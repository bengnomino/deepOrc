"""Unit tests for tailscale display name validation."""

import pytest

from orchestrator.naming import validate_tailscale_display_name


def test_validate_tailscale_display_name_accepts_simple():
    assert validate_tailscale_display_name("debug-exit-1") == "debug-exit-1"


def test_validate_tailscale_display_name_normalizes_case():
    assert validate_tailscale_display_name("Debug-Exit") == "debug-exit"


def test_validate_tailscale_display_name_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_tailscale_display_name("  ")


def test_validate_tailscale_display_name_rejects_invalid_chars():
    with pytest.raises(ValueError):
        validate_tailscale_display_name("bad name")
