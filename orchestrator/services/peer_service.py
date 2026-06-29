"""Peer business logic — deepOrc: one WireGuard backhaul peer per gateway."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from orchestrator.config import get_settings
from orchestrator.crypto import decrypt_value, encrypt_value
from orchestrator.models.gateway import GatewayStatus
from orchestrator.models.peer import Peer
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.gateway_agent_client import GatewayAgentClient
from orchestrator.services.gateway_service import GatewayService
from orchestrator.wg import ClientConfigParams, allocate_peer_ip, generate_keypair, ipv4_allowed_ips_full_tunnel, release_peer_ip, render_client_config

MAX_PEERS_PER_GATEWAY = 1


def default_backhaul_peer_name(gateway_name: str) -> str:
    return f"{gateway_name}-link"


@dataclass
class CreatePeerResult:
    peer: Peer
    client_conf: str


class PeerService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._gateways = GatewayRepository(session)
        self._peers = PeerRepository(session)
        self._settings = get_settings()

    def _get_agent(self, gateway_id: int) -> tuple:
        from orchestrator.crypto import decrypt_value
        from orchestrator.incus.target import incus_target

        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        if gateway.status != GatewayStatus.READY:
            raise ValueError(f"Gateway {gateway.name} is not ready")
        token = decrypt_value(gateway.agent_token_enc)
        incus_instance = gateway.incus_instance
        if gateway.worker and gateway.worker.incus_remote:
            incus_instance = incus_target(gateway.worker, gateway.incus_instance)
        return gateway, GatewayAgentClient(
            gateway.vm_ip, token, incus_instance=incus_instance
        )

    def create_peer(self, gateway_id: int, peer_name: str) -> CreatePeerResult:
        gateway, agent = self._get_agent(gateway_id)

        existing_peers = self._peers.list_by_gateway(gateway_id)
        if len(existing_peers) >= MAX_PEERS_PER_GATEWAY:
            raise ValueError(
                f"Gateway {gateway.name} already has the backhaul peer "
                f"({existing_peers[0].name})"
            )

        existing = [p for p in existing_peers if p.name == peer_name]
        if existing:
            raise ValueError(f"Peer {peer_name} already exists on gateway {gateway.name}")

        keys = generate_keypair()
        peer_ip = allocate_peer_ip(self._session, gateway)
        allowed_ips = f"{peer_ip}/32"

        peer = Peer(
            gateway_id=gateway.id,
            name=peer_name,
            public_key=keys.public_key,
            private_key_enc=encrypt_value(keys.private_key),
            allowed_ip=peer_ip,
            suspended=False,
        )
        self._peers.create(peer)

        agent.add_peer(keys.public_key, allowed_ips)

        gs = GatewayService(self._session)
        endpoint = gs.get_endpoint(gateway)
        client_conf = render_client_config(
            ClientConfigParams(
                private_key=keys.private_key,
                address=peer_ip,
                dns=self._settings.wg_dns,
                server_public_key=gateway.wg_server_pubkey,
                endpoint=endpoint,
                allowed_ips=ipv4_allowed_ips_full_tunnel(endpoint, gateway.wg_subnet),
            )
        )
        self._session.commit()
        return CreatePeerResult(peer=peer, client_conf=client_conf)

    def ensure_backhaul_peer(self, gateway_id: int) -> CreatePeerResult | None:
        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway or gateway.status != GatewayStatus.READY:
            return None
        if self._peers.list_by_gateway(gateway_id):
            return None
        return self.create_peer(gateway_id, default_backhaul_peer_name(gateway.name))

    def next_peer_name(self, gateway_id: int) -> str:
        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        existing = {peer.name for peer in self._peers.list_by_gateway(gateway_id)}
        if existing:
            raise ValueError(f"Gateway {gateway.name} already has a backhaul peer")
        return default_backhaul_peer_name(gateway.name)

    def export_config(self, peer_id: int) -> str:
        peer = self._peers.get_by_id(peer_id)
        if not peer:
            raise ValueError(f"Peer {peer_id} not found")
        gateway = self._gateways.get_by_id(peer.gateway_id)
        if not gateway:
            raise ValueError("Gateway not found")

        gs = GatewayService(self._session)
        endpoint = gs.get_endpoint(gateway)
        return render_client_config(
            ClientConfigParams(
                private_key=decrypt_value(peer.private_key_enc),
                address=peer.allowed_ip,
                dns=self._settings.wg_dns,
                server_public_key=gateway.wg_server_pubkey,
                endpoint=endpoint,
                allowed_ips=ipv4_allowed_ips_full_tunnel(endpoint, gateway.wg_subnet),
            )
        )

    def delete_peer(self, peer_id: int) -> None:
        peer = self._peers.get_by_id(peer_id)
        if not peer:
            raise ValueError(f"Peer {peer_id} not found")
        gateway, agent = self._get_agent(peer.gateway_id)
        agent.remove_peer(peer.public_key)
        release_peer_ip(self._session, gateway.id, peer.allowed_ip)
        self._peers.delete(peer)
        self._session.commit()

    def suspend_peer(self, peer_id: int) -> Peer:
        peer = self._peers.get_by_id(peer_id)
        if not peer:
            raise ValueError(f"Peer {peer_id} not found")
        _, agent = self._get_agent(peer.gateway_id)
        agent.suspend_peer(peer.public_key, peer.allowed_ip)
        self._peers.set_suspended(peer, True)
        self._session.commit()
        return peer

    def resume_peer(self, peer_id: int) -> Peer:
        peer = self._peers.get_by_id(peer_id)
        if not peer:
            raise ValueError(f"Peer {peer_id} not found")
        _, agent = self._get_agent(peer.gateway_id)
        agent.resume_peer(peer.public_key, peer.allowed_ip)
        self._peers.set_suspended(peer, False)
        self._session.commit()
        return peer

    def regenerate_peer_keys(self, peer_id: int) -> CreatePeerResult:
        peer = self._peers.get_by_id(peer_id)
        if not peer:
            raise ValueError(f"Peer {peer_id} not found")
        gateway, agent = self._get_agent(peer.gateway_id)

        old_pubkey = peer.public_key
        agent.remove_peer(old_pubkey)

        keys = generate_keypair()
        allowed_ips = f"{peer.allowed_ip}/32"
        agent.add_peer(keys.public_key, allowed_ips)

        peer.public_key = keys.public_key
        peer.private_key_enc = encrypt_value(keys.private_key)
        self._session.flush()

        gs = GatewayService(self._session)
        endpoint = gs.get_endpoint(gateway)
        client_conf = render_client_config(
            ClientConfigParams(
                private_key=keys.private_key,
                address=peer.allowed_ip,
                dns=self._settings.wg_dns,
                server_public_key=gateway.wg_server_pubkey,
                endpoint=endpoint,
                allowed_ips=ipv4_allowed_ips_full_tunnel(endpoint, gateway.wg_subnet),
            )
        )
        self._session.commit()
        return CreatePeerResult(peer=peer, client_conf=client_conf)
