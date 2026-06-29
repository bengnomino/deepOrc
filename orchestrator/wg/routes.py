"""WireGuard client routing helpers."""


def ipv4_allowed_ips_full_tunnel(endpoint: str, wg_subnet: str | None = None) -> str:
    """Full-tunnel AllowedIPs for the VDI peer.

    WireGuard apps bind the UDP session to the endpoint directly, so we can use
    plain defaults instead of splitting ``0.0.0.0/0`` around the VPS address.
    """
    _ = endpoint
    if wg_subnet:
        return f"{wg_subnet}, 0.0.0.0/0, ::/0"
    return "0.0.0.0/0, ::/0"
