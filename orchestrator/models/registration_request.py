import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.models.base import Base

from orchestrator.headscale.client import REGISTRATION_KEY_MAX_LENGTH

DISPLAY_CODE_LENGTH = 6


class RegistrationRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    registration_key: Mapped[str] = mapped_column(
        String(REGISTRATION_KEY_MAX_LENGTH), unique=True, nullable=False, index=True
    )
    display_code: Mapped[str] = mapped_column(String(DISPLAY_CODE_LENGTH), nullable=False, index=True)
    status: Mapped[RegistrationRequestStatus] = mapped_column(
        Enum(RegistrationRequestStatus),
        default=RegistrationRequestStatus.PENDING,
        nullable=False,
    )
    headscale_node_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tailscale_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
