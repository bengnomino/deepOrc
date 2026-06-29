"""Unit tests for WireGuard module."""

from orchestrator.wg.config import ClientConfigParams, ServerConfigParams, render_client_config, render_server_config
from orchestrator.wg.keys import generate_keypair


def test_generate_keypair():
    kp = generate_keypair()
    assert len(kp.private_key) == 44
    assert len(kp.public_key) == 44
    assert kp.private_key != kp.public_key


def test_render_server_config():
    cfg = render_server_config(
        ServerConfigParams(
            private_key="privkey",
            listen_port=51820,
            address="10.64.1.1",
            subnet="10.64.1.0/24",
        )
    )
    assert "PrivateKey = privkey" in cfg
    assert "ListenPort = 51820" in cfg
    assert "Address = 10.64.1.1/24" in cfg


def test_render_client_config():
    cfg = render_client_config(
        ClientConfigParams(
            private_key="peerpriv",
            address="10.64.1.2",
            dns="1.1.1.1",
            server_public_key="serverpub",
            endpoint="203.0.113.1:51001",
            allowed_ips="0.0.0.0/0, ::/0",
        )
    )
    assert "PrivateKey = peerpriv" in cfg
    assert "Endpoint = 203.0.113.1:51001" in cfg
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in cfg
