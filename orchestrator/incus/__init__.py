"""Incus integration module."""

from orchestrator.incus.client import IncusClient
from orchestrator.incus.network import allocate_udp_port, allocate_vm_ip, release_udp_port, release_vm_ip
from orchestrator.incus.proxy import add_wg_proxy, set_static_ip
from orchestrator.incus.vm import delete_gateway_vm, get_vm_status, launch_gateway_vm

__all__ = [
    "IncusClient",
    "add_wg_proxy",
    "allocate_udp_port",
    "allocate_vm_ip",
    "delete_gateway_vm",
    "get_vm_status",
    "launch_gateway_vm",
    "release_udp_port",
    "release_vm_ip",
    "set_static_ip",
]
