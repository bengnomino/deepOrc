"""View helpers for the Web UI."""

from datetime import UTC, datetime

from orchestrator.headscale.client import PEER_ONLINE_HANDSHAKE_SECONDS, HeadscaleNode
from orchestrator.models.gateway import Gateway
from orchestrator.models.metrics import PeerMetric
from orchestrator.models.peer import Peer


def worker_host_label(worker) -> str:
    if worker.tailscale_hostname:
        return worker.tailscale_hostname
    return worker.name


def peer_is_online(peer: Peer, metric: PeerMetric | None) -> bool:
    if peer.suspended:
        return False
    if not metric or not metric.last_handshake:
        return False
    last = metric.last_handshake
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - last).total_seconds()
    return age < PEER_ONLINE_HANDSHAKE_SECONDS


def sort_peers_by_connectivity(
    peers: list[Peer],
    metrics: dict[int, PeerMetric | None],
) -> list[dict]:
    rows = [
        {
            "peer": peer,
            "online": peer_is_online(peer, metrics.get(peer.id)),
            "metric": metrics.get(peer.id),
        }
        for peer in peers
    ]
    rows.sort(key=lambda row: (not row["online"], row["peer"].name.lower()))
    return rows


def partition_exit_nodes(
    headscale_nodes: list[HeadscaleNode],
    gateways: list[Gateway],
) -> tuple[list[HeadscaleNode], dict[str, HeadscaleNode]]:
    gateway_hostnames = {g.name for g in gateways}
    assigned_ips = {
        g.exit_node_id for g in gateways if g.exit_node_id not in {"", "pending"}
    }
    unassigned: list[HeadscaleNode] = []
    by_ip: dict[str, HeadscaleNode] = {}

    for node in headscale_nodes:
        if node.hostname in gateway_hostnames:
            continue
        by_ip[node.tailscale_ip] = node
        if node.tailscale_ip not in assigned_ips:
            unassigned.append(node)

    unassigned.sort(key=lambda n: (not n.online, n.hostname.lower()))
    return unassigned, by_ip


def selectable_exit_nodes(
    gateway: Gateway,
    gateways: list[Gateway],
    headscale_nodes: list[HeadscaleNode],
) -> list[HeadscaleNode]:
    """Exit nodes available for this gateway (unassigned elsewhere, route approved)."""
    gateway_hostnames = {g.name for g in gateways}
    assigned_elsewhere = {
        g.exit_node_id
        for g in gateways
        if g.id != gateway.id and g.exit_node_id not in {"", "pending"}
    }
    current_ip = gateway.exit_node_id if gateway.exit_node_id not in {"", "pending"} else None
    by_ip = {node.tailscale_ip: node for node in headscale_nodes}
    options: list[HeadscaleNode] = []

    for node in headscale_nodes:
        if node.hostname in gateway_hostnames:
            continue
        if not (node.exit_approved or node.exit_tagged or node.exit_advertised):
            continue
        if node.tailscale_ip in assigned_elsewhere:
            continue
        options.append(node)

    if current_ip and current_ip in by_ip:
        current = by_ip[current_ip]
        if current not in options:
            options.insert(0, current)

    options.sort(key=lambda n: (not n.online, n.hostname.lower()))
    return options
