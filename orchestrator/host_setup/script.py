"""Generate exit-host bash setup for a peer group (macvlan + WireGuard per gateway)."""

from __future__ import annotations

import base64
import ipaddress
import re
from pathlib import Path

from orchestrator.lan.ipam import default_lan_gateway
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.peer_group import PeerGroup
from orchestrator.wg.config import BACKHAUL_WG_MTU

_IFACE_SAFE = re.compile(r"[^a-zA-Z0-9]")
_CLEANUP_SCRIPT = Path(__file__).resolve().parent / "exit_host_cleanup.sh"


def render_exit_host_auto_cleanup_script() -> str:
    """Bash script that discovers and removes all deepOrc exit-host plumbing."""
    return _CLEANUP_SCRIPT.read_text(encoding="utf-8")


def wg_interface_name(gateway_name: str) -> str:
    """Linux iface name ≤15 chars."""
    base = "wg-" + _IFACE_SAFE.sub("", gateway_name)
    return base[:15]


def _lan_prefix_len(group: PeerGroup) -> int:
    return ipaddress.ip_network(group.lan_subnet, strict=False).prefixlen


def _valid_wg_conf(conf: str | None) -> bool:
    if not conf or not conf.strip():
        return False
    return "[Interface]" in conf and "[Peer]" in conf and "PrivateKey" in conf


def _write_wg_conf_lines(conf_path: str, wg_if: str, wg_conf: str) -> list[str]:
    """Embed WireGuard config via base64 (safe for copy-paste; no heredoc delimiter issues)."""
    var = f"DEEPORC_B64_{wg_if.replace('-', '_').upper()}"
    encoded = base64.b64encode(wg_conf.strip().encode()).decode("ascii")
    return [
        f"mkdir -p \"${{WG_CONF_DIR}}\"",
        f'{var}="{encoded}"',
        f'printf "%s" "${{{var}}}" | base64 -d > "{conf_path}"',
        f"chmod 600 \"{conf_path}\"",
    ]


def render_exit_host_script(
    group: PeerGroup,
    entries: list[tuple[Gateway, str | None]],
) -> str:
    parent = group.parent_iface or "ens18"
    lan_gw = group.lan_gateway or default_lan_gateway(group.lan_subnet)
    prefix_len = _lan_prefix_len(group)
    ready_count = sum(
        1 for gw, conf in entries if gw.status == GatewayStatus.READY and _valid_wg_conf(conf)
    )

    lines = [
        "#!/usr/bin/env bash",
        f"# deepOrc exit host — peer group: {group.name}",
        f"# Gateways in group: {len(entries)} ({ready_count} with WireGuard config)",
        "# Run as root on the EXIT VM (no sudo). Prefer downloading this file — do not copy from the browser modal for large groups.",
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
        "mkdir -p /etc/iproute2",
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
        conf_path = f"${{WG_CONF_DIR}}/{wg_if}.conf"

        block = [
            f"echo '==> {gateway.name} ({lan_ip} / {mac})'",
            f"ip link del {mac} 2>/dev/null || true",
            f"ip link add {mac} link \"${{PARENT_IFACE}}\" type macvlan mode bridge",
            f"ip addr add {lan_ip}/{prefix_len} dev {mac}",
            f"ip link set {mac} up",
            f"grep -q '^{table} ' /etc/iproute2/rt_tables 2>/dev/null || echo '{table} deeporc-{slot}' >> /etc/iproute2/rt_tables",
            f"ip route replace default via \"${{LAN_GW}}\" dev {mac} table {table}",
            f"ip route replace {lan_ip}/{prefix_len} dev {mac} scope link table {table}",
            f"ip rule del from {lan_ip}/32 lookup {table} 2>/dev/null || true",
            f"ip rule add pref {32000 + slot} from {lan_ip}/32 lookup {table}",
            f"ip rule del iif {wg_if} lookup {table} 2>/dev/null || true",
        ]

        if gateway.status != GatewayStatus.READY:
            block.append(
                f"echo '  skip WireGuard: {gateway.name} status={gateway.status.value} (wait for ready in UI)' >&2"
            )
        elif not _valid_wg_conf(wg_conf):
            block.append(
                f"echo '  skip WireGuard: {gateway.name} missing or incomplete backhaul peer config' >&2"
            )
        else:
            block += _write_wg_conf_lines(conf_path, wg_if, wg_conf or "")
            block += [
                f"wg-quick down {wg_if} 2>/dev/null || true",
                f"wg-quick up {wg_if}",
                f"ip link set {wg_if} mtu {BACKHAUL_WG_MTU}",
                f"ip rule add pref {32500 + slot} iif {wg_if} lookup {table}",
                f"iptables -C FORWARD -i {wg_if} -o {mac} -j ACCEPT 2>/dev/null || "
                f"iptables -A FORWARD -i {wg_if} -o {mac} -j ACCEPT",
                f"iptables -C FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || "
                f"iptables -A FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT",
                f"iptables -t nat -C POSTROUTING -o {mac} -j MASQUERADE 2>/dev/null || "
                f"iptables -t nat -A POSTROUTING -o {mac} -j MASQUERADE",
            ]

        lines.append(f"({'; '.join(block)}) || echo 'FAILED: {gateway.name}' >&2")
        lines.append("")

    lines += ["echo 'Done.'"]
    return "\n".join(lines) + "\n"


def render_exit_host_teardown_script(
    group: PeerGroup,
    gateways: list[Gateway],
) -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"# Tear down deepOrc exit host — peer group: {group.name}",
        "set -euo pipefail",
        "",
    ]
    for gateway in gateways:
        if gateway.macvlan_slot is None:
            continue
        mac = f"mac_{gateway.macvlan_slot}"
        wg_if = wg_interface_name(gateway.name)
        table = gateway.macvlan_slot
        lan_ip = gateway.lan_ip or ""
        lines += [
            f"wg-quick down {wg_if} 2>/dev/null || true",
            f"rm -f /etc/wireguard/{wg_if}.conf 2>/dev/null || true",
            f"iptables -t nat -D POSTROUTING -o {mac} -j MASQUERADE 2>/dev/null || true",
            f"iptables -D FORWARD -i {wg_if} -o {mac} -j ACCEPT 2>/dev/null || true",
            f"iptables -D FORWARD -i {mac} -o {wg_if} -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true",
            f"ip rule del from {lan_ip}/32 lookup {table} 2>/dev/null || true",
            f"ip rule del iif {wg_if} lookup {table} 2>/dev/null || true",
            f"ip route flush table {table} 2>/dev/null || true",
            f"ip link del {mac} 2>/dev/null || true",
        ]
    lines.append("echo 'Teardown done.'")
    return "\n".join(lines) + "\n"
