"""Gateway API routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from orchestrator.api.deps import ApiAuth, DbSession
from orchestrator.api.schemas.models import (
    GatewayCreateRequest,
    GatewayCreateResponse,
    GatewayResponse,
    GatewayUpdateRequest,
)
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.services.gateway_service import CreateGatewayRequest, GatewayService
from orchestrator.workers.provisioning import run_gateway_provisioning, schedule_provisioning_after_request
from orchestrator.workers.deletion import schedule_deletion_after_request

router = APIRouter(prefix="/gateways", tags=["gateways"])


def _to_response(gateway, endpoint: str) -> GatewayResponse:
    return GatewayResponse(
        id=gateway.id,
        name=gateway.name,
        worker_id=gateway.worker_id,
        peer_group_id=gateway.peer_group_id,
        lan_ip=gateway.lan_ip,
        macvlan_slot=gateway.macvlan_slot,
        status=gateway.status,
        vm_ip=gateway.vm_ip,
        udp_port=gateway.udp_port,
        wg_subnet=gateway.wg_subnet,
        wg_server_pubkey=gateway.wg_server_pubkey,
        exit_node_id=gateway.exit_node_id,
        tailscale_hostname=gateway.tailscale_hostname,
        endpoint=endpoint,
        error_message=gateway.error_message,
        created_at=gateway.created_at,
    )


@router.post("", response_model=GatewayCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_gateway(
    body: GatewayCreateRequest,
    session: DbSession,
    _: ApiAuth,
    background_tasks: BackgroundTasks,
) -> GatewayCreateResponse:
    service = GatewayService(session)
    try:
        result = service.create_gateway(
            CreateGatewayRequest(
                gateway_name=body.gateway_name,
                udp_port=body.udp_port,
                worker_id=body.worker_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    schedule_provisioning_after_request(
        background_tasks, result.gateway.id, result.job.id
    )

    return GatewayCreateResponse(
        gateway=_to_response(result.gateway, service.get_endpoint(result.gateway)),
        job_id=result.job.id,
    )


@router.get("", response_model=list[GatewayResponse])
def list_gateways(session: DbSession, _: ApiAuth) -> list[GatewayResponse]:
    repo = GatewayRepository(session)
    service = GatewayService(session)
    return [_to_response(g, service.get_endpoint(g)) for g in repo.list_all()]


@router.get("/{gateway_id}", response_model=GatewayResponse)
def get_gateway(gateway_id: int, session: DbSession, _: ApiAuth) -> GatewayResponse:
    repo = GatewayRepository(session)
    gateway = repo.get_by_id(gateway_id)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")
    service = GatewayService(session)
    return _to_response(gateway, service.get_endpoint(gateway))


@router.delete("/{gateway_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gateway(
    gateway_id: int,
    session: DbSession,
    _: ApiAuth,
    background_tasks: BackgroundTasks,
) -> None:
    try:
        job = GatewayService(session).request_delete_gateway(gateway_id)
        schedule_deletion_after_request(background_tasks, gateway_id, job.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{gateway_id}", response_model=GatewayResponse)
def update_gateway(
    gateway_id: int,
    body: GatewayUpdateRequest,
    session: DbSession,
    _: ApiAuth,
) -> GatewayResponse:
    service = GatewayService(session)
    gateway = GatewayRepository(session).get_by_id(gateway_id)
    if not gateway:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")

    if body.tailscale_hostname is not None:
        try:
            gateway = service.rename_tailscale_display_name(gateway_id, body.tailscale_hostname)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _to_response(gateway, service.get_endpoint(gateway))
