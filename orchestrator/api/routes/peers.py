"""Peer API routes."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse

from orchestrator.api.deps import ApiAuth, DbSession
from orchestrator.api.schemas.models import PeerCreateRequest, PeerCreateResponse, PeerResponse
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.peer_service import PeerService

router = APIRouter(tags=["peers"])


def _peer_response(peer) -> PeerResponse:
    return PeerResponse(
        id=peer.id,
        gateway_id=peer.gateway_id,
        name=peer.name,
        public_key=peer.public_key,
        allowed_ip=peer.allowed_ip,
        suspended=peer.suspended,
        created_at=peer.created_at,
    )


@router.post(
    "/gateways/{gateway_id}/peers",
    response_model=PeerCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_peer(
    gateway_id: int,
    body: PeerCreateRequest,
    session: DbSession,
    _: ApiAuth,
) -> PeerCreateResponse:
    service = PeerService(session)
    try:
        result = service.create_peer(gateway_id, body.peer_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PeerCreateResponse(peer=_peer_response(result.peer), client_conf=result.client_conf)


@router.get("/gateways/{gateway_id}/peers", response_model=list[PeerResponse])
def list_peers(gateway_id: int, session: DbSession, _: ApiAuth) -> list[PeerResponse]:
    if not GatewayRepository(session).get_by_id(gateway_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found")
    peers = PeerRepository(session).list_by_gateway(gateway_id)
    return [_peer_response(p) for p in peers]


@router.get("/peers/{peer_id}/config", response_class=PlainTextResponse)
def export_peer_config(peer_id: int, session: DbSession, _: ApiAuth) -> str:
    service = PeerService(session)
    try:
        return service.export_config(peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/peers/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(peer_id: int, session: DbSession, _: ApiAuth) -> None:
    service = PeerService(session)
    try:
        service.delete_peer(peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/peers/{peer_id}/regenerate", response_model=PeerCreateResponse)
def regenerate_peer(peer_id: int, session: DbSession, _: ApiAuth) -> PeerCreateResponse:
    service = PeerService(session)
    try:
        result = service.regenerate_peer_keys(peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PeerCreateResponse(peer=_peer_response(result.peer), client_conf=result.client_conf)


@router.post("/peers/{peer_id}/suspend", response_model=PeerResponse)
def suspend_peer(peer_id: int, session: DbSession, _: ApiAuth) -> PeerResponse:
    service = PeerService(session)
    try:
        peer = service.suspend_peer(peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _peer_response(peer)


@router.post("/peers/{peer_id}/resume", response_model=PeerResponse)
def resume_peer(peer_id: int, session: DbSession, _: ApiAuth) -> PeerResponse:
    service = PeerService(session)
    try:
        peer = service.resume_peer(peer_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _peer_response(peer)
