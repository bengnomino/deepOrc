"""Periodic metrics collection from gateway agents."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from orchestrator.crypto import decrypt_value
from orchestrator.incus import IncusClient, get_vm_status
from orchestrator.incus.target import incus_target
from orchestrator.models.gateway import GatewayStatus
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.metrics_repo import MetricsRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.gateway_agent_client import GatewayAgentClient
from orchestrator.services.ip_geo import lookup_geo
from orchestrator.services.worker_service import WorkerService

logger = logging.getLogger(__name__)

_EGRESS_REFRESH_SECONDS = 3600


def _egress_geo_from_agent(agent: GatewayAgentClient) -> tuple[str | None, str | None]:
    try:
        payload = agent.egress_public_ip()
        ip = (payload.get("ip") or "").strip()
        if not ip:
            return None, None
        geo = lookup_geo(ip)
        if geo:
            return geo.ip, geo.country_code
        return ip, None
    except Exception as exc:
        logger.debug("egress geo lookup failed: %s", exc)
        return None, None


def collect_metrics(session: Session) -> int:
    gateways_repo = GatewayRepository(session)
    peers_repo = PeerRepository(session)
    metrics_repo = MetricsRepository(session)
    worker_service = WorkerService(session)
    count = 0

    try:
        for gateway in gateways_repo.list_all():
            if gateway.status != GatewayStatus.READY:
                continue

            worker = gateway.worker or worker_service.get_worker(gateway.worker_id)
            vm_status = "unknown"
            try:
                client_ctx = IncusClient() if worker.is_local else IncusClient(worker=worker)
                with client_ctx as client:
                    vm_status = get_vm_status(client, gateway.incus_instance)
            except Exception as exc:
                logger.warning("VM status check failed for %s: %s", gateway.name, exc)

            tailscale_online = None
            wg_online = None
            exit_node_reachable = None
            egress_public_ip = None
            egress_country_code = None

            try:
                token = decrypt_value(gateway.agent_token_enc)
                target = incus_target(worker, gateway.incus_instance)
                agent = GatewayAgentClient(gateway.vm_ip, token, incus_instance=target)
                health = agent.health()
                tailscale_online = health.get("tailscale_online")
                wg_online = health.get("wg_online")
                exit_node_reachable = health.get("exit_node_configured")

                latest = metrics_repo.latest_gateway_metric(gateway.id)
                if latest and latest.egress_public_ip:
                    age = (datetime.now(UTC) - latest.polled_at).total_seconds()
                    if age < _EGRESS_REFRESH_SECONDS:
                        egress_public_ip = latest.egress_public_ip
                        egress_country_code = latest.egress_country_code
                if egress_public_ip is None:
                    egress_public_ip, egress_country_code = _egress_geo_from_agent(agent)

                peer_stats = {p["public_key"]: p for p in agent.list_peers()}
                for peer in peers_repo.list_by_gateway(gateway.id):
                    stats = peer_stats.get(peer.public_key)
                    if stats:
                        last_hs = None
                        if stats.get("last_handshake"):
                            last_hs = datetime.fromisoformat(stats["last_handshake"])
                        metrics_repo.add_peer_metric(
                            peer.id,
                            last_hs,
                            stats.get("rx_bytes"),
                            stats.get("tx_bytes"),
                        )
            except Exception as exc:
                logger.warning("Agent metrics failed for %s: %s", gateway.name, exc)

            metrics_repo.add_gateway_metric(
                gateway.id,
                vm_status,
                tailscale_online,
                wg_online,
                exit_node_reachable,
                egress_public_ip=egress_public_ip,
                egress_country_code=egress_country_code,
            )
            count += 1

        session.commit()
    except Exception:
        session.rollback()
        raise

    return count
