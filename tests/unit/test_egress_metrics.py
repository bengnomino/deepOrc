"""Tests for egress refresh policy."""

from datetime import UTC, datetime, timedelta

from orchestrator.workers.egress_metrics import (
    EGRESS_REFRESH_SECONDS,
    EgressSnapshot,
    interface_state,
    merge_egress,
    should_refresh_egress,
)


def test_should_not_refresh_without_state_change():
    now = datetime.now(UTC)
    state = interface_state(True, True, True)
    snapshot = EgressSnapshot("1.2.3.4", "IT", now - timedelta(seconds=EGRESS_REFRESH_SECONDS + 1))
    assert (
        should_refresh_egress(
            previous_state=state,
            current_state=state,
            snapshot=snapshot,
            now=now,
        )
        is False
    )


def test_should_refresh_on_state_change_after_cooldown():
    now = datetime.now(UTC)
    previous = interface_state(False, True, True)
    current = interface_state(True, True, True)
    snapshot = EgressSnapshot("1.2.3.4", "IT", now - timedelta(seconds=EGRESS_REFRESH_SECONDS + 5))
    assert should_refresh_egress(
        previous_state=previous,
        current_state=current,
        snapshot=snapshot,
        now=now,
    )


def test_should_not_refresh_before_cooldown_even_on_state_change():
    now = datetime.now(UTC)
    previous = interface_state(False, True, True)
    current = interface_state(True, True, True)
    snapshot = EgressSnapshot("1.2.3.4", "IT", now - timedelta(seconds=30))
    assert (
        should_refresh_egress(
            previous_state=previous,
            current_state=current,
            snapshot=snapshot,
            now=now,
        )
        is False
    )


def test_merge_egress_keeps_previous_on_failed_refresh():
    now = datetime.now(UTC)
    previous = EgressSnapshot("1.2.3.4", "IT", now - timedelta(hours=1))
    merged = merge_egress(previous, EgressSnapshot(None, None, None), attempted=True, now=now)
    assert merged.public_ip == "1.2.3.4"
    assert merged.country_code == "IT"
    assert merged.updated_at == now


def test_should_retry_missing_egress_after_cooldown():
    now = datetime.now(UTC)
    state = interface_state(True, True, True)
    snapshot = EgressSnapshot(None, None, now - timedelta(seconds=EGRESS_REFRESH_SECONDS + 1))
    assert should_refresh_egress(
        previous_state=state,
        current_state=state,
        snapshot=snapshot,
        now=now,
    )
