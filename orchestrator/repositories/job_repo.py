"""Job repository."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.job import Job, JobStatus, JobType


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, job_id: int) -> Job | None:
        return self._session.get(Job, job_id)

    def create(self, job: Job) -> Job:
        self._session.add(job)
        self._session.flush()
        return job

    def update_status(self, job: Job, status: JobStatus, error: str | None = None) -> Job:
        job.status = status
        if error is not None:
            job.error = error
        self._session.flush()
        return job

    def update_stage(self, job_id: int, stage: str, *, touch: bool = True) -> Job | None:
        job = self.get_by_id(job_id)
        if not job:
            return None
        if job.stage != stage or touch:
            job.stage = stage
            job.stage_updated_at = datetime.now(UTC)
        self._session.flush()
        return job

    def list_recent(self, limit: int = 50) -> list[Job]:
        return list(
            self._session.scalars(select(Job).order_by(Job.id.desc()).limit(limit)).all()
        )

    def get_pending_for_gateway(self, gateway_id: int) -> Job | None:
        return self._session.scalars(
            select(Job).where(
                Job.gateway_id == gateway_id,
                Job.status == JobStatus.PENDING,
            )
        ).first()

    def get_latest_create_job(self, gateway_id: int) -> Job | None:
        return self._session.scalars(
            select(Job)
            .where(Job.gateway_id == gateway_id, Job.type == JobType.CREATE_GATEWAY)
            .order_by(Job.id.desc())
        ).first()

    def get_latest_delete_job(self, gateway_id: int) -> Job | None:
        return self._session.scalars(
            select(Job)
            .where(Job.gateway_id == gateway_id, Job.type == JobType.DELETE_GATEWAY)
            .order_by(Job.id.desc())
        ).first()

    def reset_failed_job(self, gateway_id: int) -> Job | None:
        """Reset a create job so provisioning can be retried (incl. stale RUNNING)."""
        job = self.get_latest_create_job(gateway_id)
        if not job:
            return None
        if job.status in {JobStatus.FAILED, JobStatus.COMPLETED, JobStatus.RUNNING}:
            job.status = JobStatus.PENDING
            job.error = None
            self._session.flush()
        return job if job.status == JobStatus.PENDING else None
