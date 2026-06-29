"""Tests for static asset cache busting."""

from orchestrator.web.static_assets import get_static_asset_version, static_url


def test_static_url_includes_version_query():
    url = static_url("style.css", "/orchestrator")
    assert url.startswith("/orchestrator/static/style.css?v=")
    version = url.rsplit("=", 1)[-1]
    assert version == get_static_asset_version()
    assert len(version) == 12


def test_static_url_strips_leading_slash():
    assert static_url("/ui.js", "/orchestrator") == static_url("ui.js", "/orchestrator")
