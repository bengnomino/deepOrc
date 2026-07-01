from types import SimpleNamespace

from orchestrator.web import routes


def test_normalise_log_unit_rejects_unknown_values():
    assert routes._normalise_log_unit("headscale") == "headscale"
    assert routes._normalise_log_unit("anything-else") == "orchestrator"


def test_normalise_log_limit_rejects_unknown_values():
    assert routes._normalise_log_limit("100") == 100
    assert routes._normalise_log_limit("not-a-number") == 200
    assert routes._normalise_log_limit(999) == 200


def test_read_journal_lines_uses_known_unit(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="one\ntwo\n", stderr="")

    monkeypatch.setattr(routes.subprocess, "run", fake_run)

    lines, error = routes._read_journal_lines("orchestrator", 100)

    assert error is None
    assert lines == ["one", "two"]
    command, kwargs = calls[0]
    assert command[:4] == ["journalctl", "-u", "orchestrator.service", "-n"]
    assert "anything-else" not in command
    assert kwargs["timeout"] == 8


def test_read_journal_lines_all_services_has_no_unit_filter(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(routes.subprocess, "run", fake_run)

    lines, error = routes._read_journal_lines("all", 200)

    assert lines == []
    assert error is None
    assert "-u" not in calls[0]


def test_base_nav_links_logs_page():
    content = (routes.WEB_DIR / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'href="/orchestrator/ui/logs"' in content


def test_logs_layout_keeps_page_fixed_and_log_panel_scrollable():
    css = (routes.WEB_DIR / "static" / "style.css").read_text(encoding="utf-8")
    assert ".logs-container" in css
    assert "overflow: hidden;" in css
    assert "min-height: 300px;" in css
    assert ".log-output" in css
    assert "overflow: auto;" in css
