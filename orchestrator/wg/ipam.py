"""WireGuard IP address management."""

import ipaddress
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.config import get_settings
from orchestrator.models.gateway import Gateway
from orchestrator.models.peer import Peer
from orchestrator.models.resources import IpAllocation


@dataclass(frozen=True)
class SubnetAllocation:
    subnet: str
    gateway_ip: str


def allocate_wg_subnet(session: Session, gateway_id: int) -> SubnetAllocation:
    """Allocate a /24 subnet for a gateway based on gateway id."""
    settings = get_settings()
    octet = (gateway_id % 253) + 1
    subnet = ipaddress.ip_network(f"{settings.wg_subnet_base}.{octet}.0/24")
    gateway_ip = str(subnet.network_address + 1)
    return SubnetAllocation(subnet=str(subnet), gateway_ip=gateway_ip)


def allocate_peer_ip(session: Session, gateway: Gateway) -> str:
    """Allocate next available peer IP from gateway's /24 subnet."""
    subnet = ipaddress.ip_network(gateway.wg_subnet)
    used: set[str] = set()

    peers = session.scalars(select(Peer).where(Peer.gateway_id == gateway.id)).all()
    used.update(p.allowed_ip.split("/")[0] for p in peers)

    allocations = session.scalars(select(IpAllocation)).all()
    for allocation in allocations:
        used.add(allocation.address)
        if allocation.gateway_id == gateway.id and allocation.peer_id is None:
            peer_ip = allocation.address
            if peer_ip not in {p.allowed_ip.split("/")[0] for p in peers}:
                return peer_ip

    # .1 is gateway, .2-.254 for peers
    for host in subnet.hosts():
        ip = str(host)
        if ip == str(subnet.network_address + 1):
            continue
        if ip not in used:
            allocation = IpAllocation(
                worker_id=gateway.worker_id,
                address=ip,
                gateway_id=gateway.id,
            )
            session.add(allocation)
            session.flush()
            return ip

    raise ValueError(f"No available peer IPs in subnet {gateway.wg_subnet}")


def release_peer_ip(session: Session, gateway_id: int, ip: str) -> None:
    allocation = session.scalars(
        select(IpAllocation).where(
            IpAllocation.gateway_id == gateway_id,
            IpAllocation.address == ip,
        )
    ).first()
    if allocation:
        session.delete(allocation)
