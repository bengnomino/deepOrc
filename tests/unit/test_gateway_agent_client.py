"""Unit tests for GatewayAgentClient incus HTTP helpers."""

from orchestrator.services.gateway_agent_client import GatewayAgentClient


def test_incus_http_script_get_uses_wget():
    client = GatewayAgentClient("10.10.1.10", "secret-token", incus_instance="gw-test")
    script = client._incus_http_script("GET", "http://127.0.0.1:8081/v1/health", None)
    assert "wget -qO-" in script
    assert "curl" not in script
    assert "Authorization: Bearer secret-token" in script
    assert "http://127.0.0.1:8081/v1/health" in script


def test_incus_http_script_post_uses_wget_with_json():
    client = GatewayAgentClient("10.10.1.10", "tok", incus_instance="gw-test")
    script = client._incus_http_script(
        "POST",
        "http://127.0.0.1:8081/v1/register",
        {"gateway_name": "gw-000"},
    )
    assert "--post-data=" in script
    assert "gateway_name" in script
    assert "Content-Type: application/json" in script


def test_incus_http_script_delete_prefers_curl():
    client = GatewayAgentClient("10.10.1.10", "tok", incus_instance="gw-test")
    script = client._incus_http_script(
        "DELETE",
        "http://127.0.0.1:8081/v1/peers/abc",
        None,
    )
    assert "command -v curl" in script
    assert "curl -sf -X DELETE" in script
    assert "-d '" not in script


def test_incus_http_script_incus_only_when_instance_set():
    client = GatewayAgentClient("10.10.1.10", "tok", incus_instance="gw-test")
    assert client._incus_instance == "gw-test"


def test_tailscale_status_falls_back_to_incus(monkeypatch):
    client = GatewayAgentClient("10.10.1.10", "tok", incus_instance="gw-test")

    def fake_request(method, path, **kwargs):
        raise RuntimeError("agent endpoint missing")

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "_tailscale_status_via_incus",
        lambda: {"status": "100.64.0.3 gw-000"},
    )
    assert client.tailscale_status() == {"status": "100.64.0.3 gw-000"}
