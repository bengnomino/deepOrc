"""Metrics repository."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.metrics import GatewayMetric, PeerMetric


class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_gateway_metric(
        self,
        gateway_id: int,
        vm_status: str | None,
        tailscale_online: bool | None,
        wg_online: bool | None,
        exit_node_reachable: bool | None,
    ) -> GatewayMetric:
        metric = GatewayMetric(
            gateway_id=gateway_id,
            vm_status=vm_status,
            tailscale_online=tailscale_online,
            wg_online=wg_online,
            exit_node_reachable=exit_node_reachable,
            polled_at=datetime.now(UTC),
        )
        self._session.add(metric)
        self._session.flush()
        return metric

    def add_peer_metric(
        self,
        peer_id: int,
        last_handshake: datetime | None,
        rx_bytes: int | None,
        tx_bytes: int | None,
    ) -> PeerMetric:
        metric = PeerMetric(
            peer_id=peer_id,
            last_handshake=last_handshake,
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            polled_at=datetime.now(UTC),
        )
        self._session.add(metric)
        self._session.flush()
        return metric

    def latest_gateway_metric(self, gateway_id: int) -> GatewayMetric | None:
        return self._session.scalars(
            select(GatewayMetric)
            .where(GatewayMetric.gateway_id == gateway_id)
            .order_by(GatewayMetric.polled_at.desc())
            .limit(1)
        ).first()

    def latest_peer_metric(self, peer_id: int) -> PeerMetric | None:
        return self._session.scalars(
            select(PeerMetric)
            .where(PeerMetric.peer_id == peer_id)
            .order_by(PeerMetric.polled_at.desc())
            .limit(1)
        ).first()
