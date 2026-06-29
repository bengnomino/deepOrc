"""Incus instance naming for local vs remote workers."""

from orchestrator.models.worker import Worker


def incus_target(worker: Worker, instance_name: str) -> str:
    if worker.incus_remote:
        return f"{worker.incus_remote}:{instance_name}"
    return instance_name
