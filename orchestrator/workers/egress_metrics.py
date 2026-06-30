"""Egress public IP / geo refresh policy for gateway metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

EGRESS_REFRESH_SECONDS = 300


@dataclass(frozen=True)
class InterfaceState:
    tailscale_online: bool | None
    wg_online: bool | None
    exit_node_reachable: bool | None


@dataclass(frozen=True)
class EgressSnapshot:
    public_ip: str | None
    country_code: str | None
    updated_at: datetime | None


def interface_state(
    tailscale_online: bool | None,
    wg_online: bool | None,
    exit_node_reachable: bool | None,
) -> InterfaceState:
    return InterfaceState(tailscale_online, wg_online, exit_node_reachable)


def egress_snapshot_from_metric(metric) -> EgressSnapshot:
    if metric is None or not metric.egress_public_ip:
        return EgressSnapshot(None, None, None)
    return EgressSnapshot(
        public_ip=metric.egress_public_ip,
        country_code=metric.egress_country_code,
        updated_at=getattr(metric, "egress_updated_at", None) or metric.polled_at,
    )


def interface_state_changed(previous: InterfaceState | None, current: InterfaceState) -> bool:
    if previous is None:
        return True
    return previous != current


def pathways_ready(state: InterfaceState) -> bool:
    return state.tailscale_online is True and state.wg_online is True


def should_refresh_egress(
    *,
    previous_state: InterfaceState | None,
    current_state: InterfaceState,
    snapshot: EgressSnapshot,
    now: datetime,
) -> bool:
    """Refresh only external egress lookups (public IP + geo), at most every 5 minutes."""
    if not pathways_ready(current_state):
        return False
    if snapshot.updated_at is None:
        return True
    age = (now - snapshot.updated_at).total_seconds()
    if age < EGRESS_REFRESH_SECONDS:
        return False
    if not snapshot.public_ip:
        return True
    return interface_state_changed(previous_state, current_state)


def merge_egress(
    snapshot: EgressSnapshot,
    refreshed: EgressSnapshot | None,
    *,
    attempted: bool = False,
    now: datetime,
) -> EgressSnapshot:
    if refreshed and refreshed.public_ip:
        return EgressSnapshot(
            public_ip=refreshed.public_ip,
            country_code=refreshed.country_code or snapshot.country_code,
            updated_at=now,
        )
    if attempted:
        return EgressSnapshot(snapshot.public_ip, snapshot.country_code, now)
    return snapshot
