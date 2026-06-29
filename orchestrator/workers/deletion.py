"""Background gateway deletion worker."""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from orchestrator.models.gateway import GatewayStatus
from orchestrator.models.job import Job, JobStatus, JobType
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.services.gateway_service import GatewayService

logger = logging.getLogger(__name__)
_LOCK_RETRIES = 12
_LOCK_BACKOFF_SECONDS = 0.5
_REQUEST_SETTLE_SECONDS = 0.75
_STALE_JOB_MINUTES = 10

_active: set[int] = set()
_active_lock = threading.Lock()


def _is_deletion_active(gateway_id: int) -> bool:
    with _active_lock:
        return gateway_id in _active


def _is_stale_running_job(job) -> bool:
    if job.status != JobStatus.RUNNING:
        return False
    updated = job.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated.astimezone(UTC) > timedelta(minutes=_STALE_JOB_MINUTES)


def process_deletion_job(session: Session, job_id: int, gateway_id: int) -> None:
    jobs = JobRepository(session)
    job = jobs.get_by_id(job_id)
    if not job:
        return

    jobs.update_status(job, JobStatus.RUNNING)
    session.commit()

    try:
        GatewayService(session).execute_delete_gateway(gateway_id, job_id=job_id)
        logger.info("Gateway %s deleted successfully", gateway_id)
    except Exception as exc:
        logger.exception("Deletion failed for gateway %s", gateway_id)
        session.rollback()
        job = jobs.get_by_id(job_id)
        gateway = GatewayRepository(session).get_by_id(gateway_id)
        if job:
            jobs.update_status(job, JobStatus.FAILED, str(exc))
        if gateway:
            GatewayRepository(session).update_status(
                gateway,
                GatewayStatus.ERROR,
                f"Deletion failed: {exc}",
            )
        session.commit()


def _run_gateway_deletion_once(gateway_id: int, job_id: int | None) -> None:
    from orchestrator.models.base import get_session_factory

    session = get_session_factory()()
    try:
        jobs = JobRepository(session)
        gateways = GatewayRepository(session)
        gateway = gateways.get_by_id(gateway_id)

        if not gateway:
            if job_id:
                job = jobs.get_by_id(job_id)
                if job and job.status != JobStatus.COMPLETED:
                    jobs.update_status(job, JobStatus.COMPLETED)
                    session.commit()
            return

        if gateway.status != GatewayStatus.DELETING:
            logger.info(
                "Deletion skipped for gateway %s: status %s",
                gateway_id,
                gateway.status.value,
            )
            return

        job = jobs.get_by_id(job_id) if job_id else jobs.get_latest_delete_job(gateway_id)
        if not job:
            logger.warning("Deletion skipped for gateway %s: no delete job", gateway_id)
            return

        if job.status == JobStatus.RUNNING and _is_stale_running_job(job):
            jobs.update_status(job, JobStatus.PENDING)
            session.commit()
        elif job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
            logger.info(
                "Deletion skipped for gateway %s: job %s status %s",
                gateway_id,
                job.id,
                job.status.value,
            )
            return

        process_deletion_job(session, job.id, gateway_id)
    finally:
        session.close()


def run_gateway_deletion(gateway_id: int, job_id: int | None = None) -> None:
    """Run deletion after the HTTP request session has closed."""
    time.sleep(_REQUEST_SETTLE_SECONDS)
    for attempt in range(_LOCK_RETRIES):
        try:
            _run_gateway_deletion_once(gateway_id, job_id)
            return
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt + 1 >= _LOCK_RETRIES:
                logger.exception("Deletion failed for gateway %s", gateway_id)
                return
            time.sleep(_LOCK_BACKOFF_SECONDS * (attempt + 1))


def _deletion_thread(gateway_id: int, job_id: int | None) -> None:
    try:
        run_gateway_deletion(gateway_id, job_id)
    finally:
        with _active_lock:
            _active.discard(gateway_id)


def start_deletion(gateway_id: int, job_id: int | None = None) -> None:
    """Kick off deletion in a daemon thread."""
    with _active_lock:
        if gateway_id in _active:
            logger.debug("Deletion already active for gateway %s", gateway_id)
            return
        _active.add(gateway_id)
    logger.info("Starting deletion thread for gateway %s (job %s)", gateway_id, job_id)
    threading.Thread(
        target=_deletion_thread,
        args=(gateway_id, job_id),
        name=f"delete-gateway-{gateway_id}",
        daemon=True,
    ).start()


def schedule_deletion_after_request(
    background_tasks,
    gateway_id: int,
    job_id: int,
) -> None:
    """Start deletion in a background thread (reliable vs FastAPI BackgroundTasks)."""
    start_deletion(gateway_id, job_id)


def resume_incomplete_deletions() -> int:
    """Recover gateways left deleting after a restart or failed background task."""
    from orchestrator.models.base import get_session_factory

    session = get_session_factory()()
    started = 0
    try:
        jobs = JobRepository(session)
        for gateway in GatewayRepository(session).list_all():
            if gateway.status != GatewayStatus.DELETING:
                continue
            if _is_deletion_active(gateway.id):
                continue

            latest = jobs.get_latest_delete_job(gateway.id)
            if latest and latest.status == JobStatus.RUNNING:
                if _is_stale_running_job(latest):
                    jobs.update_status(latest, JobStatus.PENDING)
                    session.commit()
                else:
                    continue

            if latest and latest.status == JobStatus.PENDING:
                start_deletion(gateway.id, latest.id)
                started += 1
            elif not latest:
                job = Job(
                    type=JobType.DELETE_GATEWAY,
                    gateway_id=gateway.id,
                    status=JobStatus.PENDING,
                )
                jobs.create(job)
                session.commit()
                start_deletion(gateway.id, job.id)
                started += 1
    finally:
        session.close()

    if started:
        logger.info("Resumed deletion for %d gateway(s)", started)
    return started
