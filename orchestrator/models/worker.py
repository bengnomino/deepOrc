"""Incus worker nodes (gateway VPS)."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class WorkerStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DISABLED = "disabled"


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    public_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    tailscale_hostname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    incus_remote: Mapped[str | None] = mapped_column(String(64), nullable=True)
    incus_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    incus_cert_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    incus_key_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    incus_server_cert_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    worker_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    port_pool_start: Mapped[int] = mapped_column(Integer, nullable=False)
    port_pool_end: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_pool_network: Mapped[str] = mapped_column(String(18), nullable=False)
    ip_pool_start: Mapped[str] = mapped_column(String(45), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus, values_callable=lambda x: [e.value for e in x]),
        default=WorkerStatus.OFFLINE,
        nullable=False,
    )
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    network_rx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    network_tx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    gateways: Mapped[list["Gateway"]] = relationship("Gateway", back_populates="worker")

    @property
    def is_local(self) -> bool:
        return not self.incus_url


from orchestrator.models.gateway import Gateway  # noqa: E402
