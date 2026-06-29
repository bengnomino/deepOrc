"""Registration request repository."""

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.registration_request import (
    DISPLAY_CODE_LENGTH,
    RegistrationRequest,
    RegistrationRequestStatus,
)


class RegistrationRequestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _allocate_display_code(self) -> str:
        for _ in range(50):
            code = f"{secrets.randbelow(1_000_000):0{DISPLAY_CODE_LENGTH}d}"
            taken = self._session.scalars(
                select(RegistrationRequest).where(
                    RegistrationRequest.display_code == code,
                    RegistrationRequest.status == RegistrationRequestStatus.PENDING,
                )
            ).first()
            if not taken:
                return code
        raise RuntimeError("Unable to allocate a unique display code")

    def get_by_key(self, registration_key: str) -> RegistrationRequest | None:
        return self._session.scalars(
            select(RegistrationRequest).where(
                RegistrationRequest.registration_key == registration_key
            )
        ).first()

    def get_by_display_code(self, display_code: str) -> RegistrationRequest | None:
        return self._session.scalars(
            select(RegistrationRequest).where(
                RegistrationRequest.display_code == display_code,
                RegistrationRequest.status == RegistrationRequestStatus.PENDING,
            )
        ).first()

    def list_pending(self) -> list[RegistrationRequest]:
        return list(
            self._session.scalars(
                select(RegistrationRequest)
                .where(RegistrationRequest.status == RegistrationRequestStatus.PENDING)
                .order_by(RegistrationRequest.created_at.desc())
            ).all()
        )

    def touch_pending(self, registration_key: str) -> RegistrationRequest:
        existing = self.get_by_key(registration_key)
        if existing:
            if existing.status != RegistrationRequestStatus.PENDING:
                return existing
            existing.created_at = datetime.now(UTC)
            self._session.flush()
            return existing
        row = RegistrationRequest(
            registration_key=registration_key,
            display_code=self._allocate_display_code(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def mark_approved(
        self,
        registration_key: str,
        headscale_node_id: int,
        tailscale_ip: str,
    ) -> RegistrationRequest | None:
        row = self.get_by_key(registration_key)
        if not row:
            return None
        row.status = RegistrationRequestStatus.APPROVED
        row.headscale_node_id = headscale_node_id
        row.tailscale_ip = tailscale_ip
        row.resolved_at = datetime.now(UTC)
        self._session.flush()
        return row

    def mark_rejected(self, registration_key: str) -> RegistrationRequest | None:
        row = self.get_by_key(registration_key)
        if not row:
            return None
        row.status = RegistrationRequestStatus.REJECTED
        row.resolved_at = datetime.now(UTC)
        self._session.flush()
        return row
