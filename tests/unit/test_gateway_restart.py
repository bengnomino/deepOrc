"""Tests for gateway VM restart."""

from unittest.mock import MagicMock, patch

from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.models.worker import Worker
from orchestrator.services.gateway_service import GatewayService


def _ready_gateway() -> Gateway:
    return Gateway(
        id=17,
        name="gw-000",
        worker_id=2,
        incus_instance="gw-gw-000",
        status=GatewayStatus.READY,
        agent_token_enc="enc",
        vm_ip="10.10.2.26",
        udp_port=52017,
        wg_subnet="10.64.37.0/24",
        exit_node_id="100.64.0.8",
        tailscale_hostname="gw-000",
    )


def test_restart_gateway_stops_then_starts_vm():
    gateway = _ready_gateway()
    worker = Worker(id=2, name="worker3", public_ip="1.2.3.4", incus_remote="worker3")
    gateway.worker = worker

    session = MagicMock()
    service = GatewayService(session)
    service._gateways.get_by_id = MagicMock(return_value=gateway)

    with (
        patch("orchestrator.incus.IncusClient") as client_cls,
        patch("orchestrator.incus.restart_gateway_vm") as restart_vm,
        patch("orchestrator.incus.gateway_post_reboot.apply_gateway_post_reboot") as post_reboot,
    ):
        client = MagicMock()
        client.__enter__.return_value = client
        client_cls.return_value = client
        result = service.restart_gateway(17)

    assert result is gateway
    restart_vm.assert_called_once_with(client, "gw-gw-000")
    post_reboot.assert_called_once_with("worker3:gw-gw-000")


def test_restart_gateway_requires_ready_status():
    gateway = _ready_gateway()
    gateway.status = GatewayStatus.PROVISIONING
    session = MagicMock()
    service = GatewayService(session)
    service._gateways.get_by_id = MagicMock(return_value=gateway)

    try:
        service.restart_gateway(17)
        raised = False
    except ValueError as exc:
        raised = True
        assert "not ready" in str(exc).lower()

    assert raised
