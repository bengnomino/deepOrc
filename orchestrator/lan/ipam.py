"""LAN (deeper / macvlan) IP allocation for peer groups."""

from __future__ import annotations

import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.gateway import Gateway
from orchestrator.models.peer_group import PeerGroup


def infer_lan_subnet(start_ip: str, prefix: int = 24) -> str:
    """Derive a CIDR from a host IP when the user only provides a start address."""
    host = ipaddress.ip_address(start_ip)
    network = ipaddress.ip_network(f"{host}/{prefix}", strict=False)
    return str(network)


def default_lan_gateway(subnet: str) -> str:
    network = ipaddress.ip_network(subnet)
    candidate = network.network_address + 254
    if candidate in network:
        return str(candidate)
    hosts = list(network.hosts())
    if not hosts:
        raise ValueError(f"No host addresses in subnet {subnet}")
    return str(hosts[-1])


def validate_lan_start_ip(subnet: str, start_ip: str) -> None:
    network = ipaddress.ip_network(subnet)
    host = ipaddress.ip_address(start_ip)
    if host not in network:
        raise ValueError(f"Start IP {start_ip} is not inside subnet {subnet}")


def macvlan_slot_from_ip(lan_ip: str) -> int:
    """Last octet is the macvlan index (e.g. 192.168.13.100 → 100)."""
    return int(str(ipaddress.ip_address(lan_ip)).split(".")[-1])


def allocate_lan_ip(session: Session, group: PeerGroup) -> str:
    """Next free LAN IP in the group, starting at lan_start_ip and walking up."""
    network = ipaddress.ip_network(group.lan_subnet)
    validate_lan_start_ip(group.lan_subnet, group.lan_start_ip)

    used: set[str] = set(
        session.scalars(
            select(Gateway.lan_ip).where(
                Gateway.peer_group_id == group.id,
                Gateway.lan_ip.is_not(None),
            )
        ).all()
    )

    current = ipaddress.ip_address(group.lan_start_ip)
    while current in network:
        ip = str(current)
        if ip not in used:
            return ip
        current += 1

    raise ValueError(f"No free LAN addresses left in group {group.name} ({group.lan_subnet})")


def remaining_lan_capacity(session: Session, group: PeerGroup) -> int:
    network = ipaddress.ip_network(group.lan_subnet)
    validate_lan_start_ip(group.lan_subnet, group.lan_start_ip)
    used = len(
        session.scalars(
            select(Gateway.id).where(Gateway.peer_group_id == group.id)
        ).all()
    )
    start = ipaddress.ip_address(group.lan_start_ip)
    total = sum(1 for host in network.hosts() if host >= start)
    return max(0, total - used)
