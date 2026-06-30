"""Periodic metrics collection from gateway agents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from orchestrator.crypto import decrypt_value
from orchestrator.headscale.client import PEER_ONLINE_HANDSHAKE_SECONDS
from orchestrator.incus import IncusClient, get_vm_status
from orchestrator.incus.target import incus_target
from orchestrator.models.gateway import GatewayStatus
from orchestrator.repositories.gateway_repo import GatewayRepository
from orchestrator.repositories.metrics_repo import MetricsRepository
from orchestrator.repositories.peer_repo import PeerRepository
from orchestrator.services.gateway_agent_client import GatewayAgentClient
from orchestrator.services.ip_geo import lookup_geo
from orchestrator.services.worker_service import WorkerService
from orchestrator.services.peer_service import PeerService
from orchestrator.workers.egress_metrics import (
    EgressSnapshot,
    egress_snapshot_from_metric,
    interface_state,
    merge_egress,
    should_refresh_egress,
)

logger = logging.getLogger(__name__)


def _wg_uplink_online(peers, peer_stats: dict[str, dict]) -> bool:
    if not peers:
        return False
    now = datetime.now(UTC)
    for peer in peers:
        if peer.suspended:
            continue
        stats = peer_stats.get(peer.public_key)
        if not stats or not stats.get("last_handshake"):
            continue
        last = datetime.fromisoformat(stats["last_handshake"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if (now - last).total_seconds() < PEER_ONLINE_HANDSHAKE_SECONDS:
            return True
    return False


def _egress_geo_from_agent(
    agent: GatewayAgentClient,
    snapshot: EgressSnapshot,
) -> EgressSnapshot:
    try:
        payload = agent.egress_public_ip()
        ip = (payload.get("ip") or "").strip()
        if not ip:
            return EgressSnapshot(None, None, None)
        if ip == snapshot.public_ip and snapshot.country_code:
            return EgressSnapshot(ip, snapshot.country_code, None)
        geo = lookup_geo(ip)
        if geo:
            return EgressSnapshot(geo.ip, geo.country_code, None)
        return EgressSnapshot(ip, None, None)
    except Exception as exc:
        logger.debug("egress geo lookup failed: %s", exc)
        return EgressSnapshot(None, None, None)


def _resolve_egress(
    agent: GatewayAgentClient,
    *,
    latest_metric,
    egress_metric,
    tailscale_online: bool | None,
    wg_online: bool | None,
    exit_node_reachable: bool | None,
    now: datetime,
) -> EgressSnapshot:
    snapshot = egress_snapshot_from_metric(egress_metric)
    if not snapshot.public_ip and latest_metric:
        snapshot = egress_snapshot_from_metric(latest_metric)

    previous_state = None
    if latest_metric is not None:
        previous_state = interface_state(
            latest_metric.tailscale_online,
            latest_metric.wg_online,
            latest_metric.exit_node_reachable,
        )
    current_state = interface_state(tailscale_online, wg_online, exit_node_reachable)

    if not should_refresh_egress(
        previous_state=previous_state,
        current_state=current_state,
        snapshot=snapshot,
        now=now,
    ):
        return snapshot

    refreshed = _egress_geo_from_agent(agent, snapshot)
    return merge_egress(snapshot, refreshed, attempted=True, now=now)


def collect_metrics(session: Session) -> int:
    gateways_repo = GatewayRepository(session)
    peers_repo = PeerRepository(session)
    metrics_repo = MetricsRepository(session)
    worker_service = WorkerService(session)
    count = 0
    now = datetime.now(UTC)

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

            latest = metrics_repo.latest_gateway_metric(gateway.id)
            egress_metric = metrics_repo.latest_gateway_metric_with_egress(gateway.id)
            snapshot = egress_snapshot_from_metric(egress_metric)
            if not snapshot.public_ip:
                snapshot = egress_snapshot_from_metric(latest)

            tailscale_online = latest.tailscale_online if latest else None
            wg_online = latest.wg_online if latest else None
            exit_node_reachable = latest.exit_node_reachable if latest else None

            try:
                token = decrypt_value(gateway.agent_token_enc)
                target = incus_target(worker, gateway.incus_instance)
                agent = GatewayAgentClient(gateway.vm_ip, token, incus_instance=target)
                health = agent.health()
                tailscale_online = health.get("tailscale_online")
                exit_node_reachable = health.get("exit_node_configured")

                peer_stats = {p["public_key"]: p for p in agent.list_peers()}
                db_peers = peers_repo.list_by_gateway(gateway.id)
                active_peers = [peer for peer in db_peers if not peer.suspended]
                if active_peers and any(
                    peer.public_key not in peer_stats for peer in active_peers
                ):
                    PeerService(session).resync_gateway_peers(gateway.id)
                    peer_stats = {p["public_key"]: p for p in agent.list_peers()}

                wg_online = _wg_uplink_online(active_peers, peer_stats)

                for peer in db_peers:
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

                snapshot = _resolve_egress(
                    agent,
                    latest_metric=latest,
                    egress_metric=egress_metric,
                    tailscale_online=tailscale_online,
                    wg_online=wg_online,
                    exit_node_reachable=exit_node_reachable,
                    now=now,
                )
            except Exception as exc:
                logger.warning("Agent metrics failed for %s: %s", gateway.name, exc)

            metrics_repo.add_gateway_metric(
                gateway.id,
                vm_status,
                tailscale_online,
                wg_online,
                exit_node_reachable,
                egress_public_ip=snapshot.public_ip,
                egress_country_code=snapshot.country_code,
                egress_updated_at=snapshot.updated_at,
            )
            count += 1

        session.commit()
    except Exception:
        session.rollback()
        raise

    return count
