"""Headscale CLI integration for automatic gateway preauth keys."""

import json
import os
import subprocess
from dataclasses import dataclass

from orchestrator.config import get_settings
from orchestrator.naming import (
    EXIT_NODE_PREFIX,
    collect_exit_node_names,
    headscale_node_name,
    is_exit_node_name,
    is_gateway_name,
    next_sequential_name,
)

EXIT_NODE_ROUTES = frozenset({"0.0.0.0/0", "::/0"})
PEER_ONLINE_HANDSHAKE_SECONDS = 180
REGISTRATION_KEY_LENGTH = 24
REGISTRATION_KEY_MAX_LENGTH = 128
HEADSCALE_AUTH_ID_PREFIX = "hskey-authreq-"


def normalize_registration_key(key: str) -> str:
    return key.strip()


def is_valid_registration_key(key: str) -> bool:
    """Accept legacy 24-char keys and Headscale 0.29+ hskey-authreq-* IDs."""
    normalized = normalize_registration_key(key)
    if not normalized or len(normalized) > REGISTRATION_KEY_MAX_LENGTH:
        return False
    if len(normalized) == REGISTRATION_KEY_LENGTH:
        return True
    return normalized.startswith(HEADSCALE_AUTH_ID_PREFIX) and len(normalized) > len(
        HEADSCALE_AUTH_ID_PREFIX
    )


@dataclass(frozen=True)
class PreAuthKey:
    key: str
    user_id: int


@dataclass(frozen=True)
class HeadscaleNode:
    node_id: int
    hostname: str
    tailscale_ip: str
    online: bool
    exit_approved: bool
    exit_tagged: bool = False
    exit_advertised: bool = False


@dataclass(frozen=True)
class RegisteredNode:
    node_id: int
    hostname: str
    tailscale_ip: str


class HeadscaleError(RuntimeError):
    pass


# Headscale's own CLI reads HEADSCALE_* from the environment; do not leak our settings.
_HEADSCALE_ENV_BLOCKLIST = frozenset({"HEADSCALE_CLI", "HEADSCALE_USER", "HEADSCALE_URL"})


def _headscale_subprocess_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in _HEADSCALE_ENV_BLOCKLIST
    }


