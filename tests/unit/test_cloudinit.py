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
    assert 'ip saddr 100.64.0.0/10 oifname "wg0" masquerade' in data
    assert "deeporc_exit" in data
    assert "/opt/gateway-agent/exit-via-wg.sh" in data
    assert "tailscale up --advertise-exit-node --netfilter-mode=on --reset" not in data
    assert 'policy drop' not in data
    assert 'ip saddr 100.64.0.0/10 oifname "enp5s0" masquerade' not in data
    assert 'ip saddr 10.64.1.0/24 oifname "enp5s0" masquerade' not in data
    assert "ip link set wg0 mtu 1380" in data


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
    assert 'ip saddr 100.64.0.0/10 oifname "wg0" masquerade' in data
    assert "deeporc_exit" in data
    assert "/opt/gateway-agent/exit-via-wg.sh" in data
    assert "tailscale up --advertise-exit-node --netfilter-mode=on --reset" not in data
    assert 'oifname "eth0" masquerade' not in data
    assert "privkey" in data
