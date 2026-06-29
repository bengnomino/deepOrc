"""Build exit-host setup scripts for peer groups."""

from sqlalchemy.orm import Session

from orchestrator.host_setup.script import render_exit_host_script, render_exit_host_teardown_script
from orchestrator.models.gateway import Gateway
from orchestrator.models.peer_group import PeerGroup
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.peer_group_repo import PeerGroupRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.peer_service import PeerService, default_backhaul_peer_name


class ExitHostScriptService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._groups = PeerGroupRepository(session)
        self._gateways = GatewayRepository(session)
        self._peers = PeerRepository(session)

    def _group_gateways(self, group_id: int) -> list[Gateway]:
        return [g for g in self._gateways.list_all() if g.peer_group_id == group_id]

    def _wg_conf_for_gateway(self, gateway: Gateway) -> str | None:
        peer_name = default_backhaul_peer_name(gateway.name)
        for peer in self._peers.list_by_gateway(gateway.id):
            if peer.name == peer_name:
                return PeerService(self._session).export_config(peer.id)
        return None

    def build_setup_script(self, group_id: int) -> tuple[PeerGroup, str]:
        group = self._groups.get_by_id(group_id)
        if not group:
            raise ValueError(f"Peer group {group_id} not found")
        gateways = sorted(self._group_gateways(group_id), key=lambda g: (g.macvlan_slot or 0, g.id))
        entries = [(gw, self._wg_conf_for_gateway(gw)) for gw in gateways]
        return group, render_exit_host_script(group, entries)

    def build_teardown_script(self, group_id: int) -> tuple[PeerGroup, str]:
        group = self._groups.get_by_id(group_id)
        if not group:
            raise ValueError(f"Peer group {group_id} not found")
        gateways = sorted(self._group_gateways(group_id), key=lambda g: (g.macvlan_slot or 0, g.id))
        return group, render_exit_host_teardown_script(group, gateways)
