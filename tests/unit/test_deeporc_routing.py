"""Tests for OpenWrt deeporc-routing script template."""

from pathlib import Path

ROUTING = (
    Path(__file__).resolve().parents[2]
    / "orchestrator/cloudinit/templates/_fragments/deeporc-routing.sh"
)


def test_deeporc_routing_default_via_wg0():
    text = ROUTING.read_text()
    assert 'ip route replace default dev "$UPLINK_IF" table main' in text
    assert "WAN_TABLE=100" in text
    assert "lookup \"$WAN_TABLE\"" in text
    assert "iif \"$TS_IF\" lookup main" in text
    assert "EXIT_MTU" in text
    assert "_cleanup_stale" in text
    assert "_fw4_del_by_comment" in text


def test_openwrt_setup_installs_procd_routing():
    from orchestrator.cloudinit import CloudInitParams, render_openwrt_setup

    params = CloudInitParams(
        gateway_name="gw-000",
        vm_ip="10.10.2.26",
        wg_subnet="10.64.34.0/24",
        wg_gateway_ip="10.64.34.1",
        wg_listen_port=52017,
        wg_private_key="x" * 44,
        wg_mtu=1420,
        exit_mtu=1420,
        agent_token="token",
        agent_port=8081,
        headscale_url="https://deeporc.harlock.network",
        tailscale_auth_key="tskey-test",
        orch_allowed_ip="10.10.0.1",
        net_interface="eth0",
    )
    script = render_openwrt_setup(params)
    assert "/opt/gateway-agent/deeporc-routing.sh" in script
    assert "/etc/init.d/deeporc-routing" in script
    assert "USE_PROCD=1" in script
    assert "/etc/hotplug.d/iface/99-deeporc-routing" in script
    assert "/etc/init.d/deeporc-routing enable" in script
    assert "EXIT_MTU=1420" in script
    assert "ip link set wg0 mtu 1420" in script
    assert 'comment "deeporc-wg"' not in script
