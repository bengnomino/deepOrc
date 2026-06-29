"""Unit tests for cloud-init renderer."""

from orchestrator.cloudinit import CloudInitParams, render_user_data


def test_render_user_data():
    params = CloudInitParams(
        gateway_name="gw-test",
        wg_private_key="privkey",
        wg_gateway_ip="10.64.1.1",
        wg_subnet="10.64.1.0/24",
        wg_listen_port=51820,
        headscale_url="https://headscale.example.com",
        tailscale_auth_key="tskey-test",
        agent_token="agent-token",
        orch_allowed_ip="10.10.0.1",
        vm_ip="10.10.1.10",
        agent_port=8081,
    )
    data = render_user_data(params)
    assert "gw-test" in data
    assert "privkey" in data
    assert "pref 35 to 10.64.1.0/24 lookup main" in data
    assert "pref 40 from 10.64.1.1/32 lookup main" in data
    assert "pref 50 from 10.10.1.10/32 lookup main" in data
    assert '--advertise-exit-node' in data
    assert 'iifname "wg0" oifname "enp5s0" accept' in data
    assert "meta mark set 0x400" not in data
    assert "oifname \"enp5s0\" masquerade" in data
    assert "ip link set wg0 mtu 1280" in data


def test_render_user_data_golden():
    params = CloudInitParams(
        gateway_name="gw-test",
        wg_private_key="privkey",
        wg_gateway_ip="10.64.1.1",
        wg_subnet="10.64.1.0/24",
        wg_listen_port=51820,
        headscale_url="https://headscale.example.com",
        tailscale_auth_key="tskey-test",
        agent_token="agent-token",
        orch_allowed_ip="10.10.0.1",
        vm_ip="10.10.1.10",
        agent_port=8081,
        use_golden_image=True,
        net_interface="eth0",
    )
    data = render_user_data(params)
    assert "pip install" not in data
    assert "tailscale.com/install.sh" not in data
    assert "rc-service wg-quick.wg0 restart" in data
    assert 'oifname "eth0"' in data
    assert "privkey" in data
