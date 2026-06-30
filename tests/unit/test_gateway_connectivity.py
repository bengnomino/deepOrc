import json
from datetime import UTC, datetime, timedelta

from orchestrator.services.gateway_connectivity import (
    tailscale_connected_from_status_json,
    wg_uplink_connected,
)


def test_tailscale_connected_requires_running_backend_and_ip():
    offline = json.dumps({"BackendState": "Stopped", "Self": {"TailscaleIPs": ["100.64.0.8"]}})
    assert tailscale_connected_from_status_json(offline) is False

    running_no_ip = json.dumps({"BackendState": "Running", "Self": {"TailscaleIPs": []}})
    assert tailscale_connected_from_status_json(running_no_ip) is False

    running = json.dumps({"BackendState": "Running", "Self": {"TailscaleIPs": ["100.64.0.8"]}})
    assert tailscale_connected_from_status_json(running) is True


def test_wg_uplink_connected_from_recent_handshake():
    recent = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    stale = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    assert wg_uplink_connected({"pk1": {"last_handshake": recent}}) is True
    assert wg_uplink_connected({"pk1": {"last_handshake": stale}}) is False
    assert wg_uplink_connected({}) is False
