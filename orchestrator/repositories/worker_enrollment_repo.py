"""Worker enrollment token persistence."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.worker_enrollment import WorkerEnrollment

logger = logging.getLogger(__name__)


class WorkerEnrollmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, enrollment: WorkerEnrollment) -> WorkerEnrollment:
        logger.info("Creating worker enrollment for: %s", enrollment.name)
        self._session.add(enrollment)
        self._session.flush()
        logger.info("Worker enrollment created successfully for: %s", enrollment.name)
        return enrollment

    def get_by_token_hash(self, token_hash: str) -> WorkerEnrollment | None:
        logger.debug("Retrieving worker enrollment by token hash")
        result = self._session.scalar(
            select(WorkerEnrollment).where(WorkerEnrollment.token_hash == token_hash)
        )
        if result:
            logger.debug("Found enrollment for worker: %s", result.name)
        else:
            logger.debug("No enrollment found for token hash")
        return result

    def get_active_by_name(self, name: str) -> WorkerEnrollment | None:
        now = datetime.now(UTC)
        logger.debug("Checking active enrollment by name: %s", name)
        result = self._session.scalar(
            select(WorkerEnrollment).where(
                WorkerEnrollment.name == name,
                WorkerEnrollment.used_at.is_(None),
                WorkerEnrollment.expires_at > now,
            )
        )
        if result:
            logger.debug("Found active enrollment for worker: %s", name)
        else:
            logger.debug("No active enrollment found for worker: %s", name)
        return result

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
