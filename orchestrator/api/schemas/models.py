"""Pydantic API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from orchestrator.models.gateway import GatewayStatus
from orchestrator.models.job import JobStatus, JobType
from orchestrator.models.worker import WorkerStatus
from orchestrator.services.host_stats import HostStats


class GatewayUpdateRequest(BaseModel):
    tailscale_hostname: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Display name on Headscale (internal gateway name unchanged)",
    )


class GatewayCreateRequest(BaseModel):
    gateway_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional; auto-generated as gw-000, gw-001, … if omitted",
    )
    udp_port: int | None = Field(default=None, ge=1, le=65535)
    worker_id: int | None = Field(
        default=None,
        description="Gateway worker VPS; required when multiple workers are online",
    )


class GatewayResponse(BaseModel):
    id: int
    name: str
    worker_id: int
    status: GatewayStatus
    vm_ip: str
    udp_port: int
    wg_subnet: str
    wg_server_pubkey: str
    exit_node_id: str
    tailscale_hostname: str
    endpoint: str
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkerRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    public_ip: str = Field(min_length=7, max_length=45)
    tailscale_hostname: str | None = Field(default=None, max_length=128)
    incus_remote: str | None = Field(default=None, max_length=64)
    incus_url: str | None = Field(default=None, max_length=512)
    incus_cert_path: str | None = Field(default=None, max_length=512)
    incus_key_path: str | None = Field(default=None, max_length=512)
    incus_server_cert_path: str | None = Field(default=None, max_length=512)
    port_pool_start: int | None = Field(default=None, ge=1, le=65535)
    port_pool_end: int | None = Field(default=None, ge=1, le=65535)
    ip_pool_network: str | None = Field(default=None, max_length=18)
    ip_pool_start: str | None = Field(default=None, max_length=45)


class WorkerRegisterResponse(BaseModel):
    id: int
    name: str
    worker_token: str


class WorkerEnrollCompleteRequest(BaseModel):
    tailscale_hostname: str = Field(min_length=1, max_length=128)
    tailscale_ip: str = Field(min_length=7, max_length=45)
    incus_trust_token: str = Field(min_length=8, max_length=4096)
    public_ip: str = Field(min_length=7, max_length=45)


class WorkerHeartbeatRequest(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_total_mb: int = Field(ge=0)
    memory_used_mb: int = Field(ge=0)
    memory_percent: float = Field(ge=0, le=100)
    network_rx_bytes_per_sec: float = Field(ge=0)
    network_tx_bytes_per_sec: float = Field(ge=0)

    def to_host_stats(self) -> HostStats:
        return HostStats(
            cpu_percent=self.cpu_percent,
            memory_total_mb=self.memory_total_mb,
            memory_used_mb=self.memory_used_mb,
            memory_percent=self.memory_percent,
            network_interface="",
            network_rx_bytes_per_sec=self.network_rx_bytes_per_sec,
            network_tx_bytes_per_sec=self.network_tx_bytes_per_sec,
            load_avg=[],
        )


class WorkerResponse(BaseModel):
    id: int
    name: str
    display_name: str
    public_ip: str
    tailscale_hostname: str | None = None
    incus_remote: str | None = None
    enabled: bool
    status: WorkerStatus
    cpu_percent: float | None = None
    memory_total_mb: int | None = None
    memory_used_mb: int | None = None
    memory_percent: float | None = None
    network_rx_bps: float | None = None
    network_tx_bps: float | None = None
    last_seen_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GatewayCreateResponse(BaseModel):
    gateway: GatewayResponse
    job_id: int


class PeerCreateRequest(BaseModel):
    peer_name: str = Field(min_length=1, max_length=128)


class PeerResponse(BaseModel):
    id: int
    gateway_id: int
    name: str
    public_key: str
    allowed_ip: str
    suspended: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PeerCreateResponse(BaseModel):
    peer: PeerResponse
    client_conf: str


class JobResponse(BaseModel):
    id: int
    type: JobType
    gateway_id: int | None
    status: JobStatus
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GatewayMonitoringResponse(BaseModel):
    gateway_id: int
    name: str
    status: GatewayStatus
    exit_node_id: str
    vm_status: str | None = None
    tailscale_online: bool | None = None
    wg_online: bool | None = None
    exit_node_reachable: bool | None = None


class PeerMonitoringResponse(BaseModel):
    peer_id: int
    gateway_id: int
    name: str
    suspended: bool
    last_handshake: datetime | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
