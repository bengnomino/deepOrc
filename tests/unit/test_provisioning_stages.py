from datetime import UTC, datetime, timedelta

from orchestrator.workers.provisioning_stages import (
    STAGE_LABELS,
    STAGE_VM_LAUNCH,
    format_provision_progress,
    format_time_ago,
)


def test_format_time_ago():
    assert format_time_ago(datetime.now(UTC)) == "just now"
    assert format_time_ago(datetime.now(UTC) - timedelta(seconds=30)) == "30s ago"
    assert format_time_ago(datetime.now(UTC) - timedelta(minutes=5)) == "5m ago"


def test_format_provision_progress():
    class Job:
        stage = STAGE_VM_LAUNCH
        stage_updated_at = datetime.now(UTC) - timedelta(minutes=2)

    progress = format_provision_progress(Job())
    assert progress is not None
    assert progress["label"] == STAGE_LABELS[STAGE_VM_LAUNCH]
    assert progress["ago"] == "2m ago"
