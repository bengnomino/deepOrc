"""Tailscale exit-node routing without breaking WireGuard handshakes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

EXIT_NODE_ENV = Path("/opt/gateway-agent/exit-node.env")
WG_GATEWAY_REPLY_RULE_PREF = "40"
WG_PEER_RETURN_RULE_PREF = "35"
WG_UDP_REPLY_RULE_PREF = "50"
STALE_PEER_RULE_PREF = "100"
STALE_PEER_TABLE = "100"
TAILSCALE_SNAT_MARK = "0x400"


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or " ".join(cmd))


def _run_optional(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, text=True, check=False)


def _vm_lan_ip() -> str:
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "scope", "global"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        match = re.search(r"\sinet\s(\S+)", line)
        if match and match.group(1).startswith("10.10."):
            return match.group(1).split("/")[0]

    result = subprocess.run(
        ["ip", "-4", "route", "get", "1.1.1.1"],
        capture_output=True,
        text=True,
        check=True,
    )
    parts = result.stdout.split()
    for index, part in enumerate(parts):
        if part == "src" and index + 1 < len(parts):
            return parts[index + 1]
    raise RuntimeError("could not detect VM LAN IP")


def _wg_subnet(interface: str = "wg0") -> str:
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", interface],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        match = re.search(r"\sinet\s(\S+)", line)
        if match:
            ip, prefix = match.group(1).split("/")
            octets = ip.split(".")
            return f"{octets[0]}.{octets[1]}.{octets[2]}.0/{prefix}"
    return "10.64.2.0/24"


def _wg_gateway_ip(interface: str = "wg0") -> str:
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", interface],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        match = re.search(r"\sinet\s(\S+)", line)
        if match:
            return match.group(1).split("/")[0]
    raise RuntimeError(f"could not detect gateway IP on {interface}")


def _ensure_ip_rule(pref: str, match: list[str]) -> None:
    _run_optional(["ip", "rule", "del", "pref", pref, *match])
    _run(["ip", "rule", "add", "pref", pref, *match])


def _ensure_wg_reply_rules(vm_ip: str, wg_gateway_ip: str, wg_subnet: str) -> None:
    _ensure_ip_rule(WG_PEER_RETURN_RULE_PREF, ["to", wg_subnet, "lookup", "main"])
    _ensure_ip_rule(WG_GATEWAY_REPLY_RULE_PREF, ["from", f"{wg_gateway_ip}/32", "lookup", "main"])
    _ensure_ip_rule(WG_UDP_REPLY_RULE_PREF, ["from", f"{vm_ip}/32", "lookup", "main"])


def _cleanup_stale_peer_routing(wg_subnet: str) -> None:
    _run_optional(["ip", "rule", "del", "pref", STALE_PEER_RULE_PREF])
    _run_optional(
        [
            "ip",
            "rule",
            "del",
            "pref",
            STALE_PEER_RULE_PREF,
            "iif",
            "wg0",
            "from",
            wg_subnet,
            "lookup",
            STALE_PEER_TABLE,
        ]
    )
    _run_optional(["ip", "route", "flush", "table", STALE_PEER_TABLE])


def _remove_custom_tailscale_masquerade() -> None:
    result = subprocess.run(
        ["nft", "-a", "list", "chain", "ip", "nat", "postrouting"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        if 'oifname "tailscale0"' in line and "masquerade" in line:
            handle = line.strip().split()[-1]
            if handle.isdigit():
                _run_optional(["nft", "delete", "rule", "ip", "nat", "postrouting", "handle", handle])


def _ensure_wg_tailscale_forward_mark() -> None:
    _run_optional(["nft", "add", "table", "ip", "mangle"])
    _run_optional(
        [
            "nft",
            "add",
            "chain",
            "ip",
            "mangle",
            "forward",
            "{",
            "type",
            "filter",
            "hook",
            "forward",
            "priority",
            "mangle",
            ";",
            "policy",
            "accept",
            ";",
            "}",
        ]
    )
    result = subprocess.run(
        ["nft", "-a", "list", "chain", "ip", "mangle", "forward"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "wg0" in line and "tailscale0" in line and TAILSCALE_SNAT_MARK in line:
                return
    _run(
        [
            "nft",
            "add",
            "rule",
            "ip",
            "mangle",
            "forward",
            "iifname",
            "wg0",
            "oifname",
            "tailscale0",
            "meta",
            "mark",
            "set",
            TAILSCALE_SNAT_MARK,
        ]
    )


def _ensure_return_forward_rules() -> None:
    result = subprocess.run(
        ["nft", "-a", "list", "chain", "inet", "filter", "forward"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    has_open_return = any(
        "tailscale0" in line and "wg0" in line and "accept" in line and "established" not in line
        for line in result.stdout.splitlines()
    )
    if not has_open_return:
        _run_optional(
            [
                "nft",
                "add",
                "rule",
                "inet",
                "filter",
                "forward",
                "iifname",
                "tailscale0",
                "oifname",
                "wg0",
                "accept",
            ]
        )


def _set_vps_egress_fallback(wg_subnet: str, *, enable: bool) -> None:
    prefix = wg_subnet.split("/")[0].rsplit(".", 1)[0]
    result = subprocess.run(
        ["nft", "-a", "list", "chain", "ip", "nat", "postrouting"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    handle = None
    for line in result.stdout.splitlines():
        if "enp5s0" in line and prefix in line:
            handle = line.strip().split()[-1]
    if enable:
        if handle is None:
            _run_optional(
                [
                    "nft",
                    "add",
                    "rule",
                    "ip",
                    "nat",
                    "postrouting",
                    "ip",
                    "saddr",
                    wg_subnet,
                    "oifname",
                    "enp5s0",
                    "masquerade",
                ]
            )
        return
    if handle is not None and handle.isdigit():
        _run_optional(["nft", "delete", "rule", "ip", "nat", "postrouting", "handle", handle])


def _clear_advertised_wg_routes() -> None:
    """WireGuard subnets must not be advertised on Tailscale/Headscale."""
    _run_optional(["tailscale", "set", "--advertise-routes="])


def _persist_exit_node_id(exit_node_id: str) -> None:
    EXIT_NODE_ENV.parent.mkdir(parents=True, exist_ok=True)
    EXIT_NODE_ENV.write_text(f"EXIT_NODE_ID={exit_node_id}\n", encoding="utf-8")


def clear_exit_node() -> None:
    result = subprocess.run(
        ["tailscale", "set", "--exit-node=", "--netfilter-mode=off"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale clear exit-node failed")
    if EXIT_NODE_ENV.is_file():
        EXIT_NODE_ENV.unlink()


def advertise_exit_node() -> None:
    """Advertise this gateway as a Tailscale exit node (deepOrc model)."""
    vm_ip = _vm_lan_ip()
    wg_gateway_ip = _wg_gateway_ip()
    wg_subnet = _wg_subnet()

    _ensure_wg_reply_rules(vm_ip, wg_gateway_ip, wg_subnet)
    _cleanup_stale_peer_routing(wg_subnet)

    result = subprocess.run(
        [
            "tailscale",
            "set",
            "--advertise-exit-node",
            "--netfilter-mode=off",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale advertise-exit-node failed")

    _clear_advertised_wg_routes()


def restore_exit_node_routing() -> None:
    """On agent startup, ensure exit node is advertised (idempotent)."""
    try:
        advertise_exit_node()
    except RuntimeError:
        pass


def set_exit_node(exit_node_id: str) -> None:
    vm_ip = _vm_lan_ip()
    wg_gateway_ip = _wg_gateway_ip()
    wg_subnet = _wg_subnet()

    _ensure_wg_reply_rules(vm_ip, wg_gateway_ip, wg_subnet)
    _cleanup_stale_peer_routing(wg_subnet)
    _remove_custom_tailscale_masquerade()
    _ensure_wg_tailscale_forward_mark()
    _ensure_return_forward_rules()

    result = subprocess.run(
        [
            "tailscale",
            "set",
            f"--exit-node={exit_node_id}",
            "--exit-node-allow-lan-access=false",
            "--netfilter-mode=on",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale set failed")

    _set_vps_egress_fallback(wg_subnet, enable=False)
    _remove_custom_tailscale_masquerade()
    _clear_advertised_wg_routes()
    _persist_exit_node_id(exit_node_id)
