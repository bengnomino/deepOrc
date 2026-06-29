"""Worker persistence."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orchestrator.models.gateway import Gateway
from orchestrator.models.worker import Worker, WorkerStatus


class WorkerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, worker_id: int) -> Worker | None:
        return self._session.get(Worker, worker_id)

    def get_by_name(self, name: str) -> Worker | None:
        return self._session.scalars(select(Worker).where(Worker.name == name)).first()

    def list_all(self) -> list[Worker]:
        return list(self._session.scalars(select(Worker).order_by(Worker.id)).all())

    def list_enabled(self) -> list[Worker]:
        return list(
            self._session.scalars(
                select(Worker).where(Worker.enabled.is_(True)).order_by(Worker.id)
            ).all()
        )

    def create(self, worker: Worker) -> Worker:
        self._session.add(worker)
        self._session.flush()
        return worker

    def gateway_counts(self) -> dict[int, int]:
        rows = self._session.execute(
            select(Gateway.worker_id, func.count(Gateway.id)).group_by(Gateway.worker_id)
        ).all()
        return {int(worker_id): int(count) for worker_id, count in rows}

    def update_stats(
        self,
        worker: Worker,
        *,
        cpu_percent: float,
        memory_total_mb: int,
        memory_used_mb: int,
        memory_percent: float,
        network_rx_bps: float,
        network_tx_bps: float,
    ) -> None:
        worker.cpu_percent = cpu_percent
        worker.memory_total_mb = memory_total_mb
        worker.memory_used_mb = memory_used_mb
        worker.memory_percent = memory_percent
        worker.network_rx_bps = network_rx_bps
        worker.network_tx_bps = network_tx_bps
        worker.status = WorkerStatus.ONLINE
        worker.last_seen_at = datetime.now(UTC)