def _run_headscale(args: list[str]) -> str:
    settings = get_settings()
    cmd = [settings.headscale_cli]
    if settings.headscale_config:
        cmd.extend(["-c", settings.headscale_config])
    cmd.extend(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=_headscale_subprocess_env(),
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
                if isinstance(payload, dict) and payload.get("error"):
                    detail = str(payload["error"])
            except json.JSONDecodeError:
                pass
        raise HeadscaleError(detail or "headscale command failed")
    return result.stdout.strip()


def _parse_nodes_json(raw: str) -> list[dict]:
    if not raw or raw == "null":
        return []
    data = json.loads(raw)
    if data is None:
        return []
    if isinstance(data, list):
        return [n for n in data if isinstance(n, dict)]
    if isinstance(data, dict):
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            return [n for n in nodes if isinstance(n, dict)]
    return []


def _route_list(node: dict, *keys: str) -> list[str]:
    for key in keys:
        value = node.get(key)
        if isinstance(value, list):
            return [str(r) for r in value]
    return []


def _has_exit_route(routes: list[str]) -> bool:
    return any(route in EXIT_NODE_ROUTES for route in routes)


def _node_ipv4(node: dict) -> str | None:
    for key in ("ipAddresses", "ip_addresses"):
        addrs = node.get(key)
        if isinstance(addrs, list):
            for addr in addrs:
                ip = str(addr).split("/")[0]
                if ":" not in ip:
                    return ip
    return None


def _node_online(node: dict) -> bool:
    for key in ("connected", "online"):
        if key in node:
            return bool(node[key])
    return False


def _node_tags(node: dict) -> list[str]:
    for key in ("tags", "Tags", "validTags", "valid_tags"):
        value = node.get(key)
        if isinstance(value, list):
            return [str(tag) for tag in value]
    return []


def _node_has_exit_tag(node: dict, tag: str | None = None) -> bool:
    settings = get_settings()
    exit_tag = tag or settings.headscale_exit_node_tag
    return exit_tag in _node_tags(node)


def list_headscale_nodes_raw() -> list[dict]:
    output = _run_headscale(["nodes", "list", "-o", "json"])
    return _parse_nodes_json(output)


def _parse_headscale_node(node: dict, exit_tag: str | None = None) -> HeadscaleNode | None:
    ipv4 = _node_ipv4(node)
    if not ipv4:
        return None
    settings = get_settings()
    tag = exit_tag or settings.headscale_exit_node_tag
    approved = _route_list(node, "approvedRoutes", "approved_routes")
    available = _route_list(node, "availableRoutes", "available_routes")
    exit_tagged = _node_has_exit_tag(node, tag)
    exit_advertised = _has_exit_route(approved) or _has_exit_route(available)
    if not (exit_tagged or exit_advertised):
        return None
    node_id = node.get("id")
    hostname = headscale_node_name(node) or ipv4
    return HeadscaleNode(
        node_id=int(node_id) if node_id is not None else 0,
        hostname=str(hostname),
        tailscale_ip=ipv4,
        online=_node_online(node),
        exit_approved=_has_exit_route(approved),
        exit_tagged=exit_tagged,
        exit_advertised=exit_advertised,
    )


def get_node_tailscale_ip_by_hostname(hostname: str) -> str | None:
    """Resolve a Headscale node's Tailscale IPv4 by hostname."""
    for node in list_headscale_nodes_raw():
        if headscale_node_name(node) == hostname:
            return _node_ipv4(node)
    return None


def list_exit_nodes() -> list[HeadscaleNode]:
    """Exit nodes from Headscale (tagged or advertising 0.0.0.0/0)."""
    nodes = list_headscale_nodes_raw()
    result: list[HeadscaleNode] = []
    seen: set[str] = set()
    for node in nodes:
        parsed = _parse_headscale_node(node)
        if parsed and parsed.tailscale_ip not in seen:
            seen.add(parsed.tailscale_ip)
            result.append(parsed)
    if result:
        return result

    routes_output = _run_headscale(["nodes", "list-routes", "-o", "json"])
    for node in _parse_nodes_json(routes_output):
        parsed = _parse_headscale_node(node)
        if parsed and parsed.tailscale_ip not in seen:
            seen.add(parsed.tailscale_ip)
            result.append(parsed)
    return result


def approve_exit_routes_for_tagged_nodes() -> int:
    """Fallback: approve exit routes for tag:exit nodes (autoApprovers should handle this)."""
    settings = get_settings()
    approved_count = 0
    for node in list_headscale_nodes_raw():
        if not _node_has_exit_tag(node, settings.headscale_exit_node_tag):
            continue
        approved = _route_list(node, "approvedRoutes", "approved_routes")
        if _has_exit_route(approved):
            continue
        available = _route_list(node, "availableRoutes", "available_routes")
        if not _has_exit_route(available):
            continue
        node_id = node.get("id")
        if node_id is None:
            continue
        _run_headscale(
            [
                "nodes",
                "approve-routes",
                "-i",
                str(node_id),
                "-r",
                "0.0.0.0/0",
            ]
        )
        approved_count += 1
    return approved_count


def rename_headscale_node(node_id: int, new_name: str) -> None:
    _run_headscale(["nodes", "rename", new_name, "-i", str(node_id)])


def assign_exit_node_name(
    node_id: int,
    reserved: set[str] | None = None,
) -> str:
    """Assign the next sequential ex-NNN name to a Headscale node."""
    taken = collect_exit_node_names(list_headscale_nodes_raw())
    if reserved:
        taken |= reserved
    name = next_sequential_name(EXIT_NODE_PREFIX, taken)
    rename_headscale_node(node_id, name)
    return name


def sync_exit_node_names(gateway_names: set[str] | None = None) -> int:
    """Rename exit node candidates that do not yet have an ex-NNN hostname."""
    settings = get_settings()
    nodes = list_headscale_nodes_raw()
    taken = collect_exit_node_names(nodes)
    if gateway_names:
        taken |= {name for name in gateway_names if name}

    renamed = 0
    for node in sorted(nodes, key=lambda item: int(item.get("id") or 0)):
        node_id = node.get("id")
        if node_id is None:
            continue
        current = headscale_node_name(node)
        if is_exit_node_name(current):
            continue
        if is_gateway_name(current) or (gateway_names and current in gateway_names):
            continue
        exit_tagged = _node_has_exit_tag(node, settings.headscale_exit_node_tag)
        approved = _route_list(node, "approvedRoutes", "approved_routes")
        available = _route_list(node, "availableRoutes", "available_routes")
        if not exit_tagged and not (
            _has_exit_route(approved) or _has_exit_route(available)
        ):
            continue
        name = next_sequential_name(EXIT_NODE_PREFIX, taken)
        rename_headscale_node(int(node_id), name)
        taken.add(name)
        renamed += 1
    return renamed


def ensure_headscale_user(name: str) -> int:
    output = _run_headscale(["users", "list", "-o", "json"])
    users = json.loads(output)
    for user in users:
        if user.get("name") == name:
            return int(user["id"])
    _run_headscale(["users", "create", name])
    return get_user_id(name)


def get_user_id(username: str | None = None) -> int:
    settings = get_settings()
    name = username or settings.headscale_user
    output = _run_headscale(["users", "list", "-o", "json"])
    users = json.loads(output)
    for user in users:
        if user.get("name") == name:
            return int(user["id"])
    raise HeadscaleError(f"Headscale user '{name}' not found")


def create_gateway_preauth_key() -> PreAuthKey:
    """Create a single-use preauth key for a gateway VM that advertises as exit node."""
    settings = get_settings()
    user_id = get_user_id()
    output = _run_headscale(
        [
            "preauthkeys",
            "create",
            "-u",
            str(user_id),
            "-e",
            settings.headscale_preauth_expiration,
            "--tags",
            settings.headscale_exit_node_tag,
            "-o",
            "json",
        ]
    )
    data = json.loads(output)
    key = data.get("key") or data.get("preAuthKey", {}).get("key")
    if not key:
        raise HeadscaleError("Headscale did not return a preauth key")
    return PreAuthKey(key=key, user_id=user_id)


def create_exit_node_preauth_key() -> PreAuthKey:
    """Reusable preauth key for Android exit nodes (tagged for auto-approval)."""
    settings = get_settings()
    user_id = get_user_id()
    output = _run_headscale(
        [
            "preauthkeys",
            "create",
            "-u",
            str(user_id),
            "--reusable",
            "-e",
            settings.headscale_preauth_expiration,
            "--tags",
            settings.headscale_exit_node_tag,
            "-o",
            "json",
        ]
    )
    data = json.loads(output)
    key = data.get("key") or data.get("preAuthKey", {}).get("key")
    if not key:
        raise HeadscaleError("Headscale did not return a preauth key")
    return PreAuthKey(key=key, user_id=user_id)


def create_worker_preauth_key() -> PreAuthKey:
    """Reusable preauth key for gateway worker VPS (tagged worker-host)."""
    settings = get_settings()
    user_id = ensure_headscale_user(settings.headscale_worker_user)
    output = _run_headscale(
        [
            "preauthkeys",
            "create",
            "-u",
            str(user_id),
            "--reusable",
            "-e",
            settings.headscale_preauth_expiration,
            "--tags",
            settings.headscale_worker_tag,
            "-o",
            "json",
        ]
    )
    data = json.loads(output)
    key = data.get("key") or data.get("preAuthKey", {}).get("key")
    if not key:
        raise HeadscaleError("Headscale did not return a worker preauth key")
    return PreAuthKey(key=key, user_id=user_id)


def exit_node_registration_command(auth_key: str) -> str:
    settings = get_settings()
    return (
        f"tailscale up --login-server={settings.headscale_url} "
        f"--advertise-exit-node --authkey={auth_key}"
    )


def exit_node_web_registration_hint() -> str:
    settings = get_settings()
    return (
        f"Nell'app Tailscale: server personalizzato → {settings.headscale_url}\n"
        f"Abilita «Usa come exit node», poi attendi l'apertura del browser su /register/…"
    )


def _parse_registered_node(data: dict) -> RegisteredNode:
    node_id = data.get("id")
    if node_id is None:
        raise HeadscaleError("Headscale did not return a node id")
    hostname = headscale_node_name(data) or str(node_id)
    tailscale_ip = _node_ipv4(data)
    if not tailscale_ip:
        raise HeadscaleError("Headscale did not return a node IP")
    return RegisteredNode(
        node_id=int(node_id),
        hostname=hostname,
        tailscale_ip=tailscale_ip,
    )


def register_node_with_headscale(registration_key: str) -> dict:
    """Register a pending node; prefer Headscale 0.29+ auth register."""
    settings = get_settings()
    try:
        output = _run_headscale(
            [
                "auth",
                "register",
                "--auth-id",
                registration_key,
                "--user",
                settings.headscale_user,
                "-o",
                "json",
            ]
        )
        return json.loads(output)
    except HeadscaleError:
        output = _run_headscale(
            [
                "nodes",
                "register",
                "-u",
                settings.headscale_user,
                "-k",
                registration_key,
                "-o",
                "json",
            ]
        )
        return json.loads(output)


def approve_registration_request(registration_key: str) -> RegisteredNode:
    """Approve a mobile web-auth registration and configure it as exit node."""
    key = normalize_registration_key(registration_key)
    if not is_valid_registration_key(key):
        raise HeadscaleError(
            "Registration ID must be a 24-character key or hskey-authreq-* auth id"
        )
    node = _parse_registered_node(register_node_with_headscale(key))
    settings = get_settings()
    _run_headscale(
        [
            "nodes",
            "tag",
            "-i",
            str(node.node_id),
            "-t",
            settings.headscale_exit_node_tag,
        ]
    )
    try:
        _run_headscale(
            [
                "nodes",
                "approve-routes",
                "-i",
                str(node.node_id),
                "-r",
                "0.0.0.0/0",
            ]
        )
    except HeadscaleError:
        pass
    try:
        approve_exit_routes_for_tagged_nodes()
    except HeadscaleError:
        pass
    assigned_name = assign_exit_node_name(node.node_id)
    return RegisteredNode(
        node_id=node.node_id,
        hostname=assigned_name,
        tailscale_ip=node.tailscale_ip,
    )
