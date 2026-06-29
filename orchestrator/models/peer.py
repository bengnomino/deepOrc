from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class Peer(Base):
    __tablename__ = "peers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_id: Mapped[int] = mapped_column(ForeignKey("gateways.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    private_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="peers")
    metrics: Mapped[list["PeerMetric"]] = relationship(
        "PeerMetric", back_populates="peer", cascade="all, delete-orphan"
    )


from orchestrator.models.gateway import Gateway  # noqa: E402
from orchestrator.models.metrics import PeerMetric  # noqa: E402
