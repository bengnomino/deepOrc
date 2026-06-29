"""Background provisioning worker."""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from orchestrator.models.gateway import GatewayStatus
from orchestrator.models.job import JobStatus
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.services.gateway_service import GatewayService
from orchestrator.workers.provisioning_stages import (
    STAGE_DONE,
    STAGE_PREPARING,
    STAGE_QUEUED,
    set_provision_stage,
)

logger = logging.getLogger(__name__)
_LOCK_RETRIES = 12
_LOCK_BACKOFF_SECONDS = 0.5
_REQUEST_SETTLE_SECONDS = 0.75
_STALE_JOB_MINUTES = 10


@dataclass
class ProvisioningQueue:
    _pending: list[tuple[int, int]] = field(default_factory=list)

    def enqueue(self, job_id: int, gateway_id: int) -> None:
        self._pending.append((job_id, gateway_id))

    def pop(self) -> tuple[int, int] | None:
        if not self._pending:
            return None
        return self._pending.pop(0)


queue = ProvisioningQueue()
_active: set[int] = set()
_active_lock = threading.Lock()


def _is_provisioning_active(gateway_id: int) -> bool:
    with _active_lock:
        return gateway_id in _active


def _is_stale_running_job(job) -> bool:
    if job.status != JobStatus.RUNNING:
        return False
    updated = job.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated.astimezone(UTC) > timedelta(minutes=_STALE_JOB_MINUTES)


def process_provisioning_job(session: Session, job_id: int, gateway_id: int) -> None:
    jobs = JobRepository(session)
    gateways = GatewayRepository(session)
    service = GatewayService(session)

    job = jobs.get_by_id(job_id)
    gateway = gateways.get_by_id(gateway_id)
    if not job or not gateway:
        return

    jobs.update_status(job, JobStatus.RUNNING)
    set_provision_stage(session, job_id, STAGE_PREPARING)
    session.commit()

    try:
        service.provision_gateway(gateway_id, job_id=job_id)
        jobs.update_status(job, JobStatus.COMPLETED)
        set_provision_stage(session, job_id, STAGE_DONE)
        session.commit()
        logger.info("Gateway %s provisioned successfully", gateway.name)
    except Exception as exc:
        logger.exception("Provisioning failed for gateway %s", gateway.name)
        session.rollback()
        job = jobs.get_by_id(job_id)
        gateway = gateways.get_by_id(gateway_id)
        if job and gateway:
            gateways.update_status(gateway, GatewayStatus.ERROR, str(exc))
            jobs.update_status(job, JobStatus.FAILED, str(exc))
            session.commit()


def drain_queue(session: Session) -> int:
    processed = 0
    while True:
        item = queue.pop()
        if item is None:
            break
        job_id, gateway_id = item
        process_provisioning_job(session, job_id, gateway_id)
        processed += 1
    return processed


def _run_gateway_provisioning_once(gateway_id: int, job_id: int | None) -> None:
    from orchestrator.models.base import get_session_factory

    session = get_session_factory()()
    try:
        service = GatewayService(session)
        gateways = GatewayRepository(session)
        jobs = JobRepository(session)
        gateway = gateways.get_by_id(gateway_id)
        if not gateway:
            logger.warning("Provisioning skipped: gateway %s not found", gateway_id)
            return
        if not service.needs_provisioning(gateway):
            logger.info(
                "Provisioning skipped for %s: status %s",
                gateway.name,
                gateway.status.value,
            )
            return

        job = jobs.get_by_id(job_id) if job_id else jobs.get_pending_for_gateway(gateway_id)
        if not job:
            service.prepare_provisioning(gateway_id)
            job = jobs.get_pending_for_gateway(gateway_id)
        elif job.status == JobStatus.RUNNING and _is_stale_running_job(job):
            service.prepare_provisioning(gateway_id)
            job = jobs.get_pending_for_gateway(gateway_id)
        elif job.status != JobStatus.PENDING:
            logger.info(
                "Provisioning skipped for %s: job %s status %s",
                gateway.name,
                job.id,
                job.status.value,
            )
            return

        if not job:
            logger.warning("Provisioning skipped for gateway %s: no pending job", gateway_id)
            return

        set_provision_stage(session, job.id, STAGE_QUEUED)
        session.commit()
        process_provisioning_job(session, job.id, gateway_id)
    finally:
        session.close()


def run_gateway_provisioning(gateway_id: int, job_id: int | None = None) -> None:
    """Run provisioning after the HTTP request session has closed."""
    time.sleep(_REQUEST_SETTLE_SECONDS)
    for attempt in range(_LOCK_RETRIES):
        try:
            _run_gateway_provisioning_once(gateway_id, job_id)
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt + 1 >= _LOCK_RETRIES:
                logger.exception("Provisioning failed for gateway %s", gateway_id)
                return
            time.sleep(_LOCK_BACKOFF_SECONDS * (attempt + 1))


def _provisioning_thread(gateway_id: int, job_id: int | None) -> None:
    try:
        run_gateway_provisioning(gateway_id, job_id)
    finally:
        with _active_lock:
            _active.discard(gateway_id)


def start_provisioning(gateway_id: int, job_id: int | None = None) -> None:
    """Kick off provisioning in a daemon thread."""
    with _active_lock:
        if gateway_id in _active:
            logger.debug("Provisioning already active for gateway %s", gateway_id)
            return
        _active.add(gateway_id)
    logger.info("Starting provisioning thread for gateway %s (job %s)", gateway_id, job_id)
    threading.Thread(
        target=_provisioning_thread,
        args=(gateway_id, job_id),
        name=f"provision-gateway-{gateway_id}",
        daemon=True,
    ).start()


def schedule_provisioning_after_request(
    background_tasks,
    gateway_id: int,
    job_id: int,
) -> None:
    """Start provisioning in a background thread (reliable vs FastAPI BackgroundTasks)."""
    start_provisioning(gateway_id, job_id)


def resume_incomplete_provisioning() -> int:
    """Recover gateways left pending after a restart or failed background task."""
    from orchestrator.models.base import get_session_factory

    session = get_session_factory()()
    started = 0
    try:
        service = GatewayService(session)
        jobs = JobRepository(session)
        for gateway in GatewayRepository(session).list_all():
            if not service.needs_provisioning(gateway):
                continue
            if _is_provisioning_active(gateway.id):
                continue
            latest = jobs.get_latest_create_job(gateway.id)
            if latest and latest.status == JobStatus.RUNNING:
                if _is_stale_running_job(latest) or not _is_provisioning_active(gateway.id):
                    service.prepare_provisioning(gateway.id)
                    latest = jobs.get_pending_for_gateway(gateway.id)
                else:
                    continue
            if latest and latest.status == JobStatus.PENDING:
                start_provisioning(gateway.id, latest.id)
                started += 1
            elif not latest:
                service.prepare_provisioning(gateway.id)
                latest = jobs.get_pending_for_gateway(gateway.id)
                if latest:
                    start_provisioning(gateway.id, latest.id)
                    started += 1
        session.commit()
    finally:
        session.close()
    if started:
        logger.info("Resumed provisioning for %d gateway(s)", started)
    return started
