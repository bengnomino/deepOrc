"""Generate exit-host bash setup for a peer group (macvlan + WireGuard per gateway)."""

from __future__ import annotations

import re

from orchestrator.lan.ipam import default_lan_gateway
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.peer_group import PeerGroup

_IFACE_SAFE = re.compile(r"[^a-zA-Z0-9]")


def wg_interface_name(gateway_name: str) -> str:
    """Linux iface name ≤15 chars."""
    base = "wg-" + _IFACE_SAFE.sub("", gateway_name)
    return base[:15]


def render_exit_host_script(
    group: PeerGroup,
    entries: list[tuple[Gateway, str | None]],
) -> str:
    parent = group.parent_iface or "ens18"
    lan_gw = group.lan_gateway or default_lan_gateway(group.lan_subnet)

    lines = [
        "#!/usr/bin/env bash",
        "# deepOrc exit host — peer group: " + group.name,
        "# Run as root on the EXIT VM (no sudo). Adjust PARENT_IFACE if needed.",
        "set -euo pipefail",
        "",
        f'PARENT_IFACE="${{PARENT_IFACE:-{parent}}}"',
        f'LAN_GW="${{LAN_GW:-{lan_gw}}}"',
        f'WG_CONF_DIR="${{WG_CONF_DIR:-/etc/wireguard}}"',
        "",
        "sysctl -w net.ipv4.ip_forward=1",
        "sysctl -w net.ipv4.conf.all.rp_filter=0",
        "sysctl -w net.ipv4.conf.default.rp_filter=0",
        "sysctl -w net.ipv4.conf.${PARENT_IFACE}.rp_filter=0",
        "sysctl -w net.ipv4.conf.all.arp_ignore=1",
        "sysctl -w net.ipv4.conf.all.arp_announce=2",
        "",
        'grep -q "^200 deeporc" /etc/iproute2/rt_tables 2>/dev/null || echo "200 deeporc" >> /etc/iproute2/rt_tables',
        "",
    ]

    if not entries:
        lines += [
            "echo 'No gateways in this group yet — create gateways in the UI first.' >&2",
            "exit 1",
        ]
        return "\n".join(lines) + "\n"

    for gateway, wg_conf in entries:
        if not gateway.lan_ip or gateway.macvlan_slot is None:
            continue
        slot = gateway.macvlan_slot
        mac = f"mac_{slot}"
        wg_if = wg_interface_name(gateway.name)
        table = slot
        lan_ip = gateway.lan_ip

        lines += [
            f"echo '==> {gateway.name} ({lan_ip} / {mac})'",
            f"ip link del {mac} 2>/dev/null || true",
            f"ip link add {mac} link \"${{PARENT_IFACE}}\" type macvlan mode bridge",
            f"ip addr add {lan_ip}/24 dev {mac}",
            f"ip link set {mac} up",
            "",
            f"grep -q '^{table} ' /etc/iproute2/rt_tables 2>/dev/null || echo '{table} deeporc-{slot}' >> /etc/iproute2/rt_tables",
            f"ip route replace default via \"${{LAN_GW}}\" dev {mac} table {table}",
            f"ip rule del iif {wg_if} lookup {table} 2>/dev/null || true",
            "",
        ]

        if gateway.status != GatewayStatus.READY or not wg_conf:
            lines += [
                f"echo '  skip WireGuard: {gateway.name} not ready or missing backhaul peer' >&2",
                "",
            ]
            continue

        conf_path = f"${{WG_CONF_DIR}}/{wg_if}.conf"
        lines += [
            f"mkdir -p \"${{WG_CONF_DIR}}\"",
            f"cat > {conf_path} <<'DEEPORC_WG_EOF'",
            wg_conf.rstrip(),
            "DEEPORC_WG_EOF",
            f"wg-quick down {wg_if} 2>/dev/null || true",
            f"wg-quick up {wg_if}",
            f"ip rule add iif {wg_if} lookup {table}",
            f"iptables -C FORWARD -i {wg_if} -o {mac} -j ACCEPT 2>/dev/null || "
            f"iptables -A FORWARD -i {wg_if} -o {mac} -j ACCEPT",
            f"iptables -C FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || "
            f"iptables -A FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT",
            f"iptables -t nat -C POSTROUTING -o {mac} -j MASQUERADE 2>/dev/null || "
            f"iptables -t nat -A POSTROUTING -o {mac} -j MASQUERADE",
            "",
        ]

    lines += ["echo 'Done.'"]
    return "\n".join(lines) + "\n"


def render_exit_host_teardown_script(
    group: PeerGroup,
    gateways: list[Gateway],
) -> str:
    parent = group.parent_iface or "ens18"
    lines = [
        "#!/usr/bin/env bash",
        "# Tear down deepOrc exit host — peer group: " + group.name,
        "set -euo pipefail",
        "",
    ]
    for gateway in gateways:
        if gateway.macvlan_slot is None:
            continue
        mac = f"mac_{gateway.macvlan_slot}"
        wg_if = wg_interface_name(gateway.name)
        table = gateway.macvlan_slot
        lines += [
            f"wg-quick down {wg_if} 2>/dev/null || true",
            f"rm -f /etc/wireguard/{wg_if}.conf 2>/dev/null || true",
            f"iptables -t nat -D POSTROUTING -o {mac} -j MASQUERADE 2>/dev/null || true",
            f"iptables -D FORWARD -i {wg_if} -o {mac} -j ACCEPT 2>/dev/null || true",
            f"iptables -D FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true",
            f"ip rule del iif {wg_if} lookup {table} 2>/dev/null || true",
            f"ip route flush table {table} 2>/dev/null || true",
            f"ip link del {mac} 2>/dev/null || true",
        ]
    lines.append("echo 'Teardown done.'")
    return "\n".join(lines) + "\n"
