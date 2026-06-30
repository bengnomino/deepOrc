"""Tests for peer groups and deeper LAN IP allocation."""

import ipaddress

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from orchestrator.lan.ipam import (
    allocate_lan_ip,
    infer_lan_subnet,
    macvlan_slot_from_ip,
    remaining_lan_capacity,
    validate_lan_start_ip,
)
from orchestrator.models.base import Base
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.peer_group import PeerGroup
from orchestrator.models.worker import Worker, WorkerStatus
from orchestrator.services.peer_group_service import CreatePeerGroupRequest, PeerGroupService


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    worker = Worker(
        name="w1",
        display_name="Worker 1",
        public_ip="10.0.0.1",
        worker_token_hash="hash",
        port_pool_start=51001,
        port_pool_end=51010,
        ip_pool_network="10.10.0.0/16",
        ip_pool_start="10.10.1.10",
        status=WorkerStatus.ONLINE,
    )
    db.add(worker)
    db.commit()
    yield db
    db.close()


def test_infer_lan_subnet():
    assert infer_lan_subnet("192.168.13.100") == "192.168.13.0/24"


def test_macvlan_slot_from_ip():
    assert macvlan_slot_from_ip("192.168.13.100") == 100


def test_allocate_lan_ip_sequential(session: Session):
    worker = session.query(Worker).one()
    group = PeerGroup(
        name="g1",
        worker_id=worker.id,
        lan_subnet="192.168.13.0/24",
        lan_start_ip="192.168.13.100",
    )
    session.add(group)
    session.flush()

    assert allocate_lan_ip(session, group) == "192.168.13.100"
    session.add(
        Gateway(
            worker_id=worker.id,
            peer_group_id=group.id,
            lan_ip="192.168.13.100",
            name="gw-000",
            incus_instance="gw-gw-000",
            vm_ip="10.10.0.2",
            udp_port=51001,
            wg_subnet="10.64.1.0/24",
            wg_server_pubkey="pub",
            wg_server_privkey_enc="enc",
            exit_node_id="pending",
            tailscale_auth_key_enc="enc",
            tailscale_hostname="gw-000",
            agent_token_hash="hash",
            agent_token_enc="enc",
            status=GatewayStatus.PENDING,
        )
    )
    session.flush()
    assert allocate_lan_ip(session, group) == "192.168.13.101"


def test_validate_lan_start_ip_rejects_outside_subnet():
    with pytest.raises(ValueError, match="not inside"):
        validate_lan_start_ip("192.168.13.0/24", "192.168.14.100")


def test_remaining_lan_capacity(session: Session):
    worker = session.query(Worker).one()
    group = PeerGroup(
        name="g1",
        worker_id=worker.id,
        lan_subnet="192.168.13.0/28",
        lan_start_ip="192.168.13.10",
    )
    session.add(group)
    session.commit()
    # .10 through .14 usable hosts in /28 from start (excluding network/broadcast logic - hosts() in ipam)
    capacity = remaining_lan_capacity(session, group)
    assert capacity >= 1


def test_create_group_defaults_subnet(session: Session):
    worker = session.query(Worker).one()
    service = PeerGroupService(session)
    group = service.create_group(
        CreatePeerGroupRequest(
            name="deeper",
            worker_id=worker.id,
            lan_start_ip="192.168.13.100",
        )
    )
    assert group.lan_subnet == "192.168.13.0/24"
    assert group.lan_gateway == "192.168.13.254"


def test_rename_peer_group(session: Session):
    service = PeerGroupService(session)
    worker = session.query(Worker).one()
    group = service.create_group(
        CreatePeerGroupRequest(
            name="deeper-a",
            worker_id=worker.id,
            lan_start_ip="192.168.13.100",
        )
    )
    renamed = service.rename_group(group.id, "deeper-b")
    assert renamed.name == "deeper-b"
