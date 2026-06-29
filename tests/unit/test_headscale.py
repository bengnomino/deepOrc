"""Unit tests for Headscale client."""

import json
from unittest.mock import patch

from orchestrator.headscale.client import (
    approve_exit_routes_for_tagged_nodes,
    create_exit_node_preauth_key,
    create_gateway_preauth_key,
    get_user_id,
    list_exit_nodes,
    sync_exit_node_names,
)


def test_run_headscale_strips_conflicting_env(monkeypatch):
    monkeypatch.setenv("HEADSCALE_CLI", "headscale")
    monkeypatch.setenv("HEADSCALE_USER", "gateways")
    monkeypatch.setenv("HEADSCALE_URL", "https://example.com")
    with patch("orchestrator.headscale.client.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "[]"
        from orchestrator.headscale.client import _run_headscale

        _run_headscale(["nodes", "list", "-o", "json"])
    env = run.call_args.kwargs["env"]
    assert "HEADSCALE_CLI" not in env
    assert "HEADSCALE_USER" not in env
    assert "HEADSCALE_URL" not in env
    assert run.call_args.args[0][:4] == ["headscale", "-c", "/etc/headscale/config.yaml", "nodes"]


def test_get_user_id():
    users = json.dumps([{"id": 1, "name": "gateways"}])
    with patch("orchestrator.headscale.client._run_headscale", return_value=users):
        assert get_user_id("gateways") == 1


def test_create_gateway_preauth_key():
    users = json.dumps([{"id": 1, "name": "gateways"}])
    key_json = json.dumps({"key": "tskey-auth-test"})
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[users, key_json],
    ) as run:
        result = create_gateway_preauth_key()
    assert result.key == "tskey-auth-test"
    assert result.user_id == 1
    assert "--tags" in run.call_args_list[1].args[0]


def test_create_exit_node_preauth_key():
    users = json.dumps([{"id": 1, "name": "gateways"}])
    key_json = json.dumps({"key": "hskey-exit-test", "acl_tags": ["tag:exit"]})
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[users, key_json],
    ) as run:
        result = create_exit_node_preauth_key()
    assert result.key == "hskey-exit-test"
    assert "--tags" in run.call_args_list[1].args[0]
    assert "tag:exit" in run.call_args_list[1].args[0]


def test_list_exit_nodes_by_tag():
    nodes = json.dumps(
        [
            {
                "id": 2,
                "name": "android-exit",
                "ipAddresses": ["100.64.0.5"],
                "connected": True,
                "tags": ["tag:exit"],
            }
        ]
    )
    with patch("orchestrator.headscale.client._run_headscale", return_value=nodes):
        result = list_exit_nodes()
    assert len(result) == 1
    assert result[0].exit_tagged is True
    assert result[0].exit_advertised is False


def test_approve_exit_routes_for_tagged_nodes():
    nodes = json.dumps(
        [
            {
                "id": 5,
                "tags": ["tag:exit"],
                "availableRoutes": ["0.0.0.0/0", "::/0"],
                "approvedRoutes": [],
            }
        ]
    )
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[nodes, ""],
    ) as run:
        count = approve_exit_routes_for_tagged_nodes()
    assert count == 1
    assert "approve-routes" in run.call_args_list[1].args[0]


def test_list_exit_nodes_with_routes():
    nodes = json.dumps(
        [
            {
                "id": 2,
                "name": "android-exit",
                "ipAddresses": ["100.64.0.5", "fd7a:115c:a1e0::5"],
                "connected": True,
                "approvedRoutes": ["0.0.0.0/0", "::/0"],
            },
            {
                "id": 3,
                "name": "gw-00",
                "ipAddresses": ["100.64.0.10"],
                "connected": True,
            },
        ]
    )
    with patch("orchestrator.headscale.client._run_headscale", return_value=nodes):
        result = list_exit_nodes()
    assert len(result) == 1
    assert result[0].hostname == "android-exit"
    assert result[0].tailscale_ip == "100.64.0.5"
    assert result[0].online is True
    assert result[0].exit_approved is True


def test_list_exit_nodes_uses_given_name():
    nodes = json.dumps(
        [
            {
                "id": 2,
                "name": "shamunir",
                "given_name": "ex-000",
                "ipAddresses": ["100.64.0.2"],
                "connected": True,
                "tags": ["tag:exit"],
                "approvedRoutes": ["0.0.0.0/0"],
            }
        ]
    )
    with patch("orchestrator.headscale.client._run_headscale", return_value=nodes):
        result = list_exit_nodes()
    assert len(result) == 1
    assert result[0].hostname == "ex-000"


def test_sync_exit_node_names():
    nodes = json.dumps(
        [
            {
                "id": 2,
                "name": "android-phone",
                "tags": ["tag:exit"],
            },
            {
                "id": 3,
                "name": "ex-000",
                "tags": ["tag:exit"],
            },
            {
                "id": 4,
                "name": "gw-000",
            },
        ]
    )
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[nodes, ""],
    ) as run:
        count = sync_exit_node_names({"gw-000"})
    assert count == 1
    assert run.call_args_list[1].args[0] == [
        "nodes",
        "rename",
        "ex-001",
        "-i",
        "2",
    ]
