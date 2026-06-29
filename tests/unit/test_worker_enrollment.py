"""Worker enrollment naming."""

from datetime import UTC, datetime, timedelta

import pytest

import orchestrator.models  # noqa: F401
from orchestrator.headscale.client import PreAuthKey
from orchestrator.models.base import Base, get_engine, get_session_factory
from orchestrator.models.worker import Worker
from orchestrator.models.worker_enrollment import WorkerEnrollment
from orchestrator.services.worker_service import WorkerService


@pytest.fixture
def session(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-enrollment")
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
def mock_worker_preauth(monkeypatch):
    calls = {"n": 0}

    def fake_preauth():
        calls["n"] += 1
        return PreAuthKey(key=f"ts-key-{calls['n']}", user_id=1)

    monkeypatch.setattr(
        "orchestrator.services.worker_service.create_worker_preauth_key",
        fake_preauth,
    )
    return calls


def test_next_worker_name_increments(session):
    service = WorkerService(session)
    name, display = service._next_worker_identity()
    assert name == "worker1"
    assert display == "Worker 1"

    session.add(
        Worker(
            name="worker1",
            display_name="Worker 1",
            public_ip="1.2.3.4",
            worker_token_hash="x" * 64,
            port_pool_start=51001,
            port_pool_end=52000,
            ip_pool_network="10.10.0.0/16",
            ip_pool_start="10.10.1.10",
            incus_url="https://100.64.0.5:8443",
        )
    )
    session.commit()

    name2, display2 = service._next_worker_identity()
    assert name2 == "worker2"
    assert display2 == "Worker 2"


def test_create_enrollment_reuses_active_pending(session, mock_worker_preauth):
    service = WorkerService(session)
    first = service.create_enrollment()
    second = service.create_enrollment()

    assert first.name == second.name == "worker1"
    assert first.enroll_token == second.enroll_token
    assert first.tailscale_auth_key == second.tailscale_auth_key
    assert first.command == second.command
    assert mock_worker_preauth["n"] == 1


def test_create_enrollment_after_used_creates_new_worker(session, mock_worker_preauth):
    service = WorkerService(session)
    first = service.create_enrollment()

    enrollment = session.query(WorkerEnrollment).one()
    enrollment.used_at = datetime.now(UTC)
    session.commit()

    second = service.create_enrollment()
    assert second.name == "worker1"
    assert second.enroll_token != first.enroll_token
    assert mock_worker_preauth["n"] == 2
