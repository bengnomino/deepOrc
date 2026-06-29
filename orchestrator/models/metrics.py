from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class GatewayMetric(Base):
    __tablename__ = "gateway_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_id: Mapped[int] = mapped_column(
        ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vm_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tailscale_online: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    wg_online: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exit_node_reachable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    polled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="metrics")


class PeerMetric(Base):
    __tablename__ = "peer_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    peer_id: Mapped[int] = mapped_column(
        ForeignKey("peers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_handshake: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rx_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tx_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    polled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    peer: Mapped["Peer"] = relationship("Peer", back_populates="metrics")


from orchestrator.models.gateway import Gateway  # noqa: E402
from orchestrator.models.peer import Peer  # noqa: E402
