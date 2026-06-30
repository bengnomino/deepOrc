"""Health checks for gateway components."""

import subprocess
from dataclasses import dataclass

from gateway_agent.wg_handler import interface_up


@dataclass
class HealthStatus:
    wg_online: bool
    tailscale_online: bool
    nft_running: bool
    exit_node_configured: bool


def tailscale_online() -> bool:
    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and '"Online": true' in result.stdout


def tailscale_status_text() -> str:
    """Human-readable output of `tailscale status` inside the gateway."""
    result = subprocess.run(
        ["/usr/sbin/tailscale", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "tailscale status failed").strip()
        raise RuntimeError(detail)
    return result.stdout.strip() or "(empty)"


def nft_running() -> bool:
    result = subprocess.run(["systemctl", "is-active", "nftables"], capture_output=True, text=True)
    return result.stdout.strip() == "active"


def exit_node_configured() -> bool:
    """True when this gateway advertises itself as a Tailscale exit node."""
    result = subprocess.run(
        ["tailscale", "debug", "prefs"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        import json

        prefs = json.loads(result.stdout)
        if prefs.get("AdvertiseExitNode"):
            return True
        routes = prefs.get("AdvertiseRoutes") or []
        return "0.0.0.0/0" in routes
    except json.JSONDecodeError:
        return "advertiseexitnode" in result.stdout.replace(" ", "").lower()


def fetch_egress_public_ip() -> str:
    """Public IPv4 as seen from the gateway default route (exit path)."""
    import ipaddress

    errors: list[str] = []
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        result = subprocess.run(
            ["wget", "-qO-", "-T", "10", url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(result.stderr.strip() or result.stdout.strip() or url)
            continue
        candidate = result.stdout.strip().splitlines()[0].strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            errors.append(f"invalid response from {url}: {candidate!r}")
            continue
        return candidate
    raise RuntimeError(errors[-1] if errors else "egress ip lookup failed")


def collect_health(interface: str = "wg0") -> HealthStatus:
    return HealthStatus(
        wg_online=interface_up(interface),
        tailscale_online=tailscale_online(),
        nft_running=nft_running(),
        exit_node_configured=exit_node_configured(),
    )
