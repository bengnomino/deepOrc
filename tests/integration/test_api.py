"""Integration tests for orchestrator API."""

import pytest
from fastapi.testclient import TestClient

import orchestrator.models  # noqa: F401 — register all tables with Base.metadata
from orchestrator.config import get_settings
from orchestrator.main import create_app
from orchestrator.models.base import Base, get_engine, get_session_factory


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-32chars-minimum")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    app = create_app()
    with TestClient(app) as c:
        from orchestrator.models.base import get_session_factory as session_factory
        from orchestrator.services.worker_service import WorkerService

        session = session_factory()()
        try:
            from orchestrator.repositories.worker_repo import WorkerRepository

            ws = WorkerService(session)
            result = ws.register_worker(
                name="test-remote",
                display_name="Test Worker",
                public_ip="10.0.0.1",
                incus_url="https://worker.test:8443",
            )
            WorkerRepository(session).update_stats(
                result.worker,
                cpu_percent=1.0,
                memory_total_mb=1024,
                memory_used_mb=512,
                memory_percent=50.0,
                network_rx_bps=0.0,
                network_tx_bps=0.0,
            )
            session.commit()
        finally:
            session.close()
        yield c

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def test_health(client):
    response = client.get("/orchestrator/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_gateway_requires_auth(client):
    response = client.post(
        "/orchestrator/api/v1/gateways",
        json={
            "gateway_name": "gw-01",
        },
    )
    assert response.status_code == 401


def test_create_gateway_accepted(client, monkeypatch):
    from orchestrator.headscale.client import PreAuthKey

    monkeypatch.setattr(
        "orchestrator.services.gateway_service.create_gateway_preauth_key",
        lambda: PreAuthKey(key="test-preauth-key", user_id=1),
    )
    response = client.post(
        "/orchestrator/api/v1/gateways",
        headers={"X-API-Key": "test-key"},
        json={
            "gateway_name": "gw-01",
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert data["gateway"]["name"] == "gw-01"
    assert "job_id" in data


def test_create_gateway_auto_name(client, monkeypatch):
    from orchestrator.headscale.client import PreAuthKey

    monkeypatch.setattr(
        "orchestrator.services.gateway_service.create_gateway_preauth_key",
        lambda: PreAuthKey(key="test-preauth-key", user_id=1),
    )
    response = client.post(
        "/orchestrator/api/v1/gateways",
        headers={"X-API-Key": "test-key"},
        json={},
    )
    assert response.status_code == 202
    assert response.json()["gateway"]["name"] == "gw-000"


def test_list_gateways(client, monkeypatch):
    from orchestrator.headscale.client import PreAuthKey

    monkeypatch.setattr(
        "orchestrator.services.gateway_service.create_gateway_preauth_key",
        lambda: PreAuthKey(key="test-preauth-key", user_id=1),
    )
    client.post(
        "/orchestrator/api/v1/gateways",
        headers={"X-API-Key": "test-key"},
        json={
            "gateway_name": "gw-list",
        },
    )
    response = client.get("/orchestrator/api/v1/gateways", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    assert len(response.json()) >= 1
