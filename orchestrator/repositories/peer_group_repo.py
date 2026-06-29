"""Peer group repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from orchestrator.models.peer_group import PeerGroup


class PeerGroupRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, group_id: int) -> PeerGroup | None:
        return self._session.scalars(
            select(PeerGroup)
            .where(PeerGroup.id == group_id)
            .options(joinedload(PeerGroup.worker), joinedload(PeerGroup.gateways))
        ).unique().first()

    def get_by_name(self, name: str) -> PeerGroup | None:
        return self._session.scalars(select(PeerGroup).where(PeerGroup.name == name)).first()

    def list_all(self) -> list[PeerGroup]:
        return list(
            self._session.scalars(
                select(PeerGroup).order_by(PeerGroup.id).options(joinedload(PeerGroup.gateways))
            ).unique().all()
        )

    def create(self, group: PeerGroup) -> PeerGroup:
        self._session.add(group)
        self._session.flush()
        return group

    def delete(self, group: PeerGroup) -> None:
        self._session.delete(group)
