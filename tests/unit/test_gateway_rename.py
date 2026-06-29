"""Unit tests for gateway Headscale rename."""

from unittest.mock import MagicMock, patch

import pytest

from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.services.gateway_service import GatewayService


def _ready_gateway() -> Gateway:
    return Gateway(
        id=1,
        worker_id=1,
        name="gw-000",
        incus_instance="gw-gw-000",
        vm_ip="10.10.2.10",
        udp_port=52001,
        wg_subnet="10.64.4.0/24",
        wg_server_pubkey="pub",
        wg_server_privkey_enc="enc",
        exit_node_id="100.64.0.12",
        tailscale_auth_key_enc="enc",
        tailscale_hostname="gw-000",
        agent_token_hash="hash",
        agent_token_enc="enc",
        status=GatewayStatus.READY,
    )


def test_rename_tailscale_display_name_updates_db():
    gateway = _ready_gateway()
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_id.return_value = gateway
    repo.get_by_tailscale_hostname.return_value = None

    service = GatewayService(session)
    service._gateways = repo
    service._workers = MagicMock()
    service._jobs = MagicMock()
    service._settings = MagicMock()

    agent = MagicMock()
    with (
        patch.object(GatewayService, "_agent_client", return_value=agent),
        patch("orchestrator.crypto.decrypt_value", return_value="token"),
        patch(
            "orchestrator.services.gateway_service.find_gateway_headscale_node",
            return_value={"id": 12, "name": "gw-000"},
        ),
        patch("orchestrator.services.gateway_service.list_headscale_nodes_raw", return_value=[]),
        patch("orchestrator.services.gateway_service.rename_gateway_headscale_display_name"),
    ):
        result = service.rename_tailscale_display_name(1, "debug-paris")

    assert result.tailscale_hostname == "debug-paris"
    agent.set_tailscale_hostname.assert_called_once_with("debug-paris")
    session.commit.assert_called_once()


def test_rename_tailscale_display_name_rejects_duplicate():
    gateway = _ready_gateway()
    other = _ready_gateway()
    other.id = 2
    other.tailscale_hostname = "debug-paris"

    session = MagicMock()
    repo = MagicMock()
    repo.get_by_id.return_value = gateway
    repo.get_by_tailscale_hostname.return_value = other

    service = GatewayService(session)
    service._gateways = repo
    service._workers = MagicMock()
    service._jobs = MagicMock()
    service._settings = MagicMock()

    with pytest.raises(ValueError, match="already used"):
        service.rename_tailscale_display_name(1, "debug-paris")
