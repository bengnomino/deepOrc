"""Tests for WireGuard routing helpers."""

from orchestrator.wg.routes import ipv4_allowed_ips_full_tunnel


def test_full_tunnel_uses_default_routes():
    allowed = ipv4_allowed_ips_full_tunnel("46.101.152.153:51001", "10.64.2.0/24")
    assert allowed == "10.64.2.0/24, 0.0.0.0/0, ::/0"


def test_full_tunnel_without_wg_subnet():
    allowed = ipv4_allowed_ips_full_tunnel("46.101.152.153:51001")
    assert allowed == "0.0.0.0/0, ::/0"
