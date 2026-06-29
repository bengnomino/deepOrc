"""Gateway business logic — deepOrc: each gateway advertises as Tailscale exit node."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from orchestrator.cloudinit import CloudInitParams, render_openwrt_setup, render_user_data
from orchestrator.config import get_settings
from orchestrator.crypto import encrypt_value, generate_token, hash_token
from orchestrator.headscale import HeadscaleError, approve_exit_routes_for_tagged_nodes, create_gateway_preauth_key
from orchestrator.headscale.client import get_node_tailscale_ip_by_hostname
from orchestrator.incus import IncusClient, allocate_udp_port, allocate_vm_ip, launch_gateway_vm
from orchestrator.incus.target import incus_target
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.job import Job, JobStatus, JobType
from orchestrator.models.worker import Worker
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.job_repo import JobRepository
from orchestrator.services.gateway_agent_client import GatewayAgentClient
from orchestrator.services.worker_service import WorkerService
from orchestrator.naming import GATEWAY_PREFIX, collect_gateway_names, next_sequential_name
from orchestrator.wg import allocate_wg_subnet, generate_keypair

EXIT_NODE_PENDING = "pending"


@dataclass
class CreateGatewayRequest:
    gateway_name: str | None = None
    udp_port: int | None = None
    worker_id: int | None = None


@dataclass
class CreateGatewayResult:
    gateway: Gateway
    job: Job
    agent_token: str


class GatewayService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._gateways = GatewayRepository(session)
        self._jobs = JobRepository(session)
        self._workers = WorkerService(session)
        self._settings = get_settings()

    def _resolve_worker(self, gateway: Gateway) -> Worker:
        if gateway.worker is not None:
            return gateway.worker
        return self._workers.get_worker(gateway.worker_id)

    def _incus_client(self, worker: Worker) -> IncusClient:
        if worker.is_local:
            return IncusClient()
        return IncusClient(worker=worker)

    def _incus_exec_target(self, gateway: Gateway) -> str:
        worker = self._resolve_worker(gateway)
        return incus_target(worker, gateway.incus_instance)

    def _agent_client(self, gateway: Gateway, token: str) -> GatewayAgentClient:
        return GatewayAgentClient(
            gateway.vm_ip,
            token,
            incus_instance=self._incus_exec_target(gateway),
        )

    def create_gateway(self, request: CreateGatewayRequest) -> CreateGatewayResult:
        gateway_name = request.gateway_name or self._next_gateway_name()
        if self._gateways.get_by_name(gateway_name):
            raise ValueError(f"Gateway {gateway_name} already exists")

        try:
            preauth = create_gateway_preauth_key()
        except HeadscaleError as exc:
            raise ValueError(f"Failed to create Headscale preauth key: {exc}") from exc

        agent_token = generate_token()
        wg_keys = generate_keypair()
        worker = self._workers.resolve_worker_for_gateway(request.worker_id)
        vm_ip = allocate_vm_ip(self._session, worker)
        udp_port = request.udp_port or allocate_udp_port(self._session, worker)

        gateway = Gateway(
            worker_id=worker.id,
            name=gateway_name,
            incus_instance=f"gw-{gateway_name}",
            vm_ip=vm_ip,
            udp_port=udp_port,
            wg_subnet="pending",
            wg_server_pubkey=wg_keys.public_key,
            wg_server_privkey_enc=encrypt_value(wg_keys.private_key),
            exit_node_id=EXIT_NODE_PENDING,
            tailscale_auth_key_enc=encrypt_value(preauth.key),
            tailscale_hostname=gateway_name,
            agent_token_hash=hash_token(agent_token),
            agent_token_enc=encrypt_value(agent_token),
            status=GatewayStatus.PENDING,
        )
        self._gateways.create(gateway)
        self._session.flush()

        subnet = allocate_wg_subnet(self._session, gateway.id)
        gateway.wg_subnet = subnet.subnet

        job = Job(type=JobType.CREATE_GATEWAY, gateway_id=gateway.id, status=JobStatus.PENDING)
        self._jobs.create(job)
        self._session.commit()

        return CreateGatewayResult(gateway=gateway, job=job, agent_token=agent_token)

    def _next_gateway_name(self) -> str:
        existing = {g.name for g in self._gateways.list_all()}
        taken = collect_gateway_names([], extra=existing)
        return next_sequential_name(GATEWAY_PREFIX, taken)

    def _finalize_exit_node(self, gateway: Gateway, agent: GatewayAgentClient) -> None:
        """Advertise gateway as exit node and store its Tailscale IP."""
        agent.advertise_exit_node()
        try:
            approve_exit_routes_for_tagged_nodes()
        except HeadscaleError:
            pass
        tailscale_ip = get_node_tailscale_ip_by_hostname(gateway.name)
        if tailscale_ip:
            gateway.exit_node_id = tailscale_ip
            self._session.flush()

    def provision_gateway(self, gateway_id: int, job_id: int | None = None) -> Gateway:
        from orchestrator.workers.provisioning_stages import (
            STAGE_AGENT_WAIT,
            STAGE_CLOUD_INIT,
            STAGE_PEER_SETUP,
            STAGE_REGISTER,
            STAGE_VM_LAUNCH,
            set_provision_stage,
        )

        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")

        def stage(name: str, *, touch: bool = True) -> None:
            if job_id is not None:
                set_provision_stage(self._session, job_id, name, touch=touch)

        def heartbeat(name: str) -> None:
            if job_id is not None:
                set_provision_stage(self._session, job_id, name, touch=True)

        from orchestrator.crypto import decrypt_value

        agent_token = decrypt_value(gateway.agent_token_enc)

        wg_priv = decrypt_value(gateway.wg_server_privkey_enc)
        ts_key = decrypt_value(gateway.tailscale_auth_key_enc)
        subnet = allocate_wg_subnet(self._session, gateway.id)
        worker = self._resolve_worker(gateway)

        params = CloudInitParams(
            gateway_name=gateway.name,
            wg_private_key=wg_priv,
            wg_gateway_ip=subnet.gateway_ip,
            wg_subnet=subnet.subnet,
            wg_listen_port=gateway.udp_port,
            headscale_url=self._settings.headscale_url_for_worker(is_local=worker.is_local),
            tailscale_auth_key=ts_key,
            agent_token=agent_token,
            orch_allowed_ip=self._settings.orch_host_ip,
            vm_ip=gateway.vm_ip,
            agent_port=self._settings.agent_port,
            gateway_agent_wheel_url=self._settings.gateway_agent_wheel_url,
            use_golden_image=self._settings.incus_image.startswith("local:"),
            net_interface=self._settings.incus_net_interface,
        )
        user_data = ""
        setup_script: str | None = None
        if self._settings.incus_provisioner == "openwrt":
            setup_script = render_openwrt_setup(params)
        else:
            user_data = render_user_data(params)

        self._gateways.update_status(gateway, GatewayStatus.PROVISIONING)
        stage(STAGE_VM_LAUNCH)
        self._session.commit()

        with self._incus_client(worker) as client:
            launch_gateway_vm(
                client,
                gateway.incus_instance,
                gateway.vm_ip,
                gateway.udp_port,
                user_data,
                setup_script,
                instance_target=incus_target(worker, gateway.incus_instance),
                listen_host=None if worker.is_local else worker.public_ip,
                apply_wg_snat=worker.is_local,
            )

        stage(STAGE_CLOUD_INIT)
        agent = self._agent_client(gateway, agent_token)
        import time

        cloud_init_deadline = time.time() + min(300, self._settings.provisioning_timeout_seconds)
        while time.time() < cloud_init_deadline:
            heartbeat(STAGE_CLOUD_INIT)
            try:
                agent.health()
                break
            except Exception:
                time.sleep(5)
        stage(STAGE_AGENT_WAIT)
        if not agent.wait_until_healthy(
            timeout=self._settings.provisioning_timeout_seconds,
            on_poll=lambda: heartbeat(STAGE_AGENT_WAIT),
        ):
            detail = "Agent health check timed out (WireGuard or Tailscale not online)"
            try:
                health = agent.health()
                detail = (
                    f"{detail}: wg={health.get('wg_online')} "
                    f"ts={health.get('tailscale_online')} "
                    f"exit={health.get('exit_node_configured')}"
                )
            except Exception:
                pass
            self._gateways.update_status(gateway, GatewayStatus.ERROR, detail)
            self._session.commit()
            return gateway

        stage(STAGE_REGISTER)
        agent.register(gateway.name)

        try:
            self._finalize_exit_node(gateway, agent)
        except Exception as exc:
            self._gateways.update_status(
                gateway,
                GatewayStatus.ERROR,
                f"Exit node advertise failed: {exc}",
            )
            self._session.commit()
            return gateway

        self._gateways.update_status(gateway, GatewayStatus.READY)
        self._session.commit()

        from orchestrator.services.peer_service import PeerService

        stage(STAGE_PEER_SETUP)
        try:
            PeerService(self._session).ensure_backhaul_peer(gateway_id)
        except ValueError:
            pass
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Backhaul peer setup failed for gateway %s: %s", gateway_id, exc
            )
            self._session.rollback()

        return gateway

    def get_endpoint(self, gateway: Gateway) -> str:
        worker = self._resolve_worker(gateway)
        return f"{worker.public_ip}:{gateway.udp_port}"

    def needs_provisioning(self, gateway: Gateway) -> bool:
        return gateway.status in {
            GatewayStatus.PENDING,
            GatewayStatus.ERROR,
            GatewayStatus.PROVISIONING,
        }

    def prepare_provisioning(self, gateway_id: int) -> None:
        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        if gateway.status == GatewayStatus.ERROR:
            self._gateways.update_status(gateway, GatewayStatus.PENDING)
            gateway.error_message = None
        elif gateway.status == GatewayStatus.PROVISIONING:
            latest = self._jobs.get_latest_create_job(gateway_id)
            if latest and latest.status == JobStatus.FAILED:
                self._gateways.update_status(gateway, GatewayStatus.PENDING)
                gateway.error_message = None
        job = self._jobs.reset_failed_job(gateway_id)
        if not job:
            job = Job(type=JobType.CREATE_GATEWAY, gateway_id=gateway.id, status=JobStatus.PENDING)
            self._jobs.create(job)
        self._session.commit()

    def request_delete_gateway(self, gateway_id: int) -> Job:
        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")

        existing = self._jobs.get_latest_delete_job(gateway_id)
        if gateway.status == GatewayStatus.DELETING:
            if existing and existing.status in {JobStatus.PENDING, JobStatus.RUNNING}:
                return existing

        self._gateways.update_status(gateway, GatewayStatus.DELETING)
        if existing and existing.status == JobStatus.PENDING:
            job = existing
        else:
            job = Job(
                type=JobType.DELETE_GATEWAY,
                gateway_id=gateway.id,
                status=JobStatus.PENDING,
            )
            self._jobs.create(job)
        self._session.commit()
        return job

    def execute_delete_gateway(self, gateway_id: int, job_id: int | None = None) -> None:
        from orchestrator.incus import IncusClient, delete_gateway_vm, release_udp_port, release_vm_ip

        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            if job_id:
                job = self._jobs.get_by_id(job_id)
                if job and job.status != JobStatus.COMPLETED:
                    self._jobs.update_status(job, JobStatus.COMPLETED)
                    self._session.commit()
            return

        worker = self._resolve_worker(gateway)
        try:
            with self._incus_client(worker) as client:
                delete_gateway_vm(client, gateway.incus_instance)
        except Exception:
            pass
        release_vm_ip(self._session, gateway.worker_id, gateway.vm_ip)
        release_udp_port(self._session, gateway.worker_id, gateway.udp_port)
        self._gateways.delete(gateway)
        if job_id:
            job = self._jobs.get_by_id(job_id)
            if job:
                self._jobs.update_status(job, JobStatus.COMPLETED)
        self._session.commit()

    def delete_gateway(self, gateway_id: int) -> None:
        """Queue and run gateway deletion synchronously (tests / scripts)."""
        job = self.request_delete_gateway(gateway_id)
        self.execute_delete_gateway(gateway_id, job_id=job.id)
