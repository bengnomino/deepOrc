"""Tests for exit-host setup script generation."""

import base64

from orchestrator.host_setup.script import (
    _valid_wg_conf,
    render_exit_host_script,
    wg_interface_name,
)
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.peer_group import PeerGroup


def test_wg_interface_name():
    assert wg_interface_name("gw-000") == "wg-gw000"


def test_valid_wg_conf():
    good = "[Interface]\nPrivateKey = x\n\n[Peer]\nPublicKey = y\n"
    assert _valid_wg_conf(good) is True
    assert _valid_wg_conf("[Interface]\nPrivateKey = x\n") is False


def test_render_exit_host_script_uses_base64_and_mkdir_iproute2():
    group = PeerGroup(
        id=1,
        name="deeper",
        worker_id=1,
        lan_subnet="192.168.13.0/24",
        lan_start_ip="192.168.13.100",
        lan_gateway="192.168.13.254",
        parent_iface="ens18",
    )
    gateway = Gateway(
        id=1,
        worker_id=1,
        peer_group_id=1,
        lan_ip="192.168.13.100",
        macvlan_slot=100,
        name="gw-000",
        incus_instance="gw-gw-000",
        vm_ip="10.10.0.2",
        udp_port=51001,
        wg_subnet="10.64.1.0/24",
        wg_server_pubkey="pub",
        wg_server_privkey_enc="enc",
        exit_node_id="100.64.0.7",
        tailscale_auth_key_enc="enc",
        tailscale_hostname="gw-000",
        agent_token_hash="hash",
        agent_token_enc="enc",
        status=GatewayStatus.READY,
    )
    wg_conf = "[Interface]\nPrivateKey = x\nAddress = 10.64.1.2/32\n\n[Peer]\nPublicKey = y\n"
    script = render_exit_host_script(group, [(gateway, wg_conf)])
    assert "mkdir -p /etc/iproute2" in script
    assert "DEEPORC_B64_WG_GW000" in script
    assert "base64 -d" in script
    assert "DEEPORC_WG_EOF" not in script
    assert base64.b64encode(wg_conf.strip().encode()).decode() in script
    assert "mac_100" in script
    assert "wg-quick up wg-gw000" in script
    assert "skip WireGuard" not in script


def test_render_skips_not_ready_gateway():
    group = PeerGroup(
        id=1,
        name="deeper",
        worker_id=1,
        lan_subnet="192.168.13.0/24",
        lan_start_ip="192.168.13.100",
        lan_gateway="192.168.13.254",
        parent_iface="ens18",
    )
    gateway = Gateway(
        id=9,
        worker_id=1,
        peer_group_id=1,
        lan_ip="192.168.13.109",
        macvlan_slot=109,
        name="gw-009",
        incus_instance="gw-gw-009",
        vm_ip="10.10.0.2",
        udp_port=51009,
        wg_subnet="10.64.9.0/24",
        wg_server_pubkey="pub",
        wg_server_privkey_enc="enc",
        exit_node_id="pending",
        tailscale_auth_key_enc="enc",
        tailscale_hostname="gw-009",
        agent_token_hash="hash",
        agent_token_enc="enc",
        status=GatewayStatus.PROVISIONING,
    )
    script = render_exit_host_script(group, [(gateway, None)])
    assert "skip WireGuard: gw-009" in script
    assert "wg-quick up" not in script
