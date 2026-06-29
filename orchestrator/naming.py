"""Sequential resource names for gateways and exit nodes."""

from __future__ import annotations

import re

GATEWAY_PREFIX = "gw-"
EXIT_NODE_PREFIX = "ex-"
SEQUENTIAL_WIDTH = 3

GATEWAY_NAME_RE = re.compile(r"^gw-\d{3}$")
EXIT_NODE_NAME_RE = re.compile(r"^ex-\d{3}$")
TAILSCALE_DISPLAY_NAME_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


def format_sequential_name(prefix: str, index: int, width: int = SEQUENTIAL_WIDTH) -> str:
    return f"{prefix}{index:0{width}d}"


def next_sequential_name(prefix: str, taken: set[str], width: int = SEQUENTIAL_WIDTH) -> str:
    limit = 10**width
    for index in range(limit):
        name = format_sequential_name(prefix, index, width)
        if name not in taken:
            return name
    raise ValueError(f"No available names for prefix {prefix} (width {width})")


def is_gateway_name(name: str) -> bool:
    return bool(GATEWAY_NAME_RE.match(name))


def is_exit_node_name(name: str) -> bool:
    return bool(EXIT_NODE_NAME_RE.match(name))


def normalize_tailscale_display_name(name: str) -> str:
    return name.strip().lower()


def validate_tailscale_display_name(name: str) -> str:
    """Validate a user-chosen Headscale / Tailscale hostname (not gw-NNN)."""
    value = normalize_tailscale_display_name(name)
    if not value:
        raise ValueError("Headscale name cannot be empty")
    if len(value) > 63:
        raise ValueError("Headscale name must be at most 63 characters")
    if not TAILSCALE_DISPLAY_NAME_RE.match(value):
        raise ValueError(
            "Headscale name must start and end with a letter or digit and contain only letters, digits, and hyphens"
        )
    return value


def headscale_node_name(node: dict) -> str:
    for key in ("given_name", "givenName", "name", "hostname"):
        value = node.get(key)
        if value:
            return str(value)
    return ""


def collect_exit_node_names(nodes: list[dict]) -> set[str]:
    return {
        name
        for node in nodes
        if is_exit_node_name(name := headscale_node_name(node))
    }


def collect_gateway_names(nodes: list[dict], *, extra: set[str] | None = None) -> set[str]:
    taken = {name for node in nodes if is_gateway_name(name := headscale_node_name(node))}
    if extra:
        taken |= extra
    return taken
