"""Peer groups — shared deeper LAN settings for batched gateway creation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class PeerGroup(Base):
    __tablename__ = "peer_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), nullable=False, index=True)
    lan_subnet: Mapped[str] = mapped_column(String(18), nullable=False)
    lan_start_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    lan_gateway: Mapped[str | None] = mapped_column(String(45), nullable=True)
    parent_iface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    worker: Mapped["Worker"] = relationship("Worker", back_populates="peer_groups")
    gateways: Mapped[list["Gateway"]] = relationship("Gateway", back_populates="peer_group")


from orchestrator.models.gateway import Gateway  # noqa: E402
from orchestrator.models.worker import Worker  # noqa: E402
