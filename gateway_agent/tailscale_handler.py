"""Tailscale exit-node routing without breaking WireGuard handshakes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

EXIT_NODE_ENV = Path("/opt/gateway-agent/exit-node.env")
WG_GATEWAY_REPLY_RULE_PREF = "40"
WG_PEER_RETURN_RULE_PREF = "35"
WG_UDP_REPLY_RULE_PREF = "50"
GATEWAY_TS_RULE_PREF = "45"
EXIT_CLIENT_RULE_PREF = "58"
BACKHAUL_ROUTE_TABLE = "200"
BACKHAUL_ROUTE_TABLE_NAME = "backhaul"
STALE_PEER_RULE_PREF = "100"
STALE_PEER_TABLE = "100"
TAILSCALE_SNAT_SUBNET = "100.64.0.0/10"
UPLINK_INTERFACE = "wg0"


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


def _wg_subnet(interface: str = UPLINK_INTERFACE) -> str:
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


def _wg_gateway_ip(interface: str = UPLINK_INTERFACE) -> str:
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
            UPLINK_INTERFACE,
            "from",
            wg_subnet,
            "lookup",
            STALE_PEER_TABLE,
        ]
    )
    _run_optional(["ip", "route", "flush", "table", STALE_PEER_TABLE])


def _clear_advertised_wg_routes() -> None:
    """WireGuard subnets must not be advertised on Tailscale/Headscale."""
    _run_optional(["tailscale", "set", "--advertise-routes="])


def _persist_exit_node_id(exit_node_id: str) -> None:
    EXIT_NODE_ENV.parent.mkdir(parents=True, exist_ok=True)
    EXIT_NODE_ENV.write_text(f"EXIT_NODE_ID={exit_node_id}\n", encoding="utf-8")


def _detect_wan_interface() -> str:
    from gateway_agent.config import get_agent_settings

    settings = get_agent_settings()
    if settings.net_interface:
        return settings.net_interface
    result = subprocess.run(
        ["ip", "-4", "route", "show", "default"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        for index, part in enumerate(parts):
            if part == "dev" and index + 1 < len(parts):
                return parts[index + 1]
    return "eth0"


def _nft_rule_exists(table: str, chain: str, needle: str) -> bool:
    result = subprocess.run(
        ["nft", "-a", "list", "chain", *table.split(), chain],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and needle in result.stdout


def _nft_delete_matching(table: str, chain: str, predicate) -> None:
    result = subprocess.run(
        ["nft", "-a", "list", "chain", *table.split(), chain],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        if predicate(line):
            handle = line.strip().split()[-1]
            if handle.isdigit():
                _run_optional(["nft", "delete", "rule", *table.split(), chain, "handle", handle])


def _tailscale_gateway_ip() -> str | None:
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", "tailscale0"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        match = re.search(r"\sinet\s(\S+)", line)
        if match:
            return match.group(1).split("/")[0]
    return None


def _cleanup_stale_exit_hacks() -> None:
    """Remove experimental fwmark/mangle rules from earlier iterations."""
    for pref in ("54", "55", "60"):
        _run_optional(["ip", "rule", "del", "pref", pref])
    for table in ("ip gw_mangle", "ip gw_preroute"):
        _run_optional(["nft", "delete", "table", *table.split()])


def _ensure_backhaul_policy_routing(
    vm_ip: str,
    wg_gateway_ip: str,
    wg_subnet: str,
    tailscale_ip: str | None = None,
) -> None:
    """Route traffic arriving on tailscale0 via wg0 (WireGuard uplink)."""
    ts_ip = tailscale_ip or _tailscale_gateway_ip()
    _ensure_ip_rule(WG_PEER_RETURN_RULE_PREF, ["to", wg_subnet, "lookup", "main"])
    _ensure_ip_rule(WG_GATEWAY_REPLY_RULE_PREF, ["from", f"{wg_gateway_ip}/32", "lookup", "main"])
    _ensure_ip_rule(WG_UDP_REPLY_RULE_PREF, ["from", f"{vm_ip}/32", "lookup", "main"])
    if ts_ip:
        _ensure_ip_rule(GATEWAY_TS_RULE_PREF, ["from", f"{ts_ip}/32", "lookup", "main"])

    _cleanup_stale_exit_hacks()
    _ensure_ip_rule(EXIT_CLIENT_RULE_PREF, ["iif", "tailscale0", "lookup", BACKHAUL_ROUTE_TABLE])

    if subprocess.run(
        ["grep", "-q", BACKHAUL_ROUTE_TABLE_NAME, "/etc/iproute2/rt_tables"],
        capture_output=True,
        check=False,
    ).returncode != 0:
        with open("/etc/iproute2/rt_tables", "a", encoding="utf-8") as fh:
            fh.write(f"{BACKHAUL_ROUTE_TABLE} {BACKHAUL_ROUTE_TABLE_NAME}\n")
    _run(["ip", "route", "replace", "default", "dev", UPLINK_INTERFACE, "table", BACKHAUL_ROUTE_TABLE])


def _strip_tailscale_postrouting_masquerade() -> None:
    """Tailscale SNAT on eth0 breaks exit-via-wg; we masquerade on wg0 instead."""
    _nft_delete_matching(
        "ip nat",
        "ts-postrouting",
        lambda line: "masquerade" in line,
    )


def _ensure_exit_via_wg_backhaul() -> None:
    """SNAT exit on wg0 + forward tailscale0 <-> wg0 (same as exit-via-wg.sh)."""
    _strip_tailscale_postrouting_masquerade()
    _run_optional(["nft", "delete", "table", "ip", "gw_nat"])
    _run_optional(["nft", "delete", "table", "ip", "deeporc_exit"])
    gateway_nft = Path("/etc/nftables.d/gateway.nft")
    if gateway_nft.is_file():
        _run(["nft", "-f", str(gateway_nft)])
        return
    _run_optional(["nft", "add", "table", "ip", "gw_nat"])
    _run_optional(
        [
            "nft",
            "add",
            "chain",
            "ip",
            "gw_nat",
            "postrouting",
            "{",
            "type",
            "nat",
            "hook",
            "postrouting",
            "priority",
            "srcnat",
            ";",
            "policy",
            "accept",
            ";",
            "}",
        ]
    )
    _run_optional(
        [
            "nft",
            "add",
            "rule",
            "ip",
            "gw_nat",
            "postrouting",
            "ip",
            "saddr",
            TAILSCALE_SNAT_SUBNET,
            "oifname",
            UPLINK_INTERFACE,
            "masquerade",
        ]
    )
    _run_optional(["nft", "add", "table", "ip", "deeporc_exit"])
    _run_optional(
        [
            "nft",
            "add",
            "chain",
            "ip",
            "deeporc_exit",
            "forward",
            "{",
            "type",
            "filter",
            "hook",
            "forward",
            "priority",
            "filter",
            ";",
            "policy",
            "accept",
            ";",
            "}",
        ]
    )
    if not _nft_rule_exists("ip deeporc_exit", "forward", "tailscale0"):
        _run_optional(
            [
                "nft",
                "add",
                "rule",
                "ip",
                "deeporc_exit",
                "forward",
                "iifname",
                "tailscale0",
                "oifname",
                UPLINK_INTERFACE,
                "accept",
            ]
        )
        _run_optional(
            [
                "nft",
                "add",
                "rule",
                "ip",
                "deeporc_exit",
                "forward",
                "iifname",
                UPLINK_INTERFACE,
                "oifname",
                "tailscale0",
                "accept",
            ]
        )


def remove_exit_node_egress(wan_interface: str | None = None) -> None:
    """Firewall disabled — no-op."""


def ensure_exit_node_forwarding(wan_interface: str | None = None) -> None:
    """Route + SNAT Tailscale exit via WireGuard uplink."""
    _ = wan_interface
    vm_ip = _vm_lan_ip()
    wg_gateway_ip = _wg_gateway_ip()
    wg_subnet = _wg_subnet()
    ts_ip = _tailscale_gateway_ip()

    _ensure_backhaul_policy_routing(vm_ip, wg_gateway_ip, wg_subnet, ts_ip)
    _ensure_exit_via_wg_backhaul()


def advertise_exit_node() -> None:
    """Advertise this gateway as a Tailscale exit node (deepOrc model)."""
    wg_subnet = _wg_subnet()
    _cleanup_stale_peer_routing(wg_subnet)

    result = subprocess.run(
        ["tailscale", "set", "--advertise-exit-node", "--accept-dns", "--advertise-routes="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale advertise-exit-node failed")

    _clear_advertised_wg_routes()
    ensure_exit_node_forwarding()
    _strip_tailscale_postrouting_masquerade()


def set_tailscale_hostname(hostname: str) -> None:
    result = subprocess.run(
        ["tailscale", "set", "--hostname", hostname],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale set hostname failed")


def restore_exit_node_routing() -> None:
    """On agent startup, restore exit routing if advertised."""
    _cleanup_stale_exit_hacks()
    try:
        result = subprocess.run(
            ["tailscale", "debug", "prefs"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            import json

            try:
                prefs = json.loads(result.stdout)
                exit_advertised = bool(prefs.get("AdvertiseExitNode")) or "0.0.0.0/0" in (
                    prefs.get("AdvertiseRoutes") or []
                )
            except json.JSONDecodeError:
                exit_advertised = '"AdvertiseExitNode": true' in result.stdout
            if exit_advertised:
                ensure_exit_node_forwarding()
            else:
                remove_exit_node_egress()
        else:
            remove_exit_node_egress()
    except RuntimeError:
        remove_exit_node_egress()


def set_exit_node(exit_node_id: str) -> None:
    """Gateway consumes another Tailscale exit (not the deepOrc advertise path)."""
    vm_ip = _vm_lan_ip()
    wg_gateway_ip = _wg_gateway_ip()
    wg_subnet = _wg_subnet()

    _ensure_wg_reply_rules(vm_ip, wg_gateway_ip, wg_subnet)
    _cleanup_stale_peer_routing(wg_subnet)

    result = subprocess.run(
        [
            "tailscale",
            "set",
            f"--exit-node={exit_node_id}",
            "--exit-node-allow-lan-access=false",
            "--netfilter-mode=off",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale set failed")

    _clear_advertised_wg_routes()
    _persist_exit_node_id(exit_node_id)


def clear_exit_node() -> None:
    result = subprocess.run(
        ["tailscale", "set", "--exit-node=", "--netfilter-mode=off"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tailscale clear exit-node failed")
    remove_exit_node_egress()
    if EXIT_NODE_ENV.is_file():
        EXIT_NODE_ENV.unlink()
