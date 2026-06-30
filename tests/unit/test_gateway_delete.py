"""Unit tests for gateway deletion."""

from unittest.mock import MagicMock, patch

from orchestrator.models.gateway import Gateway, GatewayStatus
from orchestrator.services.gateway_service import EXIT_NODE_PENDING, GatewayService


def _ready_gateway() -> Gateway:
    return Gateway(
        id=17,
        worker_id=2,
        name="gw-000",
        incus_instance="gw-gw-000",
        vm_ip="10.10.2.10",
        udp_port=52001,
        wg_subnet="10.64.18.0/24",
        wg_server_pubkey="pub",
        wg_server_privkey_enc="enc",
        exit_node_id="100.64.0.7",
        tailscale_auth_key_enc="enc",
        tailscale_hostname="gw-000",
        agent_token_hash="hash",
        agent_token_enc="enc",
        status=GatewayStatus.DELETING,
    )


def test_execute_delete_gateway_removes_headscale_node():
    gateway = _ready_gateway()
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_id.return_value = gateway
    jobs = MagicMock()
    jobs.get_by_id.return_value = MagicMock()

    service = GatewayService(session)
    service._gateways = repo
    service._workers = MagicMock()
    service._jobs = jobs
    service._settings = MagicMock()

    worker = MagicMock()
    service._workers.get_worker.return_value = worker

    with (
        patch(
            "orchestrator.services.gateway_service.delete_gateway_headscale_node",
        ) as delete_node,
        patch("orchestrator.incus.IncusClient") as incus_cls,
        patch("orchestrator.incus.delete_gateway_vm"),
        patch("orchestrator.incus.release_vm_ip"),
        patch("orchestrator.incus.release_udp_port"),
    ):
        incus_cls.return_value.__enter__.return_value = MagicMock()
        service.execute_delete_gateway(17, job_id=99)

    delete_node.assert_called_once_with(
        tailscale_ip="100.64.0.7",
        hostnames=["gw-000", "gw-000"],
    )
    repo.delete.assert_called_once_with(gateway)
    session.commit.assert_called_once()


def test_execute_delete_gateway_skips_pending_exit_node_ip():
    gateway = _ready_gateway()
    gateway.exit_node_id = EXIT_NODE_PENDING

    session = MagicMock()
    repo = MagicMock()
    repo.get_by_id.return_value = gateway
    jobs = MagicMock()
    jobs.get_by_id.return_value = MagicMock()

    service = GatewayService(session)
    service._gateways = repo
    service._workers = MagicMock()
    service._jobs = jobs
    service._settings = MagicMock()
    service._workers.get_worker.return_value = MagicMock()

    with (
        patch(
            "orchestrator.services.gateway_service.delete_gateway_headscale_node",
        ) as delete_node,
        patch("orchestrator.incus.IncusClient") as incus_cls,
        patch("orchestrator.incus.delete_gateway_vm"),
        patch("orchestrator.incus.release_vm_ip"),
        patch("orchestrator.incus.release_udp_port"),
    ):
        incus_cls.return_value.__enter__.return_value = MagicMock()
        service.execute_delete_gateway(17, job_id=99)

    delete_node.assert_called_once_with(
        tailscale_ip=None,
        hostnames=["gw-000", "gw-000"],
    )
