"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    secret_key: str = Field(default="change-me-in-production", min_length=16)
    api_key: str = Field(default="dev-api-key")
    database_url: str = Field(default="sqlite:///./orchestrator.db")
    api_root: str = Field(
        default="/orchestrator",
        description="HTTP prefix for orchestrator API (not /api — reserved for Headscale)",
    )

    # Host / networking
    host_public_ip: str = Field(default="127.0.0.1")
    wg_public_host: str = Field(
        default="",
        description="Public host for WireGuard endpoints (IP or hostname); defaults to HOST_PUBLIC_IP",
    )
    orch_host_ip: str = Field(
        default="10.10.0.1",
        description="IP on orch bridge used by gateway agents to reach orchestrator",
    )

    # Incus
    incus_socket: str = Field(default="/var/lib/incus/unix.socket")
    incus_network: str = Field(default="orch-br0")
    incus_image: str = Field(
        default="local:gw-golden",
        description="Incus image: local:alias for golden image, or images:debian/... for cloud",
    )
    incus_storage_pool: str = Field(default="default")
    incus_vm_memory: str = Field(default="192MiB")
    incus_vm_cpu: str = Field(default="1")
    incus_net_interface: str = Field(
        default="eth0",
        description="Guest NIC name (eth0 on OpenWrt/Alpine containers)",
    )
    incus_instance_type: str = Field(
        default="container",
        description="Incus instance type: container (tiny OpenWrt) or virtual-machine",
    )
    incus_provisioner: str = Field(
        default="openwrt",
        description="Gateway config: openwrt (incus exec setup) or cloud-init",
    )
    ip_pool_network: str = Field(default="10.10.0.0/16")
    ip_pool_start: str = Field(default="10.10.1.10")
    port_pool_start: int = Field(default=51001)
    port_pool_end: int = Field(default=52000)
    wg_subnet_base: str = Field(default="10.64")

    # Headscale / Tailscale
    headscale_url: str = Field(default="https://headscale.example.com")
    headscale_gateway_url: str = Field(
        default="",
        description="Headscale login URL for gateway VMs (defaults to http://ORCH_HOST_IP:8080)",
    )
    headscale_cli: str = Field(
        default="headscale",
        validation_alias=AliasChoices("ORCH_HEADSCALE_CLI", "HEADSCALE_CLI"),
    )
    headscale_config: str = Field(
        default="/etc/headscale/config.yaml",
        validation_alias=AliasChoices("ORCH_HEADSCALE_CONFIG", "HEADSCALE_CONFIG"),
    )
    headscale_user: str = Field(
        default="gateways",
        validation_alias=AliasChoices("ORCH_HEADSCALE_USER", "HEADSCALE_USER"),
    )
    headscale_preauth_expiration: str = Field(
        default="876000h",
        description="Preauth key lifetime for auto-provisioned gateway VMs (~100 years)",
    )
    headscale_exit_node_tag: str = Field(
        default="tag:exit",
        description="Tag for gateway exit nodes (autoApprovers in ACL); not used for mobile clients",
    )
    headscale_mobile_user: str = Field(
        default="gateways",
        description="Headscale user for mobile test clients (no exit advertisement)",
    )
    headscale_worker_tag: str = Field(
        default="tag:worker-host",
        description="Tag applied to gateway worker VPS via preauth key",
    )
    headscale_worker_user: str = Field(
        default="workers",
        description="Headscale user for gateway worker hosts",
    )

    # WireGuard defaults
    wg_dns: str = Field(default="1.1.1.1")
    wg_allowed_ips: str = Field(default="0.0.0.0/0, ::/0")
    wg_listen_port: int = Field(default=51820)

    # Workers
    metrics_poll_interval_seconds: int = Field(default=30)
    provisioning_timeout_seconds: int = Field(default=600)
    agent_port: int = Field(default=8081)

    # Gateway agent package path (embedded in cloud-init)
    gateway_agent_wheel_url: str = Field(
        default="",
        description="Minimal gateway-agent wheel URL (not full orchestrator package)",
    )

    @property
    def headscale_url_for_gateways(self) -> str:
        if self.headscale_gateway_url.strip():
            return self.headscale_gateway_url.strip()
        return f"http://{self.orch_host_ip}:8080"

    def headscale_url_for_worker(self, *, is_local: bool) -> str:
        """Login-server URL embedded in gateway VMs.

        Local CP gateways reach Headscale on the orch bridge. Remote worker VMs
        must use the public Headscale URL (bridge 10.10.0.1:8080 is the worker host).
        """
        if is_local:
            return self.headscale_url_for_gateways
        return self.headscale_url.rstrip("/")

    @property
    def wg_endpoint_host(self) -> str:
        if self.wg_public_host.strip():
            return self.wg_public_host.strip()
        if self.host_public_ip.strip() and self.host_public_ip.strip() != "127.0.0.1":
            return self.host_public_ip.strip()
        host = urlparse(self.headscale_url).hostname
        if host:
            return host
        return self.host_public_ip

    @property
    def data_dir(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.removeprefix("sqlite:///")
            return Path(db_path).expanduser().resolve().parent
        return Path("./data").resolve()

    @property
    def public_orchestrator_url(self) -> str:
        base = self.headscale_url.rstrip("/")
        root = self.api_root.rstrip("/")
        if root:
            return f"{base}{root}"
        return base


@lru_cache
def get_settings() -> Settings:
    return Settings()
