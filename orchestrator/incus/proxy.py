"""UDP proxy device management for WireGuard."""

import subprocess

from orchestrator.config import get_settings
from orchestrator.incus.client import IncusClient


def ensure_wg_snat_rule(vm_ip: str, udp_port: int, *, public_ip: str | None = None) -> None:
    """Same UDP port inside and outside the VM; MASQUERADE still rewrites the source port.

    Force replies to exit via the public WireGuard port so client handshakes complete.
    """
    settings = get_settings()
    public_ip = (public_ip or settings.host_public_ip).strip()
    dest = settings.ip_pool_network
    rule = [
        "-s",
        vm_ip,
        "-o",
        "eth0",
        "-p",
        "udp",
        "--sport",
        str(udp_port),
        "!",
        "-d",
        dest,
        "-j",
        "SNAT",
        "--to-source",
        f"{public_ip}:{udp_port}",
    ]
    check = subprocess.run(["iptables", "-t", "nat", "-C", "POSTROUTING", *rule], capture_output=True)
    if check.returncode != 0:
        subprocess.run(["iptables", "-t", "nat", "-I", "POSTROUTING", "1", *rule], check=True)


def add_wg_proxy(
    client: IncusClient,
    instance_name: str,
    vm_ip: str,
    udp_port: int,
    *,
    listen_host: str | None = None,
    apply_snat: bool = True,
) -> None:
    settings = get_settings()
    host = (listen_host or settings.host_public_ip).strip()
    client.add_device(
        instance_name,
        "wg-proxy",
        "proxy",
        {
            "listen": f"udp:{host}:{udp_port}",
            "connect": f"udp:{vm_ip}:{udp_port}",
            "nat": "true",
        },
    )
    if apply_snat:
        ensure_wg_snat_rule(vm_ip, udp_port, public_ip=host)


def set_static_ip(client: IncusClient, instance_name: str, vm_ip: str, network: str | None = None) -> None:
    settings = get_settings()
    net = network or settings.incus_network
    client.add_device(
        instance_name,
        "eth0",
        "nic",
        {
            "name": "eth0",
            "network": net,
            "ipv4.address": vm_ip,
        },
    )
