"""WireGuard IPAM tests."""

import pytest
from sqlalchemy import select

import orchestrator.models  # noqa: F401
from orchestrator.models.base import Base, get_engine, get_session_factory
from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.resources import IpAllocation
from orchestrator.models.worker import Worker
from orchestrator.wg.ipam import allocate_peer_ip


@pytest.fixture
def session(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from orchestrator.config import get_settings

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    db = get_session_factory()()
    yield db
    db.close()


@pytest.fixture
def worker(session):
    row = Worker(
        name="worker1",
        display_name="Worker 1",
        public_ip="1.2.3.4",
        worker_token_hash="x" * 64,
        port_pool_start=51001,
        port_pool_end=52000,
        ip_pool_network="10.10.0.0/16",
        ip_pool_start="10.10.1.10",
    )
    session.add(row)
    session.flush()
    return row


def test_allocate_peer_ip_sets_worker_id(session, worker):
    gateway = Gateway(
        worker_id=worker.id,
        name="gw-test",
        incus_instance="gw-gw-test",
        vm_ip="10.10.1.10",
        udp_port=51001,
        wg_subnet="10.64.99.0/24",
        wg_server_pubkey="pub",
        wg_server_privkey_enc="enc",
        exit_node_id="pending",
        tailscale_auth_key_enc="enc",
        tailscale_hostname="gw-test",
        agent_token_hash="hash",
        agent_token_enc="enc",
        status=GatewayStatus.READY,
    )
    session.add(gateway)
    session.flush()

    peer_ip = allocate_peer_ip(session, gateway)

    assert peer_ip == "10.64.99.2"
    allocation = session.scalars(select(IpAllocation).where(IpAllocation.address == peer_ip)).one()
    assert allocation.worker_id == worker.id
    assert allocation.gateway_id == gateway.id
