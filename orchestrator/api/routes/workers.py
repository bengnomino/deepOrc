"""Worker registration and heartbeat API."""

import logging
from fastapi import APIRouter, Header, HTTPException, status

from orchestrator.api.deps import ApiAuth, DbSession
from orchestrator.api.schemas.models import (
    WorkerEnrollCompleteRequest,
    WorkerHeartbeatRequest,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
    WorkerResponse,
)
from orchestrator.models.worker import WorkerStatus
from orchestrator.services.worker_service import CompleteEnrollmentRequest, WorkerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workers", tags=["workers"])


def _to_response(worker, *, status: WorkerStatus | None = None) -> WorkerResponse:
    return WorkerResponse(
        id=worker.id,
        name=worker.name,
        display_name=worker.display_name,
        public_ip=worker.public_ip,
        tailscale_hostname=worker.tailscale_hostname,
        incus_remote=worker.incus_remote,
        enabled=worker.enabled,
        status=status or worker.status,
        cpu_percent=worker.cpu_percent,
        memory_total_mb=worker.memory_total_mb,
        memory_used_mb=worker.memory_used_mb,
        memory_percent=worker.memory_percent,
        network_rx_bps=worker.network_rx_bps,
        network_tx_bps=worker.network_tx_bps,
        last_seen_at=worker.last_seen_at,
        created_at=worker.created_at,
    )


@router.get("", response_model=list[WorkerResponse])
def list_workers(session: DbSession, _: ApiAuth) -> list[WorkerResponse]:
    service = WorkerService(session)
    return [
        _to_response(row["worker"], status=row["status"])
        for row in service.dashboard_workers()
    ]


@router.post("/register", response_model=WorkerRegisterResponse, status_code=status.HTTP_201_CREATED)
def register_worker(body: WorkerRegisterRequest, session: DbSession, _: ApiAuth) -> WorkerRegisterResponse:
    logger.info("Worker registration request received for worker: %s", body.name)
    service = WorkerService(session)
    try:
        result = service.register_worker(
            name=body.name,
            display_name=body.display_name,
            public_ip=body.public_ip,
            tailscale_hostname=body.tailscale_hostname,
            incus_remote=body.incus_remote,
            incus_url=body.incus_url,
            incus_cert_path=body.incus_cert_path,
            incus_key_path=body.incus_key_path,
            incus_server_cert_path=body.incus_server_cert_path,
            port_pool_start=body.port_pool_start,
            port_pool_end=body.port_pool_end,
            ip_pool_network=body.ip_pool_network,
            ip_pool_start=body.ip_pool_start,
        )
    except ValueError as exc:
        logger.warning("Worker registration failed for worker: %s - %s", body.name, str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    logger.info("Worker registration completed successfully for worker: %s", body.name)
    return WorkerRegisterResponse(
        id=result.worker.id,
        name=result.worker.name,
        worker_token=result.worker_token,
    )


@router.post("/enroll/complete", response_model=WorkerRegisterResponse, status_code=status.HTTP_201_CREATED)
def complete_worker_enrollment(
    body: WorkerEnrollCompleteRequest,
    session: DbSession,
    x_enroll_token: str | None = Header(default=None, alias="X-Enroll-Token"),
) -> WorkerRegisterResponse:
    logger.info("Worker enrollment completion request received")
    if not x_enroll_token:
        logger.warning("Enrollment completion failed - enrollment token required")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Enrollment token required")

    service = WorkerService(session)
    try:
        result = service.complete_enrollment(
            x_enroll_token,
            CompleteEnrollmentRequest(
                tailscale_hostname=body.tailscale_hostname,
                tailscale_ip=body.tailscale_ip,
                incus_trust_token=body.incus_trust_token,
                public_ip=body.public_ip,
            ),
        )
    except ValueError as exc:
        logger.warning("Worker enrollment completion failed - %s", str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    logger.info("Worker enrollment completed successfully for worker: %s", result.worker.name)
    return WorkerRegisterResponse(
        id=result.worker.id,
        name=result.worker.name,
        worker_token=result.worker_token,
    )


@router.post("/{worker_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def worker_heartbeat(
    worker_id: int,
    body: WorkerHeartbeatRequest,
    session: DbSession,
    authorization: str | None = Header(default=None),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> None:
    logger.info("Heartbeat received for worker ID: %d", worker_id)
    token = x_worker_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        logger.warning("Heartbeat failed - worker token required for worker ID: %d", worker_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token required")

    service = WorkerService(session)
    try:
        worker = service.authenticate_worker(worker_id, token)
    except ValueError as exc:
        logger.warning("Heartbeat authentication failed for worker ID: %d - %s", worker_id, str(exc))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    logger.debug("Heartbeat processing for worker ID: %d", worker_id)
    service.record_heartbeat(worker, body.to_host_stats())
    logger.info("Heartbeat processed successfully for worker ID: %d", worker_id)
