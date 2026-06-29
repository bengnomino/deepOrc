"""Incus network and resource allocation."""

import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator.models.gateway import Gateway
from orchestrator.models.resources import IpAllocation, PortAllocation
from orchestrator.models.worker import Worker


def allocate_vm_ip(session: Session, worker: Worker) -> str:
    network = ipaddress.ip_network(worker.ip_pool_network)
    start = ipaddress.ip_address(worker.ip_pool_start)

    used_vm_ips = set(
        session.scalars(select(Gateway.vm_ip).where(Gateway.worker_id == worker.id)).all()
    )
    used_allocations = set(
        session.scalars(select(IpAllocation.address).where(IpAllocation.worker_id == worker.id)).all()
    )
    used = used_vm_ips | used_allocations

    host = int(start)
    end = int(network.broadcast_address) - 1
    while host <= end:
        candidate = str(ipaddress.ip_address(host))
        if candidate not in used:
            session.add(IpAllocation(worker_id=worker.id, address=candidate))
            session.flush()
            return candidate
        host += 1
    raise ValueError(f"No available VM IPs in pool for worker {worker.name}")


def allocate_udp_port(session: Session, worker: Worker, gateway_id: int | None = None) -> int:
    used_ports = set(
        session.scalars(select(Gateway.udp_port).where(Gateway.worker_id == worker.id)).all()
    )
    used_allocations = set(
        session.scalars(select(PortAllocation.udp_port).where(PortAllocation.worker_id == worker.id)).all()
    )
    used = used_ports | used_allocations

    for port in range(worker.port_pool_start, worker.port_pool_end + 1):
        if port not in used:
            session.add(PortAllocation(worker_id=worker.id, udp_port=port, gateway_id=gateway_id))
            session.flush()
            return port
    raise ValueError(f"No available UDP ports in pool for worker {worker.name}")


def release_vm_ip(session: Session, worker_id: int, ip: str) -> None:
    allocation = session.scalars(
        select(IpAllocation).where(IpAllocation.worker_id == worker_id, IpAllocation.address == ip)
    ).first()
    if allocation:
        session.delete(allocation)


def release_udp_port(session: Session, worker_id: int, port: int) -> None:
    allocation = session.scalars(
        select(PortAllocation).where(
            PortAllocation.worker_id == worker_id,
            PortAllocation.udp_port == port,
        )
    ).first()
    if allocation:
        session.delete(allocation)
