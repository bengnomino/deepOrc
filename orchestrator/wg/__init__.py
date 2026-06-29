"""WireGuard module."""

from orchestrator.wg.config import ClientConfigParams, ServerConfigParams, render_client_config, render_server_config
from orchestrator.wg.ipam import SubnetAllocation, allocate_peer_ip, allocate_wg_subnet, release_peer_ip
from orchestrator.wg.routes import ipv4_allowed_ips_backhaul, ipv4_allowed_ips_full_tunnel
from orchestrator.wg.keys import WireGuardKeyPair, generate_keypair

__all__ = [
    "ClientConfigParams",
    "ServerConfigParams",
    "SubnetAllocation",
    "WireGuardKeyPair",
    "allocate_peer_ip",
    "allocate_wg_subnet",
    "generate_keypair",
    "ipv4_allowed_ips_backhaul",
    "ipv4_allowed_ips_full_tunnel",
    "release_peer_ip",
    "render_client_config",
    "render_server_config",
]
