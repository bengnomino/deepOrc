"""Worker selection, registration, and heartbeat."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from orchestrator.config import get_settings
from orchestrator.crypto import decrypt_value, encrypt_value, generate_token, hash_token, verify_token
from orchestrator.headscale import HeadscaleError, create_worker_preauth_key
from orchestrator.incus.remote_setup import IncusRemoteError, add_worker_remote
from orchestrator.models.worker import Worker, WorkerStatus
from orchestrator.models.worker_enrollment import WorkerEnrollment
from orchestrator.repositories.worker_enrollment_repo import WorkerEnrollmentRepository
from orchestrator.repositories.worker_repo import WorkerRepository
from orchestrator.services.host_stats import HostStats


@dataclass
class RegisterWorkerResult:
    worker: Worker
    worker_token: str


@dataclass
class EnrollWorkerResult:
    enroll_token: str
    tailscale_auth_key: str
    command: str
    name: str
    display_name: str
    tailscale_hostname: str


@dataclass
class CompleteEnrollmentRequest:
    tailscale_hostname: str
    tailscale_ip: str
    incus_trust_token: str
    public_ip: str


class WorkerService:
    HEARTBEAT_STALE_SECONDS = 120

    def __init__(self, session: Session) -> None:
        self._session = session
        self._workers = WorkerRepository(session)
        self._enrollments = WorkerEnrollmentRepository(session)
        self._settings = get_settings()

    def ensure_default_local_worker(self) -> Worker:
        """Legacy FK target for old gateways; CP never hosts new gateways."""
        existing = self._workers.get_by_name("local")
        if existing:
            existing.enabled = False
            if existing.public_ip in {"", "127.0.0.1"}:
                existing.public_ip = self._settings.wg_endpoint_host
                existing.port_pool_start = self._settings.port_pool_start
                existing.port_pool_end = self._settings.port_pool_end
                existing.ip_pool_network = self._settings.ip_pool_network
                existing.ip_pool_start = self._settings.ip_pool_start
            self._session.commit()
            return existing

        worker = Worker(
            name="local",
            display_name="Local (control plane)",
            public_ip=self._settings.wg_endpoint_host,
            worker_token_hash=hash_token(generate_token()),
            port_pool_start=self._settings.port_pool_start,
            port_pool_end=self._settings.port_pool_end,
            ip_pool_network=self._settings.ip_pool_network,
            ip_pool_start=self._settings.ip_pool_start,
            enabled=False,
            status=WorkerStatus.OFFLINE,
        )
        self._workers.create(worker)
        self._session.commit()
        return worker

    def pick_worker(self) -> Worker:
        online = self.list_online_workers()
        if not online:
            raise ValueError("No online gateway worker available")

        counts = self._workers.gateway_counts()
        return min(online, key=lambda worker: (counts.get(worker.id, 0), worker.id))

    def list_online_workers(self) -> list[Worker]:
        return [
            row["worker"]
            for row in self.dashboard_workers()
            if row["status"] == WorkerStatus.ONLINE
        ]

    def resolve_worker_for_gateway(self, worker_id: int | None) -> Worker:
        online = self.list_online_workers()
        if worker_id is not None:
            worker = self.get_worker(worker_id)
            if worker.is_local:
                raise ValueError("Cannot create gateway on control plane")
            if not worker.enabled:
                raise ValueError(f"Worker {worker.display_name} is disabled")
            if self.effective_status(worker) != WorkerStatus.ONLINE:
                raise ValueError(f"Worker {worker.display_name} is offline")
            return worker

        if not online:
            raise ValueError("No online gateway worker available")
        if len(online) > 1:
            raise ValueError("Select a worker for the new gateway")
        return online[0]

    def get_worker(self, worker_id: int) -> Worker:
        worker = self._workers.get_by_id(worker_id)
        if not worker:
            raise ValueError(f"Worker {worker_id} not found")
        return worker

    def register_worker(
        self,
        *,
        name: str,
        display_name: str | None,
        public_ip: str,
        tailscale_hostname: str | None = None,
        incus_remote: str | None = None,
        incus_url: str | None = None,
        incus_cert_path: str | None = None,
        incus_key_path: str | None = None,
        incus_server_cert_path: str | None = None,
        port_pool_start: int | None = None,
        port_pool_end: int | None = None,
        ip_pool_network: str | None = None,
        ip_pool_start: str | None = None,
    ) -> RegisterWorkerResult:
        if self._workers.get_by_name(name):
            raise ValueError(f"Worker {name} already exists")

        token = generate_token()
        worker = Worker(
            name=name,
            display_name=display_name or name,
            public_ip=public_ip,
            tailscale_hostname=tailscale_hostname,
            incus_remote=incus_remote,
            incus_url=incus_url,
            incus_cert_path=incus_cert_path,
            incus_key_path=incus_key_path,
            incus_server_cert_path=incus_server_cert_path,
            worker_token_hash=hash_token(token),
            port_pool_start=port_pool_start or self._settings.port_pool_start,
            port_pool_end=port_pool_end or self._settings.port_pool_end,
            ip_pool_network=ip_pool_network or self._settings.ip_pool_network,
            ip_pool_start=ip_pool_start or self._settings.ip_pool_start,
            enabled=True,
            status=WorkerStatus.OFFLINE,
        )
        self._workers.create(worker)
        self._session.commit()
        return RegisterWorkerResult(worker=worker, worker_token=token)

    def authenticate_worker(self, worker_id: int, token: str) -> Worker:
        worker = self.get_worker(worker_id)
        if not verify_token(token, worker.worker_token_hash):
            raise ValueError("Invalid worker token")
        return worker

    def record_heartbeat(self, worker: Worker, stats: HostStats) -> None:
        self._workers.update_stats(
            worker,
            cpu_percent=stats.cpu_percent,
            memory_total_mb=stats.memory_total_mb,
            memory_used_mb=stats.memory_used_mb,
            memory_percent=stats.memory_percent,
            network_rx_bps=stats.network_rx_bytes_per_sec,
            network_tx_bps=stats.network_tx_bytes_per_sec,
        )
        self._session.commit()

    @staticmethod
    def _utc_dt(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def effective_status(self, worker: Worker) -> WorkerStatus:
        if not worker.enabled:
            return WorkerStatus.DISABLED
        if worker.last_seen_at is None:
            return WorkerStatus.OFFLINE
        age = (datetime.now(UTC) - self._utc_dt(worker.last_seen_at)).total_seconds()
        if age > self.HEARTBEAT_STALE_SECONDS:
            return WorkerStatus.OFFLINE
        return WorkerStatus.ONLINE

    def dashboard_workers(self) -> list[dict]:
        counts = self._workers.gateway_counts()
        rows: list[dict] = []
        for worker in self._workers.list_all():
            if worker.is_local:
                continue
            status = self.effective_status(worker)
            rows.append(
                {
                    "worker": worker,
                    "status": status,
                    "gateway_count": counts.get(worker.id, 0),
                }
            )
        return rows

    def _next_worker_identity(self) -> tuple[str, str]:
        taken = {
            worker.name
            for worker in self._workers.list_all()
            if not worker.is_local
        }
        taken |= self._enrollments.list_active_names()
        for index in range(1, 1000):
            name = f"worker{index}"
            if name not in taken:
                return name, f"Worker {index}"
        raise ValueError("No available worker name")

    def create_enrollment(self) -> EnrollWorkerResult:
        existing = self._enrollments.get_latest_active()
        if existing:
            if existing.enroll_token_enc and existing.headscale_auth_key_enc:
                return self._enrollment_result(
                    existing,
                    decrypt_value(existing.enroll_token_enc),
                    decrypt_value(existing.headscale_auth_key_enc),
                )
            return self._refresh_enrollment(existing)

        slug, display_name = self._next_worker_identity()
        if self._workers.get_by_name(slug):
            raise ValueError(f"Worker {slug} already exists")

        try:
            preauth = create_worker_preauth_key()
        except HeadscaleError as exc:
            raise ValueError(f"Failed to create Tailscale auth key: {exc}") from exc

        token = generate_token()
        enrollment = WorkerEnrollment(
            token_hash=hash_token(token),
            name=slug,
            display_name=display_name,
            public_ip="0.0.0.0",
            tailscale_hostname=slug,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            enroll_token_enc=encrypt_value(token),
            headscale_auth_key_enc=encrypt_value(preauth.key),
        )
        self._enrollments.create(enrollment)
        self._session.commit()
        return self._enrollment_result(enrollment, token, preauth.key)

    def _enrollment_result(
        self,
        enrollment: WorkerEnrollment,
        enroll_token: str,
        tailscale_auth_key: str,
    ) -> EnrollWorkerResult:
        return EnrollWorkerResult(
            enroll_token=enroll_token,
            tailscale_auth_key=tailscale_auth_key,
            command=self.build_join_command(
                enroll_token=enroll_token,
                tailscale_auth_key=tailscale_auth_key,
                worker_name=enrollment.name,
                worker_display_name=enrollment.display_name,
                tailscale_hostname=enrollment.tailscale_hostname,
            ),
            name=enrollment.name,
            display_name=enrollment.display_name,
            tailscale_hostname=enrollment.tailscale_hostname,
        )

    def _refresh_enrollment(self, enrollment: WorkerEnrollment) -> EnrollWorkerResult:
        try:
            preauth = create_worker_preauth_key()
        except HeadscaleError as exc:
            raise ValueError(f"Failed to create Tailscale auth key: {exc}") from exc

        token = generate_token()
        enrollment.token_hash = hash_token(token)
        enrollment.enroll_token_enc = encrypt_value(token)
        enrollment.headscale_auth_key_enc = encrypt_value(preauth.key)
        self._session.commit()
        return self._enrollment_result(enrollment, token, preauth.key)

    def build_join_command(
        self,
        *,
        enroll_token: str,
        tailscale_auth_key: str,
        worker_name: str,
        worker_display_name: str,
        tailscale_hostname: str,
    ) -> str:
        base = self._settings.public_orchestrator_url
        script_url = f"{base}/ui/workers/join.sh"
        return (
            f"curl -fsSL '{script_url}' -o /tmp/orchtest-join-worker.sh && \\\n"
            "sudo env \\\n"
            f"  CP_BASE_URL='{base}' \\\n"
            f"  ENROLL_TOKEN='{enroll_token}' \\\n"
            f"  TAILSCALE_AUTHKEY='{tailscale_auth_key}' \\\n"
            f"  WORKER_NAME='{worker_name}' \\\n"
            f"  WORKER_DISPLAY_NAME='{worker_display_name}' \\\n"
            f"  TAILSCALE_HOSTNAME='{tailscale_hostname}' \\\n"
            "  bash /tmp/orchtest-join-worker.sh"
        )

    def complete_enrollment(self, enroll_token: str, request: CompleteEnrollmentRequest) -> RegisterWorkerResult:
        enrollment = self._enrollments.get_by_token_hash(hash_token(enroll_token))
        if not enrollment or not verify_token(enroll_token, enrollment.token_hash):
            raise ValueError("Invalid enrollment token")
        if enrollment.used_at is not None:
            raise ValueError("Enrollment token already used")
        if self._utc_dt(enrollment.expires_at) <= datetime.now(UTC):
            raise ValueError("Enrollment token expired")
        if self._workers.get_by_name(enrollment.name):
            raise ValueError(f"Worker {enrollment.name} already exists")

        incus_url = f"https://{request.tailscale_ip.strip()}:8443"
        try:
            paths = add_worker_remote(
                enrollment.name,
                incus_url,
                request.incus_trust_token.strip(),
                self._settings.data_dir,
            )
        except IncusRemoteError as exc:
            raise ValueError(f"Incus remote setup failed: {exc}") from exc

        token = generate_token()
        public_ip = request.public_ip.strip()
        if not public_ip:
            raise ValueError("Worker public IP is required")
        worker = Worker(
            name=enrollment.name,
            display_name=enrollment.display_name,
            public_ip=public_ip,
            tailscale_hostname=request.tailscale_hostname.strip() or enrollment.tailscale_hostname,
            incus_remote=enrollment.name,
            incus_url=incus_url,
            incus_cert_path=paths.cert_path,
            incus_key_path=paths.key_path,
            incus_server_cert_path=paths.server_cert_path,
            worker_token_hash=hash_token(token),
            port_pool_start=self._settings.port_pool_start,
            port_pool_end=self._settings.port_pool_end,
            ip_pool_network=self._settings.ip_pool_network,
            ip_pool_start=self._settings.ip_pool_start,
            enabled=True,
            status=WorkerStatus.OFFLINE,
        )
        self._workers.create(worker)
        self._session.flush()
        enrollment.used_at = datetime.now(UTC)
        enrollment.worker_id = worker.id
        self._session.commit()
        return RegisterWorkerResult(worker=worker, worker_token=token)
