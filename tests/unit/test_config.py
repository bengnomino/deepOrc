"""Settings helpers."""

from orchestrator.config import Settings


def test_wg_endpoint_host_prefers_explicit_domain():
    settings = Settings(
        wg_public_host="wg.example.com",
        headscale_url="https://orchtest.harlock.network",
        host_public_ip="203.0.113.1",
    )
    assert settings.wg_endpoint_host == "wg.example.com"


def test_wg_endpoint_host_falls_back_to_public_ip_before_headscale_url():
    settings = Settings(
        headscale_url="https://orchtest.harlock.network",
        host_public_ip="203.0.113.1",
    )
    assert settings.wg_endpoint_host == "203.0.113.1"


def test_wg_endpoint_host_falls_back_to_public_ip():
    settings = Settings(headscale_url="", host_public_ip="203.0.113.1")
    assert settings.wg_endpoint_host == "203.0.113.1"


def test_headscale_url_for_worker_local_uses_bridge():
    settings = Settings(
        headscale_url="https://orchtest.harlock.network",
        headscale_gateway_url="http://10.10.0.1:8080",
    )
    assert settings.headscale_url_for_worker(is_local=True) == "http://10.10.0.1:8080"


def test_headscale_url_for_worker_remote_uses_public_url():
    settings = Settings(
        headscale_url="https://orchtest.harlock.network",
        headscale_gateway_url="http://10.10.0.1:8080",
    )
    assert settings.headscale_url_for_worker(is_local=False) == "https://orchtest.harlock.network"
