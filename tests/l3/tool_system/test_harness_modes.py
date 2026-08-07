"""Harness mode tests — governed / semi / minimal pipeline gate matrix.

Process steps (approval / rate / pool) may be skipped in lighter modes;
the safety bottom line (constitution, gatechain, sandbox, reference-channel
recording) is never skipped in any mode.
"""

from __future__ import annotations

from l1.kernel.params.tool import (
    HARNESS_MODE_DEFAULT,
    HARNESS_MODE_GOVERNED,
    HARNESS_MODE_MINIMAL,
    HARNESS_MODE_SEMI,
    HARNESS_MODE_STEPS,
    HARNESS_MODES,
)
from l3.tool_system.tool_pipeline import ToolPipeline
from l3.tool_system.tool_spec import ToolSpec


def _spec() -> ToolSpec:
    return ToolSpec(
        name="read_file", description="r", category="", ring="RING_1", danger=0, parameters=[], handler=None
    )


def _run(pipeline: ToolPipeline, mode: str, monkeypatch) -> dict:
    """Run execute() with a forced harness mode."""
    import l3.tool_system.harness as harness
    import l3.tool_system.tool_pipeline as tp

    calls: dict[str, int] = {}

    def _cfg(key: str, default=None):
        if key == "record_steps":
            return True
        if key == "exec_token_budget":
            return 1000
        return default

    monkeypatch.setattr(tp, "get_tool_config", _cfg)
    monkeypatch.setattr(harness, "get_harness_mode", lambda: mode)
    monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

    class _Gate:
        def check(self, *a, **k):
            return {"allowed": True, "decision": "PASS", "steps": []}

    monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())

    # stub the rate scheduler + policy so we can observe whether they ran
    class _Rate:
        def check(self, agent_id, ring):
            calls["rate"] = calls.get("rate", 0) + 1
            return {"allowed": True}

    # pipeline binds _rate_scheduler at construction — replace the instance attr
    pipeline._rate_scheduler = _Rate()

    def _requires_approval(agent_id, tool_name):
        calls["approval"] = calls.get("approval", 0) + 1
        return False  # no real approval request → no wait timeout

    monkeypatch.setattr(tp, "_ToolPolicy", type("P", (), {"requires_approval": staticmethod(_requires_approval)}))

    result = pipeline.execute("read_file", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
    result["_calls"] = calls
    return result


class TestModeMatrix:
    def test_mode_constants(self):
        assert HARNESS_MODE_DEFAULT == HARNESS_MODE_GOVERNED
        assert set(HARNESS_MODES) == {HARNESS_MODE_GOVERNED, HARNESS_MODE_SEMI, HARNESS_MODE_MINIMAL}
        assert HARNESS_MODE_STEPS[HARNESS_MODE_GOVERNED] == ()
        assert "approval" in HARNESS_MODE_STEPS[HARNESS_MODE_SEMI]
        assert {"approval", "rate", "pool"} <= set(HARNESS_MODE_STEPS[HARNESS_MODE_MINIMAL])

    def test_governed_runs_all_process_steps(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_GOVERNED, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_GOVERNED
        assert r["_calls"].get("approval", 0) >= 1
        assert r["_calls"].get("rate", 0) >= 1

    def test_semi_skips_approval(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_SEMI, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_SEMI
        assert r["_calls"].get("approval", 0) == 0
        assert r["_calls"].get("rate", 0) >= 1  # rate stays in semi

    def test_minimal_skips_approval_and_rate(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, HARNESS_MODE_MINIMAL, monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_MINIMAL
        assert r["_calls"].get("approval", 0) == 0
        assert r["_calls"].get("rate", 0) == 0

    def test_invalid_mode_falls_back(self, monkeypatch):
        p = ToolPipeline()
        r = _run(p, "weird-mode", monkeypatch)
        assert r["harness_mode"] == HARNESS_MODE_GOVERNED


class TestBottomLine:
    def test_constitution_never_skipped_in_minimal(self, monkeypatch):
        """Even minimal mode blocks constitution violations."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

        class _Gate:
            def check(self, *a, **k):
                return {"allowed": True, "decision": "PASS", "steps": []}

        monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())
        monkeypatch.setattr(harness, "get_harness_mode", lambda: HARNESS_MODE_MINIMAL)

        # force minimal mode, constitution denies everything — bind the
        # instance attribute directly (bound at construction)
        class _Deny:
            def is_allowed(self, tool, agent, target="", territory=""):
                return {"allowed": False, "reason": "denied"}

        p.constitution = _Deny()
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        _spec_obj = _spec()
        r = p.execute("read_file", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert not r["success"]
        assert "constitution blocked" in r["error"]

    def test_gatechain_recording_never_skipped(self, monkeypatch):
        """Reference-channel causal recording stays on in minimal mode."""
        import l3.tool_system.harness as harness
        import l3.tool_system.tool_pipeline as tp

        p = ToolPipeline()
        monkeypatch.setattr(tp, "agent_can_access", lambda *a, **k: True)

        class _Gate:
            def check(self, *a, **k):
                return {"allowed": True, "decision": "PASS", "steps": []}

        monkeypatch.setattr(tp, "_get_gatechain", lambda: _Gate())
        monkeypatch.setattr(harness, "get_harness_mode", lambda: HARNESS_MODE_MINIMAL)
        monkeypatch.setattr(tp, "get_tool_config", lambda k, d=None: True if k == "record_steps" else d)
        recorded = []

        class _RC:
            def tool_call(self, *a, **k):
                recorded.append(a[0])

        monkeypatch.setattr(tp, "_get_rc", lambda: _RC())
        r = p.execute("read_file", "agent-http", _registry={}, _executor=lambda *a, **k: {"success": True})
        assert r.get("harness_mode") == HARNESS_MODE_MINIMAL
        assert "read_file" in recorded
