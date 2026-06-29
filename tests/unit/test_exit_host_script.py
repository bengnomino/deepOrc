"""Tests for exit-host setup script generation."""

from orchestrator.host_setup.script import render_exit_host_script, wg_interface_name
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.peer_group import PeerGroup


def test_wg_interface_name():
    assert wg_interface_name("gw-000") == "wg-gw000"


def test_render_exit_host_script_includes_macvlan_and_wg():
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
    assert "mac_100" in script
    assert "192.168.13.100" in script
    assert "wg-gw000" in script
    assert "wg-quick up wg-gw000" in script
    assert "DEEPORC_WG_EOF" in script
    assert "PARENT_IFACE" in script
    assert "no sudo" in script.lower() or "Run as root" in script
