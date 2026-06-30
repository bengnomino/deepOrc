"""Unit tests for gateway agent wg_handler parsing."""

from unittest.mock import patch

from gateway_agent.health import tailscale_status_text
from gateway_agent.wg_handler import list_peers


def test_tailscale_status_text_returns_stdout():
    with patch(
        "gateway_agent.health.subprocess.run",
        return_value=type("R", (), {"returncode": 0, "stdout": "100.64.0.3 gw-000\n", "stderr": ""})(),
    ):
        assert tailscale_status_text() == "100.64.0.3 gw-000"


def test_list_peers_parses_dump():
    dump = (
        "priv\tpub\t51820\toff\n"
        "peerpub1\t(none)\t(none)\t10.64.1.2/32\t1640000000\t1024\t2048\toff\n"
    )
    with patch("gateway_agent.wg_handler._run_wg", return_value=dump):
        peers = list_peers()
    assert len(peers) == 1
    assert peers[0].public_key == "peerpub1"
    assert peers[0].allowed_ips == "10.64.1.2/32"
    assert peers[0].rx_bytes == 1024
    assert peers[0].tx_bytes == 2048
