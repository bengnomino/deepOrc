"""Monitoring and jobs API routes."""

from fastapi import APIRouter, HTTPException, status

from orchestrator.api.deps import ApiAuth, DbSession
from orchestrator.api.schemas.models import (
    GatewayMonitoringResponse,
    JobResponse,
    PeerMonitoringResponse,
)
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.repositories.metrics_repo import MetricsRepository
from orchestrator.repositories.peer_repo import PeerRepository

router = APIRouter(tags=["monitoring"])


@router.get("/monitoring/gateways", response_model=list[GatewayMonitoringResponse])
def monitoring_gateways(session: DbSession, _: ApiAuth) -> list[GatewayMonitoringResponse]:
    gateways = GatewayRepository(session)
    metrics = MetricsRepository(session)
    result = []
    for gateway in gateways.list_all():
        latest = metrics.latest_gateway_metric(gateway.id)
        result.append(
            GatewayMonitoringResponse(
                gateway_id=gateway.id,
                name=gateway.name,
                status=gateway.status,
                exit_node_id=gateway.exit_node_id,
                vm_status=latest.vm_status if latest else None,
                tailscale_online=latest.tailscale_online if latest else None,
                wg_online=latest.wg_online if latest else None,
                exit_node_reachable=latest.exit_node_reachable if latest else None,
            )
        )
    return result


@router.get("/monitoring/peers", response_model=list[PeerMonitoringResponse])
def monitoring_peers(session: DbSession, _: ApiAuth) -> list[PeerMonitoringResponse]:
    peers_repo = PeerRepository(session)
    metrics_repo = MetricsRepository(session)
    gateways = GatewayRepository(session).list_all()
    result = []
    for gateway in gateways:
        for peer in peers_repo.list_by_gateway(gateway.id):
            latest = metrics_repo.latest_peer_metric(peer.id)
            result.append(
                PeerMonitoringResponse(
                    peer_id=peer.id,
                    gateway_id=peer.gateway_id,
                    name=peer.name,
                    suspended=peer.suspended,
                    last_handshake=latest.last_handshake if latest else None,
                    rx_bytes=latest.rx_bytes if latest else None,
                    tx_bytes=latest.tx_bytes if latest else None,
                )
            )
    return result


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, session: DbSession, _: ApiAuth) -> JobResponse:
    job = JobRepository(session).get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResponse(
        id=job.id,
        type=job.type,
        gateway_id=job.gateway_id,
        status=job.status,
        error=job.error,
        created_at=job.created_at,
    )
