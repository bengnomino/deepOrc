"""Peer group business logic."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from orchestrator.lan.ipam import (
    allocate_lan_ip,
    default_lan_gateway,
    infer_lan_subnet,
    macvlan_slot_from_ip,
    remaining_lan_capacity,
    validate_lan_start_ip,
)
from orchestrator.models.gateway import GatewayStatus
from orchestrator.models.peer_group import PeerGroup
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.peer_group_repo import PeerGroupRepository
from orchestrator.services.gateway_service import CreateGatewayRequest, CreateGatewayResult, GatewayService
from orchestrator.services.worker_service import WorkerService


@dataclass
class CreatePeerGroupRequest:
    name: str
    worker_id: int
    lan_start_ip: str
    lan_subnet: str | None = None
    lan_gateway: str | None = None
    parent_iface: str | None = None


@dataclass
class CreateGatewaysInGroupResult:
    group: PeerGroup
    gateways: list[CreateGatewayResult]


class PeerGroupService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._groups = PeerGroupRepository(session)
        self._gateways = GatewayRepository(session)
        self._workers = WorkerService(session)
        self._gateway_service = GatewayService(session)

    def create_group(self, request: CreatePeerGroupRequest) -> PeerGroup:
        name = request.name.strip()
        if not name:
            raise ValueError("Group name is required")
        if self._groups.get_by_name(name):
            raise ValueError(f"Peer group {name} already exists")

        worker = self._workers.get_worker(request.worker_id)

        lan_subnet = request.lan_subnet or infer_lan_subnet(request.lan_start_ip)
        validate_lan_start_ip(lan_subnet, request.lan_start_ip)
        lan_gateway = request.lan_gateway or default_lan_gateway(lan_subnet)

        group = PeerGroup(
            name=name,
            worker_id=worker.id,
            lan_subnet=lan_subnet,
            lan_start_ip=request.lan_start_ip.strip(),
            lan_gateway=lan_gateway,
            parent_iface=(request.parent_iface.strip() if request.parent_iface else None),
        )
        self._groups.create(group)
        self._session.commit()
        return group

    def create_gateways(self, group_id: int, count: int) -> CreateGatewaysInGroupResult:
        if count < 1:
            raise ValueError("Count must be at least 1")
        if count > 64:
            raise ValueError("Count cannot exceed 64 per request")

        group = self._groups.get_by_id(group_id)
        if not group:
            raise ValueError(f"Peer group {group_id} not found")

        available = remaining_lan_capacity(self._session, group)
        if count > available:
            raise ValueError(
                f"Only {available} LAN address(es) left in group {group.name} ({group.lan_subnet})"
            )

        results: list[CreateGatewayResult] = []
        for _ in range(count):
            lan_ip = allocate_lan_ip(self._session, group)
            result = self._gateway_service.create_gateway(
                CreateGatewayRequest(
                    worker_id=group.worker_id,
                    peer_group_id=group.id,
                    lan_ip=lan_ip,
                    macvlan_slot=macvlan_slot_from_ip(lan_ip),
                )
            )
            results.append(result)

        self._session.commit()
        return CreateGatewaysInGroupResult(group=group, gateways=results)

    def get_group(self, group_id: int) -> PeerGroup | None:
        return self._groups.get_by_id(group_id)

    def list_groups(self) -> list[PeerGroup]:
        return self._groups.list_all()

    def delete_group(self, group_id: int) -> None:
        group = self._groups.get_by_id(group_id)
        if not group:
            raise ValueError(f"Peer group {group_id} not found")
        active = [
            g for g in group.gateways if g.status not in {GatewayStatus.DELETING}
        ]
        if active:
            raise ValueError(
                f"Peer group {group.name} still has {len(active)} gateway(s); delete them first"
            )
        self._groups.delete(group)
        self._session.commit()
