"""Worker enrollment token persistence."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.worker_enrollment import WorkerEnrollment


class WorkerEnrollmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, enrollment: WorkerEnrollment) -> WorkerEnrollment:
        self._session.add(enrollment)
        self._session.flush()
        return enrollment

    def get_by_token_hash(self, token_hash: str) -> WorkerEnrollment | None:
        return self._session.scalar(
            select(WorkerEnrollment).where(WorkerEnrollment.token_hash == token_hash)
        )

    def get_active_by_name(self, name: str) -> WorkerEnrollment | None:
        now = datetime.now(UTC)
        return self._session.scalar(
            select(WorkerEnrollment).where(
                WorkerEnrollment.name == name,
                WorkerEnrollment.used_at.is_(None),
                WorkerEnrollment.expires_at > now,
            )
        )

    def list_active_names(self) -> set[str]:
        now = datetime.now(UTC)
        rows = self._session.scalars(
            select(WorkerEnrollment.name).where(
                WorkerEnrollment.used_at.is_(None),
                WorkerEnrollment.expires_at > now,
            )
        ).all()
        return set(rows)

    def get_latest_active(self) -> WorkerEnrollment | None:
        now = datetime.now(UTC)
        return self._session.scalar(
            select(WorkerEnrollment)
            .where(
                WorkerEnrollment.used_at.is_(None),
                WorkerEnrollment.expires_at > now,
            )
            .order_by(WorkerEnrollment.created_at.desc())
            .limit(1)
        )
