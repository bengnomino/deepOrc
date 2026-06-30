"""Gateway business logic — deepOrc: each gateway advertises as Tailscale exit node."""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from orchestrator.cloudinit import CloudInitParams, render_openwrt_setup, render_user_data
from orchestrator.config import get_settings
from orchestrator.crypto import encrypt_value, generate_token, hash_token
from orchestrator.headscale import (
    HeadscaleError,
    approve_exit_routes_for_tagged_nodes,
    approve_node_exit_route,
    create_gateway_preauth_key,
    delete_gateway_headscale_node,
    find_gateway_headscale_node,
)
from orchestrator.headscale.client import (
    get_node_tailscale_ip_by_hostname,
    list_headscale_nodes_raw,
    rename_gateway_headscale_display_name,
)
from orchestrator.naming import headscale_node_name, validate_tailscale_display_name
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
logger = logging.getLogger(__name__)


def _gateway_headscale_hostnames(gateway: Gateway) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in (gateway.tailscale_hostname, gateway.name, gateway.incus_instance):
        if value and value not in seen:
            seen.add(value)
            names.append(value)
    return names


@dataclass
class CreateGatewayRequest:
    gateway_name: str | None = None
    udp_port: int | None = None
    worker_id: int | None = None
    peer_group_id: int | None = None
    lan_ip: str | None = None
    macvlan_slot: int | None = None


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
            peer_group_id=request.peer_group_id,
            lan_ip=request.lan_ip,
            macvlan_slot=request.macvlan_slot,
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
        node = find_gateway_headscale_node(
            hostnames=[gateway.tailscale_hostname, gateway.name],
        )
        if node and node.get("id") is not None:
            try:
                approve_node_exit_route(int(node["id"]))
            except HeadscaleError:
                pass
        try:
            approve_exit_routes_for_tagged_nodes()
        except HeadscaleError:
            pass
        tailscale_ip = get_node_tailscale_ip_by_hostname(gateway.tailscale_hostname)
        if not tailscale_ip:
            tailscale_ip = get_node_tailscale_ip_by_hostname(gateway.name)
        if not tailscale_ip and gateway.exit_node_id not in {"", EXIT_NODE_PENDING}:
            tailscale_ip = gateway.exit_node_id
        if tailscale_ip:
            gateway.exit_node_id = tailscale_ip
            self._session.flush()

    def rename_tailscale_display_name(self, gateway_id: int, display_name: str) -> Gateway:
        """Rename the gateway on Headscale; internal gateway.name is unchanged."""
        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        if gateway.status != GatewayStatus.READY:
            raise ValueError(f"Gateway {gateway.name} is not ready")

        new_name = validate_tailscale_display_name(display_name)
        if new_name == gateway.tailscale_hostname:
            return gateway

        other = self._gateways.get_by_tailscale_hostname(new_name)
        if other and other.id != gateway_id:
            raise ValueError(f"Headscale name {new_name} is already used by gateway {other.name}")

        node = find_gateway_headscale_node(
            tailscale_ip=gateway.exit_node_id if gateway.exit_node_id not in {"", EXIT_NODE_PENDING} else None,
            hostnames=[gateway.tailscale_hostname, gateway.name],
        )
        if not node:
            raise ValueError(
                f"Gateway {gateway.name} not found on Headscale — wait for Tailscale to come online"
            )

        node_id = node.get("id")
        if node_id is None:
            raise ValueError("Headscale did not return a node id")

        for existing in list_headscale_nodes_raw():
            if existing.get("id") == node_id:
                continue
            if headscale_node_name(existing) == new_name:
                raise ValueError(f"Headscale name {new_name} is already taken")

        try:
            rename_gateway_headscale_display_name(int(node_id), new_name)
        except HeadscaleError as exc:
            raise ValueError(str(exc)) from exc

        from orchestrator.crypto import decrypt_value

        agent_token = decrypt_value(gateway.agent_token_enc)
        try:
            self._agent_client(gateway, agent_token).set_tailscale_hostname(new_name)
        except Exception:
            pass

        gateway.tailscale_hostname = new_name
        self._session.flush()
        self._session.commit()
        return gateway

    def fetch_tailscale_status(self, gateway: Gateway) -> str | None:
        if gateway.status != GatewayStatus.READY:
            return None
        from orchestrator.crypto import decrypt_value

        try:
            agent_token = decrypt_value(gateway.agent_token_enc)
            data = self._agent_client(gateway, agent_token).tailscale_status()
            text = (data.get("status") or "").strip()
            return text or None
        except Exception as exc:
            logger.warning("tailscale status for %s failed: %s", gateway.name, exc)
            return None

    def restart_gateway(self, gateway_id: int) -> Gateway:
        from orchestrator.incus import IncusClient, restart_gateway_vm
        from orchestrator.incus.gateway_post_reboot import apply_gateway_post_reboot

        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        if gateway.status != GatewayStatus.READY:
            raise ValueError("Gateway is not ready")
        worker = self._resolve_worker(gateway)
        target = incus_target(worker, gateway.incus_instance)
        client_ctx = IncusClient() if worker.is_local else IncusClient(worker=worker)
        with client_ctx as client:
            restart_gateway_vm(client, gateway.incus_instance)
        apply_gateway_post_reboot(target)
        from orchestrator.services.peer_service import PeerService

        PeerService(self._session).resync_gateway_peers(gateway_id)
        return gateway

    def gateway_boot_status(self, gateway_id: int) -> dict[str, object]:
        from orchestrator.crypto import decrypt_value
        from orchestrator.incus import IncusClient, get_vm_status

        gateway = self._gateways.get_by_id(gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        worker = self._resolve_worker(gateway)
        vm_status = "unknown"
        try:
            client_ctx = IncusClient() if worker.is_local else IncusClient(worker=worker)
            with client_ctx as client:
                vm_status = get_vm_status(client, gateway.incus_instance)
        except Exception as exc:
            logger.debug("VM status for gateway %s failed: %s", gateway.name, exc)

        tailscale_online = False
        wg_online = False
        if gateway.status == GatewayStatus.READY and vm_status == "Running":
            try:
                token = decrypt_value(gateway.agent_token_enc)
                health = self._agent_client(gateway, token).health()
                tailscale_online = bool(health.get("tailscale_online"))
                wg_online = bool(health.get("wg_online"))
            except Exception as exc:
                logger.debug("Agent health for gateway %s failed: %s", gateway.name, exc)

        ready = vm_status == "Running" and wg_online and tailscale_online
        return {
            "vm_status": vm_status,
            "wg_online": wg_online,
            "tailscale_online": tailscale_online,
            "ready": ready,
        }

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
                apply_wg_snat=True,
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
            try:
                agent.advertise_exit_node()
                agent.run_exit_via_wg()
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Post-peer exit setup failed for gateway %s: %s", gateway_id, exc
                )
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

        tailscale_ip = (
            gateway.exit_node_id
            if gateway.exit_node_id not in {"", EXIT_NODE_PENDING}
            else None
        )
        try:
            removed = delete_gateway_headscale_node(
                tailscale_ip=tailscale_ip,
                hostnames=_gateway_headscale_hostnames(gateway),
            )
            if not removed:
                logger.warning(
                    "No Headscale node found for gateway %s (%s)",
                    gateway.name,
                    tailscale_ip or "no tailscale IP",
                )
        except HeadscaleError as exc:
            logger.warning(
                "Headscale node delete failed for gateway %s: %s",
                gateway.name,
                exc,
            )

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
