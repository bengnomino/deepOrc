"""Provisioning stage labels and helpers for UI progress."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from orchestrator.models.job import Job
from orchestrator.repositories.job_repo import JobRepository

STAGE_QUEUED = "queued"
STAGE_PREPARING = "preparing"
STAGE_VM_LAUNCH = "vm_launch"
STAGE_CLOUD_INIT = "cloud_init"
STAGE_AGENT_WAIT = "agent_wait"
STAGE_REGISTER = "register"
STAGE_PEER_SETUP = "peer_setup"
STAGE_DONE = "done"

STAGE_LABELS_IT: dict[str, str] = {
    STAGE_QUEUED: "In coda",
    STAGE_PREPARING: "Preparazione",
    STAGE_VM_LAUNCH: "Avvio VM",
    STAGE_CLOUD_INIT: "Cloud-init (config e servizi, ~30–60 s)",
    STAGE_AGENT_WAIT: "Attesa WireGuard e Tailscale online",
    STAGE_REGISTER: "Registrazione agent",
    STAGE_PEER_SETUP: "Creazione peer predefinito",
    STAGE_DONE: "Completato",
}


def set_provision_stage(session: Session, job_id: int, stage: str, *, touch: bool = True) -> None:
    JobRepository(session).update_stage(job_id, stage, touch=touch)
    session.commit()


def format_time_ago(when: datetime | None) -> str | None:
    if when is None:
        return None
    now = datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = now - when.astimezone(UTC)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 10:
        return "adesso"
    if seconds < 60:
        return f"{seconds} s fa"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min fa"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h fa"
    days = hours // 24
    return f"{days} g fa"


def format_provision_progress(job: Job | None) -> dict[str, str] | None:
    if not job or not job.stage:
        return None
    label = STAGE_LABELS_IT.get(job.stage, job.stage)
    ago = format_time_ago(job.stage_updated_at)
    if ago:
        return {"label": label, "ago": ago}
    return {"label": label, "ago": ""}
