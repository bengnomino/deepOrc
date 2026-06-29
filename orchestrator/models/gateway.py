import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base


class GatewayStatus(str, enum.Enum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    ERROR = "error"
    DELETING = "deleting"


class Gateway(Base):
    __tablename__ = "gateways"
    __table_args__ = (UniqueConstraint("worker_id", "udp_port", name="uq_gateway_worker_udp_port"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    incus_instance: Mapped[str] = mapped_column(String(128), nullable=False)
    vm_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    udp_port: Mapped[int] = mapped_column(Integer, nullable=False)
    wg_subnet: Mapped[str] = mapped_column(String(18), nullable=False)
    wg_server_pubkey: Mapped[str] = mapped_column(String(64), nullable=False)
    wg_server_privkey_enc: Mapped[str] = mapped_column(Text, nullable=False)
    exit_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tailscale_auth_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    tailscale_hostname: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GatewayStatus] = mapped_column(
        Enum(GatewayStatus), default=GatewayStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    peers: Mapped[list["Peer"]] = relationship("Peer", back_populates="gateway", cascade="all, delete-orphan")
    worker: Mapped["Worker"] = relationship("Worker", back_populates="gateways")
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="gateway", cascade="all, delete-orphan")
    metrics: Mapped[list["GatewayMetric"]] = relationship(
        "GatewayMetric", back_populates="gateway", cascade="all, delete-orphan"
    )


from orchestrator.models.job import Job  # noqa: E402
from orchestrator.models.metrics import GatewayMetric  # noqa: E402
from orchestrator.models.peer import Peer  # noqa: E402
from orchestrator.models.worker import Worker  # noqa: E402
