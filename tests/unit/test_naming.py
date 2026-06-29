"""Tests for sequential naming helpers."""

import pytest

from orchestrator.naming import (
    EXIT_NODE_PREFIX,
    GATEWAY_PREFIX,
    collect_exit_node_names,
    headscale_node_name,
    is_exit_node_name,
    is_gateway_name,
    next_sequential_name,
)


def test_next_sequential_name_skips_taken():
    taken = {"ex-000", "ex-001"}
    assert next_sequential_name(EXIT_NODE_PREFIX, taken) == "ex-002"


def test_next_gateway_name_format():
    assert next_sequential_name(GATEWAY_PREFIX, set()) == "gw-000"


def test_is_managed_name_patterns():
    assert is_gateway_name("gw-000")
    assert is_gateway_name("gw-042")
    assert not is_gateway_name("gw-00")
    assert is_exit_node_name("ex-000")
    assert not is_exit_node_name("shamunir")


def test_collect_exit_node_names():
    nodes = [
        {"name": "ex-000"},
        {"name": "phone"},
        {"hostname": "ex-001"},
        {"name": "shamunir", "given_name": "ex-002"},
    ]
    assert collect_exit_node_names(nodes) == {"ex-000", "ex-001", "ex-002"}


def test_headscale_node_name_prefers_given_name():
    assert headscale_node_name({"name": "shamunir", "given_name": "ex-000"}) == "ex-000"
    assert headscale_node_name({"name": "android-exit"}) == "android-exit"


def test_next_sequential_name_exhausted():
    taken = {f"ex-{index:03d}" for index in range(1000)}
    with pytest.raises(ValueError, match="No available names"):
        next_sequential_name(EXIT_NODE_PREFIX, taken)
