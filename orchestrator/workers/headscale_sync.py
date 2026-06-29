"""Periodic Headscale maintenance (exit route auto-approval and naming)."""

import logging

from orchestrator.headscale.client import approve_exit_routes_for_tagged_nodes
from orchestrator.models.base import get_session_factory
from orchestrator.repositories.gateway_repo import GatewayRepository

logger = logging.getLogger(__name__)


def _gateway_names_from_db() -> set[str]:
    session = get_session_factory()()
    try:
        return {gateway.name for gateway in GatewayRepository(session).list_all()}
    finally:
        session.close()


def sync_headscale_exit_nodes(gateway_names: set[str] | None = None) -> int:
    names = gateway_names if gateway_names is not None else _gateway_names_from_db()
    try:
        routes = approve_exit_routes_for_tagged_nodes()
        if routes:
            logger.info("Auto-approved exit routes for %d node(s)", routes)
        return routes
    except Exception:
        logger.exception("Headscale exit node sync failed")
        return 0
