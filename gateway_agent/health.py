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
        return bool(prefs.get("AdvertiseExitNode"))
    except json.JSONDecodeError:
        return "advertiseexitnode" in result.stdout.replace(" ", "").lower()


def collect_health(interface: str = "wg0") -> HealthStatus:
    return HealthStatus(
        wg_online=interface_up(interface),
        tailscale_online=tailscale_online(),
        nft_running=nft_running(),
        exit_node_configured=exit_node_configured(),
    )
