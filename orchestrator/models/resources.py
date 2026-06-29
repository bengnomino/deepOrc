from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.models.base import Base


class PortAllocation(Base):
    __tablename__ = "port_allocations"
    __table_args__ = (UniqueConstraint("worker_id", "udp_port", name="uq_port_worker_udp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    udp_port: Mapped[int] = mapped_column(Integer, nullable=False)
    gateway_id: Mapped[int | None] = mapped_column(
        ForeignKey("gateways.id", ondelete="SET NULL"), nullable=True
    )
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IpAllocation(Base):
    __tablename__ = "ip_allocations"
    __table_args__ = (UniqueConstraint("worker_id", "address", name="uq_ip_worker_address"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(String(45), nullable=False)
    gateway_id: Mapped[int | None] = mapped_column(
        ForeignKey("gateways.id", ondelete="SET NULL"), nullable=True
    )
    peer_id: Mapped[int | None] = mapped_column(
        ForeignKey("peers.id", ondelete="SET NULL"), nullable=True
    )
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
