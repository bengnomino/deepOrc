"""Unit tests for Web UI view helpers."""

from datetime import UTC, datetime, timedelta

from orchestrator.headscale.client import HeadscaleNode
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.metrics import PeerMetric
from orchestrator.models.peer import Peer
from orchestrator.services.peer_service import default_backhaul_peer_name
from orchestrator.web.views import partition_exit_nodes, peer_is_online, selectable_exit_nodes, sort_peers_by_connectivity


def test_default_backhaul_peer_name():
    assert default_backhaul_peer_name("gw-00") == "gw-00-link"


def _peer(peer_id: int, name: str, suspended: bool = False) -> Peer:
    peer = Peer(
        id=peer_id,
        gateway_id=1,
        name=name,
        public_key=f"pub{peer_id}",
        private_key_enc="enc",
        allowed_ip=f"10.64.0.{peer_id}/32",
        suspended=suspended,
    )
    return peer


def test_peer_is_online_recent_handshake():
    peer = _peer(1, "vdi-01")
    metric = PeerMetric(
        peer_id=1,
        last_handshake=datetime.now(UTC) - timedelta(seconds=30),
        rx_bytes=0,
        tx_bytes=0,
    )
    assert peer_is_online(peer, metric) is True


def test_peer_is_offline_when_suspended():
    peer = _peer(1, "vdi-01", suspended=True)
    metric = PeerMetric(
        peer_id=1,
        last_handshake=datetime.now(UTC),
        rx_bytes=0,
        tx_bytes=0,
    )
    assert peer_is_online(peer, metric) is False


def test_sort_peers_online_first():
    online_peer = _peer(1, "online")
    offline_peer = _peer(2, "offline")
    metrics = {
        1: PeerMetric(
            peer_id=1,
            last_handshake=datetime.now(UTC),
            rx_bytes=0,
            tx_bytes=0,
        ),
        2: None,
    }
    rows = sort_peers_by_connectivity([offline_peer, online_peer], metrics)
    assert [row["peer"].name for row in rows] == ["online", "offline"]


def test_partition_exit_nodes():
    gateways = [
        Gateway(
            id=1,
            name="gw-00",
            incus_instance="gw-gw-00",
            vm_ip="10.10.0.2",
            udp_port=51001,
            wg_subnet="10.64.0.0/24",
            wg_server_pubkey="pub",
            wg_server_privkey_enc="enc",
            exit_node_id="100.64.0.5",
            tailscale_auth_key_enc="enc",
            tailscale_hostname="gw-00",
            agent_token_hash="hash",
            agent_token_enc="enc",
            status=GatewayStatus.READY,
        )
    ]
    nodes = [
        HeadscaleNode(1, "android-1", "100.64.0.5", True, True, True, True),
        HeadscaleNode(2, "android-2", "100.64.0.6", True, True, True, True),
        HeadscaleNode(3, "gw-00", "100.64.0.10", True, False, False, False),
    ]
    unassigned, by_ip = partition_exit_nodes(nodes, gateways)
    assert [n.tailscale_ip for n in unassigned] == ["100.64.0.6"]
    assert by_ip["100.64.0.5"].hostname == "android-1"


def test_selectable_exit_nodes_excludes_assigned_elsewhere():
    gateways = [
        Gateway(
            id=1,
            name="gw-00",
            incus_instance="gw-gw-00",
            vm_ip="10.10.0.2",
            udp_port=51001,
            wg_subnet="10.64.0.0/24",
            wg_server_pubkey="pub",
            wg_server_privkey_enc="enc",
            exit_node_id="100.64.0.5",
            tailscale_auth_key_enc="enc",
            tailscale_hostname="gw-00",
            agent_token_hash="hash",
            agent_token_enc="enc",
            status=GatewayStatus.READY,
        ),
        Gateway(
            id=2,
            name="gw-01",
            incus_instance="gw-gw-01",
            vm_ip="10.10.0.3",
            udp_port=51002,
            wg_subnet="10.64.1.0/24",
            wg_server_pubkey="pub",
            wg_server_privkey_enc="enc",
            exit_node_id="pending",
            tailscale_auth_key_enc="enc",
            tailscale_hostname="gw-01",
            agent_token_hash="hash",
            agent_token_enc="enc",
            status=GatewayStatus.PENDING,
        ),
    ]
    nodes = [
        HeadscaleNode(1, "android-1", "100.64.0.5", True, True, True, True),
        HeadscaleNode(2, "android-2", "100.64.0.6", True, True, True, True),
    ]
    options = selectable_exit_nodes(gateways[1], gateways, nodes)
    assert [n.tailscale_ip for n in options] == ["100.64.0.6"]
