"""Harness runtime state tests — switchable via API / L2 Shell.

Covers the override resolution chain (runtime → config → default),
the minimal-mode risk confirmation gate, and the API/L2 handler glue.
"""

from __future__ import annotations

import pytest

from l1.kernel.params.tool import (
    HARNESS_MODE_GOVERNED,
    HARNESS_MODE_MINIMAL,
    HARNESS_MODE_SEMI,
    HARNESS_MODES,
)


@pytest.fixture(autouse=True)
def _clean_state():
    import l3.tool_system.harness as h

    with h._lock:
        old = dict(h._state)
        h._state["mode"] = None
        h._state["source"] = "config"
    yield
    with h._lock:
        h._state.clear()
        h._state.update(old)


class TestHarnessState:
    def test_default_falls_back_to_config(self, monkeypatch):
        import l3.tool_system.harness as h

        monkeypatch.setattr("l3.tool_system.harness.get_tool_config", lambda k, d=None: "semi")
        assert h.get_harness_mode() == HARNESS_MODE_SEMI

    def test_runtime_override_wins(self, monkeypatch):
        import l3.tool_system.harness as h

        monkeypatch.setattr("l3.tool_system.harness.get_tool_config", lambda k, d=None: HARNESS_MODE_GOVERNED)
        assert h.set_harness_mode(HARNESS_MODE_SEMI, confirmed=False)["success"]
        assert h.get_harness_mode() == HARNESS_MODE_SEMI

    def test_invalid_mode_rejected(self):
        import l3.tool_system.harness as h

        r = h.set_harness_mode("quantum", confirmed=True)
        assert not r["success"]
        assert r["modes"] == list(HARNESS_MODES)

    def test_minimal_requires_confirmation(self):
        import l3.tool_system.harness as h

        r = h.set_harness_mode(HARNESS_MODE_MINIMAL, confirmed=False)
        assert not r["success"]
        assert "confirm" in r["error"]
        r2 = h.set_harness_mode(HARNESS_MODE_MINIMAL, confirmed=True, source="shell")
        assert r2["success"]
        assert "user-assumed" in r2["note"]
        assert h.get_harness_mode() == HARNESS_MODE_MINIMAL

    def test_reset_restores_config_source(self, monkeypatch):
        import l3.tool_system.harness as h

        monkeypatch.setattr("l3.tool_system.harness.get_tool_config", lambda k, d=None: HARNESS_MODE_GOVERNED)
        h.set_harness_mode(HARNESS_MODE_SEMI)
        assert h.reset_harness_mode()["mode"] == HARNESS_MODE_GOVERNED

    def test_bottom_line_present_in_status(self):
        import l3.tool_system.harness as h

        s = h.harness_status()
        assert "constitution" in s["bottom_line"]
        assert set(s["modes"]) == set(HARNESS_MODES)


class TestApiGlue:
    def test_get_endpoint_registered(self):
        from l4.api.api_routes import API_ROUTES

        paths = {m + " " + p for m, p, _, _ in API_ROUTES}
        assert "GET /api/v2/harness/mode" in paths
        assert "POST /api/v2/harness/mode" in paths

    def test_handler_get(self):
        from l4.api_handlers import ApiHandlers

        h = ApiHandlers()
        r = h._harness_mode_get()
        assert r["mode"] in HARNESS_MODES
        assert "bottom_line" in r

    def test_handler_set_minimal_needs_confirm(self):
        from l4.api_handlers import ApiHandlers

        h = ApiHandlers()
        assert not h._harness_mode_set({"mode": "minimal"})["success"]
        r = h._harness_mode_set({"mode": "minimal", "confirm_risk": True})
        assert r["success"] and r["mode"] == HARNESS_MODE_MINIMAL


class TestL2Glue:
    def test_command_registered(self):
        import l2.l2_shell.commands  # noqa: F401  (triggers auto-registration)
        from l1.kernel.commands import get_command

        c = get_command("harness")
        assert c is not None
        assert "minimal" in c.get("help", "")

    def test_command_show(self):
        from l2.l2_shell.commands.harness import _cmd_harness

        r = _cmd_harness([])
        assert r["success"] and "mode" in r

    def test_command_switch_requires_confirm_for_minimal(self):
        from l2.l2_shell.commands.harness import _cmd_harness

        assert not _cmd_harness(["minimal"])["success"]
        r = _cmd_harness(["minimal", "--confirm"])
        assert r["success"] and r["mode"] == HARNESS_MODE_MINIMAL

    def test_command_reset(self, monkeypatch):
        from l2.l2_shell.commands.harness import _cmd_harness

        monkeypatch.setattr("l3.tool_system.harness.get_tool_config", lambda k, d=None: HARNESS_MODE_GOVERNED)
        _cmd_harness(["semi", "--confirm"])
        r = _cmd_harness(["reset"])
        assert r["success"] and r["mode"] == HARNESS_MODE_GOVERNED
