"""WireGuard client routing helpers."""

TAILSCALE_CIDR = "100.64.0.0/10"
BACKHAUL_GATEWAY_PEER_ALLOWED_IPS = "0.0.0.0/0, ::/0"


def ipv4_allowed_ips_backhaul_uplink(wg_subnet: str) -> str:
    """Uplink peer: only route the gateway WG LAN (internet flows gateway → peer)."""
    return wg_subnet


def ipv4_allowed_ips_backhaul(wg_subnet: str | None = None) -> str:
    """Deprecated alias — use backhaul_uplink on the client side."""
    if wg_subnet:
        return wg_subnet
    return "10.64.0.0/24"


def ipv4_allowed_ips_full_tunnel(endpoint: str, wg_subnet: str | None = None) -> str:
    """Full-tunnel AllowedIPs for the VDI peer."""
    _ = endpoint
    if wg_subnet:
        return f"{wg_subnet}, 0.0.0.0/0, ::/0"
    return "0.0.0.0/0, ::/0"
