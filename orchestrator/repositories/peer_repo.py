"""Peer repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.peer import Peer


class PeerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, peer_id: int) -> Peer | None:
        return self._session.get(Peer, peer_id)

    def get_by_public_key(self, public_key: str) -> Peer | None:
        return self._session.scalars(select(Peer).where(Peer.public_key == public_key)).first()

    def list_by_gateway(self, gateway_id: int) -> list[Peer]:
        return list(
            self._session.scalars(
                select(Peer).where(Peer.gateway_id == gateway_id).order_by(Peer.id)
            ).all()
        )

    def create(self, peer: Peer) -> Peer:
        self._session.add(peer)
        self._session.flush()
        return peer

    def delete(self, peer: Peer) -> None:
        self._session.delete(peer)

    def set_suspended(self, peer: Peer, suspended: bool) -> Peer:
        peer.suspended = suspended
        self._session.flush()
        return peer
