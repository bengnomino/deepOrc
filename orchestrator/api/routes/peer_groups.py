"""Peer group API routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from orchestrator.api.deps import ApiAuth, DbSession
from orchestrator.api.routes.gateways import _to_response
from orchestrator.api.schemas.models import (
    GatewayCreateResponse,
    PeerGroupCreateRequest,
    PeerGroupCreateGatewaysRequest,
    PeerGroupCreateGatewaysResponse,
    PeerGroupResponse,
)
from orchestrator.services.gateway_service import GatewayService
from orchestrator.services.peer_group_service import CreatePeerGroupRequest, PeerGroupService
from orchestrator.workers.provisioning import schedule_provisioning_after_request

router = APIRouter(prefix="/peer-groups", tags=["peer-groups"])


def _group_response(group) -> PeerGroupResponse:
    return PeerGroupResponse(
        id=group.id,
        name=group.name,
        worker_id=group.worker_id,
        lan_subnet=group.lan_subnet,
        lan_start_ip=group.lan_start_ip,
        lan_gateway=group.lan_gateway,
        parent_iface=group.parent_iface,
        gateway_count=len(group.gateways),
        created_at=group.created_at,
    )


@router.post("", response_model=PeerGroupResponse, status_code=status.HTTP_201_CREATED)
def create_peer_group(body: PeerGroupCreateRequest, session: DbSession, _: ApiAuth) -> PeerGroupResponse:
    service = PeerGroupService(session)
    try:
        group = service.create_group(
            CreatePeerGroupRequest(
                name=body.name,
                worker_id=body.worker_id,
                lan_start_ip=body.lan_start_ip,
                lan_subnet=body.lan_subnet,
                lan_gateway=body.lan_gateway,
                parent_iface=body.parent_iface,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _group_response(group)


@router.get("", response_model=list[PeerGroupResponse])
def list_peer_groups(session: DbSession, _: ApiAuth) -> list[PeerGroupResponse]:
    return [_group_response(g) for g in PeerGroupService(session).list_groups()]


@router.get("/{group_id}", response_model=PeerGroupResponse)
def get_peer_group(group_id: int, session: DbSession, _: ApiAuth) -> PeerGroupResponse:
    group = PeerGroupService(session).get_group(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer group not found")
    return _group_response(group)


@router.post(
    "/{group_id}/gateways",
    response_model=PeerGroupCreateGatewaysResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_gateways_in_group(
    group_id: int,
    body: PeerGroupCreateGatewaysRequest,
    session: DbSession,
    _: ApiAuth,
    background_tasks: BackgroundTasks,
) -> PeerGroupCreateGatewaysResponse:
    service = PeerGroupService(session)
    gs = GatewayService(session)
    try:
        result = service.create_gateways(group_id, body.count)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    created: list[GatewayCreateResponse] = []
    for item in result.gateways:
        schedule_provisioning_after_request(background_tasks, item.gateway.id, item.job.id)
        created.append(
            GatewayCreateResponse(
                gateway=_to_response(item.gateway, gs.get_endpoint(item.gateway)),
                job_id=item.job.id,
            )
        )

    return PeerGroupCreateGatewaysResponse(
        group=_group_response(result.group),
        gateways=created,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer_group(group_id: int, session: DbSession, _: ApiAuth) -> None:
    try:
        PeerGroupService(session).delete_group(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
