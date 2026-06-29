import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class JobType(str, enum.Enum):
    CREATE_GATEWAY = "create_gateway"
    DELETE_GATEWAY = "delete_gateway"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    gateway_id: Mapped[int | None] = mapped_column(
        ForeignKey("gateways.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    gateway: Mapped["Gateway | None"] = relationship("Gateway", back_populates="jobs")


from orchestrator.models.gateway import Gateway  # noqa: E402
