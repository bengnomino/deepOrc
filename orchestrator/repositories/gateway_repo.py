"""Gateway repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.gateway import Gateway, GatewayStatus


class GatewayRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, gateway_id: int) -> Gateway | None:
        return self._session.get(Gateway, gateway_id)

    def get_by_name(self, name: str) -> Gateway | None:
        return self._session.scalars(select(Gateway).where(Gateway.name == name)).first()

    def get_by_tailscale_hostname(self, hostname: str) -> Gateway | None:
        return self._session.scalars(
            select(Gateway).where(Gateway.tailscale_hostname == hostname)
        ).first()

    def list_all(self) -> list[Gateway]:
        return list(self._session.scalars(select(Gateway).order_by(Gateway.id)).all())

    def create(self, gateway: Gateway) -> Gateway:
        self._session.add(gateway)
        self._session.flush()
        return gateway

    def update_status(
        self,
        gateway: Gateway,
        status: GatewayStatus,
        error_message: str | None = None,
    ) -> Gateway:
        gateway.status = status
        gateway.error_message = error_message
        self._session.flush()
        return gateway

    def delete(self, gateway: Gateway) -> None:
        self._session.delete(gateway)
