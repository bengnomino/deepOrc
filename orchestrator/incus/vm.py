"""Incus VM/container lifecycle management."""

from typing import Any

from orchestrator.config import get_settings
from orchestrator.incus.client import IncusClient
from orchestrator.incus.proxy import add_wg_proxy, set_static_ip
from orchestrator.incus.setup import run_script


def _incus_image_source(image: str) -> dict[str, Any]:
    if image.startswith("local:"):
        return {"type": "image", "alias": image.removeprefix("local:")}
    source: dict[str, Any] = {
        "type": "image",
        "alias": image.split(":")[-1] if ":" in image else image,
        "protocol": "simplestreams",
        "server": "https://images.linuxcontainers.org",
    }
    if image.startswith("images:"):
        source["mode"] = "pull"
        source["alias"] = image.removeprefix("images:")
    return source


def launch_gateway_vm(
    client: IncusClient,
    name: str,
    vm_ip: str,
    udp_port: int,
    user_data: str,
    setup_script: str | None = None,
    *,
    instance_target: str | None = None,
    listen_host: str | None = None,
    apply_wg_snat: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    source = _incus_image_source(settings.incus_image)

    config: dict[str, Any] = {
        "limits.cpu": settings.incus_vm_cpu,
        "limits.memory": settings.incus_vm_memory,
    }
    if settings.incus_provisioner == "cloud-init" and user_data:
        config["cloud-init.user-data"] = user_data
    if settings.incus_instance_type == "virtual-machine":
        config["security.secureboot"] = "false"

    import httpx

    try:
        client.get_instance(name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        client.create_instance(name, source, config)
    set_static_ip(client, name, vm_ip)
    add_wg_proxy(
        client,
        name,
        vm_ip,
        udp_port,
        listen_host=listen_host,
        apply_snat=apply_wg_snat,
    )
    state = client.get_instance_state(name)
    if state.get("status") != "Running":
        client.start_instance(name)
    if setup_script:
        run_script(instance_target or name, setup_script)
    return client.get_instance(name)


def delete_gateway_vm(client: IncusClient, name: str) -> None:
    try:
        client.stop_instance(name)
    except Exception:
        pass
    client.delete_instance(name)


def restart_gateway_vm(client: IncusClient, name: str) -> None:
    state = client.get_instance_state(name)
    if state.get("status") == "Running":
        client.stop_instance(name)
    client.start_instance(name)


def get_vm_status(client: IncusClient, name: str) -> str:
    state = client.get_instance_state(name)
    return state.get("status", "unknown")
