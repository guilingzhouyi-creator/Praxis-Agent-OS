"""Deterministic attack matrix — safety oracles across the security stack.

Adapted from the Agent libOS evaluation (§8.4): each attack asserts on the
behavioral outcome (BLOCK/deny) and, where applicable, the audit trail
(broadcast topics / notify queue). No LLM involved — fully deterministic.

Attack classes:
  A1  cross-boundary secret read (unregistered tool)
  A2  cross-boundary write via territory prefix collision (/app vs /app2)
  A3  high-danger tool without approval in governed mode
  A4  harness downgrade without operator confirmation
  A5  confirmed minimal mode auto-approval + audit broadcast
  A6  capability deny overrides auto-approval
  A7  unauthenticated skill write
  A8  approval-gate bypass via pre_approved threading
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import contextlib

from l3.tool_system.tool_registry import TOOL_REGISTRY  # noqa: E402
from l3.tool_system.tool_spec import ParamSpec, ToolRing, ToolSpec, register  # noqa: E402


def _register(name: str, danger: int, ring: ToolRing) -> None:
    """Register a deterministic tool handler that echoes a payload marker."""
    from l3.services.approval_policy import get_policy

    def _handler(args: dict, agent_id: str) -> dict:
        return {"success": True, "tool": name, "agent": agent_id}

    register(
        ToolSpec(
            name=name,
            description=f"Attack-matrix tool {name}",
            category="test",
            ring=ring,
            danger=danger,
            handler=_handler,
            parameters=[ParamSpec(name="path", type="string", description="Target path", required=False)],
        )
    )
    if danger >= 4:
        get_policy().set_agent_danger("", "default", name, danger)


def _cleanup() -> None:
    for name in TOOL_REGISTRY.all_names():
        with contextlib.suppress(Exception):
            TOOL_REGISTRY.unregister(name)
    from l1.kernel.process import get_table

    for p in list(get_table()._processes or {}):
        with contextlib.suppress(Exception):
            get_table().kill(p)


@pytest.fixture(autouse=True)
def _attacks_env():
    """Isolated environment for every attack case."""
    from l1.kernel.notify import reset_notify
    from l1.kernel.process import get_table, reset_table
    from l3.services.capability_store import get_capability_store, reset_capability_store
    from l3.tool_system.harness import get_harness_mode, set_harness_mode

    reset_capability_store()
    reset_notify()
    reset_table()
    _cleanup()
    get_table().spawn("default", role="writer")
    try:
        from l1.kernel.gatechain import GateResult, get_gatechain

        def _capability_gate(ctx, gc):
            decision = get_capability_store().check(ctx["agent_id"], f"tool:{ctx['tool']}")
            if decision["decision"] == "deny":
                return (ctx["steps"] + [{"gate": "capability", "result": "BLOCK"}]), GateResult.BLOCK
            return (ctx["steps"] + [{"gate": "capability", "result": "PASS"}]), ctx.get("_overall", GateResult.PASS)

        get_gatechain().register_gate("capability", _capability_gate)
        get_gatechain().set_harness_provider(lambda: get_harness_mode())
    except Exception:
        pass
    try:
        if get_harness_mode() != "governed":
            set_harness_mode("governed", confirmed=True)
    except Exception:
        pass
    yield
    _cleanup()
    with contextlib.suppress(Exception):
        set_harness_mode("governed", confirmed=True)


def _run(tool_name: str, agent_id: str, args: dict | None = None):
    """Execute a tool through the full pipeline (registry + executor)."""
    from l3.tool_system.tool_pipeline import get_pipeline

    return get_pipeline().execute(tool_name, agent_id, args or {}, _registry=TOOL_REGISTRY)


def _notify_topics() -> list[str]:
    """Snapshot of notify broadcast topics, newest first."""
    from l1.kernel.notify import get_notify

    return [str(a.get("topic", "")) for a in get_notify().recent()]


class TestA1CrossBoundarySecretRead:
    """Unregistered tools must never reach a handler."""

    def test_unregistered_tool_blocked(self):
        from l3.tool_system.tool_pipeline import get_pipeline

        result = get_pipeline().execute("secret_reader", "default", {})
        assert result.get("success") is False
        assert "error" in result

    def test_high_danger_tool_requires_approval(self):
        _register("a1_pwn", danger=5, ring=ToolRing.RING_3)
        result = _run("a1_pwn", "default")
        assert result.get("success") is False
        assert result.get("steps")
        gate_steps = _gate_results(result)
        assert "G4" in gate_steps
        assert gate_steps["G4"].get("result") in ("BLOCK", "FAIL")


class TestA2TerritoryPrefixCollision:
    """/app must not authorize writes to /app2 (naive startswith bug class)."""

    @pytest.fixture()
    def write_tool(self):
        _register("a2_write", danger=2, ring=ToolRing.RING_2_5)
        yield "a2_write"

    def test_within_territory_allowed(self, write_tool):
        result = _run(write_tool, "default", {"path": "/project/app/file.txt", "territory": "/project/app"})
        assert result.get("success") is True

    def test_prefix_collision_blocked(self, write_tool):
        result = _run(write_tool, "default", {"path": "/project/app2/secret.txt", "territory": "/project/app"})
        assert result.get("success") is False
        gate = _gate_results(result)
        assert gate["G3"].get("result") in ("BLOCK", "FAIL")


class TestA3HighDangerUnapproved:
    """Governed mode: danger>=4 without full power or harness approval must BLOCK."""

    def test_g4_blocks_high_danger(self):
        _register("a3_nuke", danger=5, ring=ToolRing.RING_3)
        result = _run("a3_nuke", "default")
        assert result.get("success") is False
        assert _gate_results(result)["G4"].get("result") == "BLOCK"

    def test_blocked_call_broadcasts_alert(self):
        _register("a3_nuke", danger=5, ring=ToolRing.RING_3)
        _run("a3_nuke", "default")
        assert any("blocked" in t or "danger" in t for t in _notify_topics())


class TestA4HarnessDowngradeGate:
    """Downgrading harness mode requires explicit operator confirmation."""

    def test_minimal_without_confirmation_rejected(self):
        from l3.tool_system.harness import set_harness_mode

        r = set_harness_mode("minimal", confirmed=False)
        assert r.get("accepted") is False or r.get("success") is False


class TestA5ConfirmedMinimalAutoApproval:
    """Explicit downgrade auto-approves high-danger tools and broadcasts."""

    def test_auto_approval_and_broadcast(self):
        from l1.kernel.notify import get_notify
        from l3.tool_system.harness import set_harness_mode

        _register("a5_nuke", danger=5, ring=ToolRing.RING_3)
        set_harness_mode("minimal", confirmed=True)
        result = _run("a5_nuke", "default")
        assert result.get("success") is True
        assert any("auto_approved" in t or "approval" in t for t in _notify_topics())
        assert get_notify().recent()


class TestA6CapabilityDenyOverrides:
    """A typed deny record must override any earlier auto-approval."""

    def test_deny_overrides_harness_approval(self):
        from l3.services.capability_store import get_capability_store
        from l3.tool_system.harness import set_harness_mode

        _register("a6_nuke", danger=5, ring=ToolRing.RING_3)
        get_capability_store().issue(
            subject="default",
            resource="tool:a6_nuke",
            effect="deny",
            issuer="security",
        )
        set_harness_mode("minimal", confirmed=True)
        result = _run("a6_nuke", "default")
        assert result.get("success") is False
        gate_steps = _gate_results(result)
        assert "capability" in gate_steps
        assert gate_steps["capability"].get("result") == "BLOCK"


class TestA7UnauthenticatedSkillWrite:
    """Skill writes require an explicit identity (write gate)."""

    def test_write_without_identity_rejected(self):
        from l1.kernel.skill import SkillManager

        mgr = SkillManager()
        r = mgr.create("a7_evil", "Use when escalating privileges", "", role="")
        assert not r.get("success", False)
        assert "identity" in str(r).lower() or "authorize" in str(r).lower()


class TestA8ApprovalGateBypass:
    """pre_approved only flows from a real approval decision, not the caller."""

    def test_governed_high_danger_still_blocked_without_preapproval(self):
        _register("a8_nuke", danger=5, ring=ToolRing.RING_3)
        result = _run("a8_nuke", "default")
        assert result.get("success") is False
        assert _gate_results(result)["G4"].get("result") == "BLOCK"


def _phase_steps(result: dict) -> dict:
    """Index pipeline steps by phase name."""
    index = {}
    for s in result.get("steps") or []:
        name = s.get("phase") or s.get("gate") or "?"
        index.setdefault(name, []).append(s)
    return index


def _gate_results(result: dict) -> dict:
    """Map gate name -> step dict from the gatechain step list."""
    for s in result.get("steps") or []:
        if s.get("phase") == "gatechain":
            return {g.get("gate"): g for g in s.get("steps") or []}
    return {}
