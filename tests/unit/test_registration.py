"""Tests for mobile registration approval."""

import json
from unittest.mock import patch

import pytest

from orchestrator.headscale.client import (
    HeadscaleError,
    approve_registration_request,
    is_valid_registration_key,
)


def _registration_key() -> str:
    return "hskey-authreq-fj0dD26nCDZe-PIzCv4rddLK"


def test_approve_registration_request():
    key = _registration_key()
    register_json = json.dumps(
        {
            "id": 9,
            "name": "android-phone",
            "ip_addresses": ["100.64.0.9", "fd7a::9"],
        }
    )
    nodes_json = json.dumps([{"id": 9, "name": "android-phone"}])
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[register_json, "", "[]", nodes_json, ""],
    ) as run:
        node = approve_registration_request(key)
    assert node.node_id == 9
    assert node.hostname == "ex-000"
    assert node.tailscale_ip == "100.64.0.9"
    first = run.call_args_list[0].args[0]
    assert first[:2] == ["auth", "register"]
    assert first[3] == key
    assert run.call_args_list[1].args[0] == [
        "nodes",
        "approve-routes",
        "-i",
        "9",
        "-r",
        "",
    ]
    assert run.call_args_list[-1].args[0][:4] == ["nodes", "rename", "ex-000", "-i"]


def test_approve_registration_falls_back_to_nodes_register():
    key = _registration_key()
    register_json = json.dumps(
        {
            "id": 9,
            "name": "android-phone",
            "ip_addresses": ["100.64.0.9"],
        }
    )
    nodes_json = json.dumps([{"id": 9, "name": "android-phone"}])
    with patch(
        "orchestrator.headscale.client._run_headscale",
        side_effect=[
            HeadscaleError("unknown auth"),
            register_json,
            "",
            "[]",
            nodes_json,
            "",
        ],
    ) as run:
        node = approve_registration_request(key)
    assert node.hostname == "ex-000"
    assert run.call_args_list[1].args[0][:4] == ["nodes", "register", "-u", "gateways"]


def test_approve_registration_invalid_key_length():
    with pytest.raises(HeadscaleError, match="Registration ID must"):
        approve_registration_request("short")


def test_is_valid_registration_key_accepts_headscale_auth_id():
    assert is_valid_registration_key("hskey-authreq-fj0dD26nCDZe-PIzCv4rddLK")


def test_is_valid_registration_key_accepts_legacy_key():
    assert is_valid_registration_key("a" * 24)
