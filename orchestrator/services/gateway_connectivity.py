"""Gateway link connectivity — not interface presence."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from orchestrator.headscale.client import PEER_ONLINE_HANDSHAKE_SECONDS


def tailscale_connected_from_status_json(raw: str) -> bool:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if data.get("BackendState") != "Running":
        return False
    ips = (data.get("Self") or {}).get("TailscaleIPs") or []
    return any("." in str(ip) for ip in ips)


def wg_uplink_connected(peer_stats: dict[str, dict]) -> bool:
    """True when a backhaul WG peer has a recent handshake."""
    if not peer_stats:
        return False
    now = datetime.now(UTC)
    for stats in peer_stats.values():
        last_hs = stats.get("last_handshake")
        if not last_hs:
            continue
        raw = str(last_hs).replace("Z", "+00:00")
        last = datetime.fromisoformat(raw)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if (now - last).total_seconds() < PEER_ONLINE_HANDSHAKE_SECONDS:
            return True
    return False
