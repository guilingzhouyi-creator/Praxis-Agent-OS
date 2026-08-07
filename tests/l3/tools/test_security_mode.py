"""Security posture mode tests — productive vs security-test dual-axis gating.

Covers:
  - security_mode state machine: 3-level resolve + posture combination
  - detection-bypass: security-test requires confirm_risk (warning + event)
  - constitution §9.2: offensive-skill use gated by full_power
  - GateChain G4: high-danger tool escalation skipped under full_power
  - L3A cardwrite: offensive warrant rejected without attack posture
  - Cell.activate_attack_team: peer agents + skill bindings from config
"""

from __future__ import annotations

import contextlib

import pytest


def _reset():
    from l1.kernel.constitution import reset_constitution
    from l1.kernel.gatechain import reset_gatechain
    from l1.kernel.process import get_table
    from l1.kernel.skill import reset_skill_manager

    reset_constitution()
    reset_gatechain()
    reset_skill_manager()
    with contextlib.suppress(Exception):
        get_table()._pcbs.clear()


@pytest.fixture(autouse=True)
def _posture_env():
    # Force productive posture BEFORE each test too — other test files (e.g.
    # test_skill_posture.py catalog tests) may have left security-test in the
    # module-global state, and this file's assertions assume a clean slate.
    from l3.tool_system.security_mode import set_security_mode

    with contextlib.suppress(Exception):
        set_security_mode("productive", confirmed=True)
    _reset()
    yield
    with contextlib.suppress(Exception):
        set_security_mode("productive", confirmed=True)
    _reset()


def _mk_offensive_skill(name: str = "rev-x"):
    from l1.kernel.skill import get_skill_manager

    sm = get_skill_manager()
    sm.create(name=name, description="d", prompt="p", tags=["evolved"], posture="offensive", internal=True)
    return name


def _wire_provider():
    from l1.kernel.constitution import set_posture_provider
    from l1.kernel.gatechain import get_gatechain
    from l3.tool_system.security_mode import get_posture

    set_posture_provider(get_posture)
    get_gatechain().set_posture_provider(get_posture)


class TestSecurityModeStateMachine:
    def test_default_productive(self):
        from l3.tool_system.security_mode import get_posture, get_security_mode

        assert get_security_mode() == "productive"
        p = get_posture()
        assert p["classification"] == "productive"
        assert p["full_power"] is False

    def test_switch_requires_confirm(self):
        from l3.tool_system.security_mode import set_security_mode

        r = set_security_mode("security-test", confirmed=False)
        assert not r["success"]
        assert r["warning"]["code"] == "SECURITY_TEST_CONFIRM_REQUIRED"

    def test_confirm_enables_full_power(self):
        from l3.tool_system.security_mode import get_posture, set_security_mode

        r = set_security_mode("security-test", confirmed=True)
        assert r["success"]
        assert get_posture()["classification"] == "security-test"
        assert get_posture()["full_power"] is True

    def test_back_to_productive(self):
        from l3.tool_system.security_mode import get_posture, set_security_mode

        set_security_mode("security-test", confirmed=True)
        set_security_mode("productive", confirmed=True)
        assert get_posture()["classification"] == "productive"
        assert get_posture()["full_power"] is False


class TestConstitutionPostureGate:
    def test_offensive_blocked_without_full_power(self):
        from l1.kernel.constitution import get_constitution
        from l3.tool_system.security_mode import set_security_mode

        _mk_offensive_skill("rev-a")
        _wire_provider()
        cc = get_constitution()
        set_security_mode("productive", confirmed=True)
        assert not cc.is_allowed("skill.use", "agent-x", target="rev-a").get("allowed")

    def test_offensive_allowed_with_full_power(self):
        from l1.kernel.constitution import get_constitution
        from l3.tool_system.security_mode import set_security_mode

        _mk_offensive_skill("rev-b")
        _wire_provider()
        cc = get_constitution()
        set_security_mode("security-test", confirmed=True)
        assert cc.is_allowed("skill.use", "agent-x", target="rev-b").get("allowed")

    def test_no_provider_backward_compatible(self):
        from l1.kernel.constitution import get_constitution, set_posture_provider

        _mk_offensive_skill("rev-c")
        # Provider is a module-level global — clear it explicitly so earlier
        # tests that wired it cannot leak into this backward-compat case.
        set_posture_provider(None)
        cc = get_constitution()  # provider not wired
        assert cc.is_allowed("skill.use", "agent-x", target="rev-c").get("allowed")


class TestGateChainPosture:
    def _g4(self, gc):
        from l1.kernel.gatechain import GATECHAIN_ESCALATION_DANGER

        r = gc.check("pwn_tool", "agent-x", danger=GATECHAIN_ESCALATION_DANGER + 1)
        return [s["result"] for s in r["steps"] if s["gate"] == "G4"]

    def test_g4_warns_without_full_power(self):
        from l1.kernel.gatechain import get_gatechain
        from l1.kernel.process import get_table
        from l3.tool_system.security_mode import set_security_mode

        get_table().spawn("agent-x", role="writer")
        gc = get_gatechain()
        gc.register_tools(["pwn_tool"])
        gc.set_territories({})
        _wire_provider()
        set_security_mode("productive", confirmed=True)
        assert self._g4(gc) == ["WARN"]

    def test_g4_passes_with_full_power(self):
        from l1.kernel.gatechain import get_gatechain
        from l1.kernel.process import get_table
        from l3.tool_system.security_mode import set_security_mode

        get_table().spawn("agent-x", role="writer")
        gc = get_gatechain()
        gc.register_tools(["pwn_tool"])
        gc.set_territories({})
        _wire_provider()
        set_security_mode("security-test", confirmed=True)
        assert self._g4(gc) == ["PASS"]


class TestCardwriteWarrant:
    def _card(self, nature: str = "offensive"):
        from l3.cell.peers.l3a.helpers import cardwrite_handler

        return cardwrite_handler({"nature": nature, "title": "t", "intent": "t", "phases": []}, "l3a")

    def test_offensive_warrant_denied_in_productive(self):
        from l3.tool_system.security_mode import set_security_mode

        set_security_mode("productive", confirmed=True)
        r = self._card("offensive")
        assert not r["success"]
        assert r["warning"]["code"] == "OFFENSIVE_WARRANT_DENIED"

    def test_offensive_warrant_issued_with_full_power(self):
        from l3.tool_system.security_mode import set_security_mode

        set_security_mode("security-test", confirmed=True)
        r = self._card("offensive")
        assert r["success"]

    def test_execution_card_always_allowed(self):
        from l3.tool_system.security_mode import set_security_mode

        set_security_mode("productive", confirmed=True)
        assert self._card("execution")["success"]


class TestCellAttackTeam:
    def test_activate_attack_team(self):
        from l1.kernel.skill import get_skill_manager
        from l3.cell import Cell, reset_cells
        from l3.config.settings_center import get_center, reset_center

        reset_cells()
        reset_center()
        sm = get_skill_manager()
        sm.create(name="recon-methodology", description="d", prompt="r", posture="offensive", internal=True)
        get_center().set_l2("team.attack.domains", {"recon": ["recon-methodology"]})
        cell = Cell(cell_id="cell-1")
        r = cell.activate_attack_team()
        assert r["success"]
        assert "agent-recon" in r["created"]
        assert r["bound"] == 1
        assert "recon-methodology" in sm.skills_for_cell("cell-1")

    def test_empty_domains_no_team(self):
        from l3.cell import Cell, reset_cells
        from l3.config.settings_center import reset_center

        reset_cells()
        reset_center()
        cell = Cell(cell_id="cell-1")
        r = cell.activate_attack_team()
        assert r["success"]
        assert r["created"] == []
        assert r["domains"] == []


class TestBypassNotificationApi:
    """Bypass-detection warnings must be queryable via the API (frontend pull)."""

    def test_warning_recorded_and_queryable(self):
        from l3.tool_system.security_mode import security_notifications, set_security_mode

        set_security_mode("security-test", confirmed=False)  # emits security_mode_warning
        items = security_notifications(event_type="security_mode_warning")
        assert items, "bypass warning must be recorded in notification history"
        newest = items[0]
        assert newest["type"] == "security_mode_warning"
        assert newest["data"]["code"] == "SECURITY_TEST_CONFIRM_REQUIRED"
        assert newest["data"]["classification"] == "attack"
        assert "ts" in newest and "source" in newest

    def test_change_recorded_after_confirm(self):
        from l3.tool_system.security_mode import security_notifications, set_security_mode

        set_security_mode("security-test", confirmed=True)  # emits security_mode_change
        items = security_notifications(event_type="security_mode_change")
        assert items
        assert items[0]["data"]["mode"] == "security-test"
        assert items[0]["data"]["confirmed"] is True

    def test_limit_and_order_newest_first(self):
        from l3.tool_system.security_mode import security_notifications, set_security_mode

        set_security_mode("security-test", confirmed=False)
        set_security_mode("security-test", confirmed=True)
        set_security_mode("productive", confirmed=True)
        items = security_notifications(limit=2)
        assert len(items) == 2
        # newest first: last action was back-to-productive
        assert items[0]["data"]["mode"] == "productive"

    def test_api_handler_exposes_notifications(self):
        from l3.tool_system.security_mode import set_security_mode

        set_security_mode("security-test", confirmed=False)
        from l4.api_handlers import ApiHandlers

        h = ApiHandlers.__new__(ApiHandlers)
        r = h._security_mode_notifications({"event_type": "security_mode_warning"})
        assert r["success"]
        assert r["count"] >= 1
        assert r["notifications"][0]["data"]["code"] == "SECURITY_TEST_CONFIRM_REQUIRED"

    def test_event_bus_emits_warning(self):
        from l1.kernel.event import get_bus, reset_bus
        from l3.tool_system.security_mode import set_security_mode

        reset_bus()
        seen: list[str] = []
        bus = get_bus()

        def _cb(sig):
            seen.append(sig.type.name if hasattr(sig.type, "name") else str(sig.type))

        try:
            bus.on_event("security_mode_warning", _cb)
            set_security_mode("security-test", confirmed=False)
            assert "security_mode_warning" in seen, f"event not forwarded: {seen}"
        finally:
            reset_bus()


class TestReviewFixes:
    """Regression tests for code-review findings (constitution use_skill action)."""

    def test_constitution_blocks_use_skill_action_without_full_power(self):
        from l1.kernel.constitution import get_constitution
        from l3.tool_system.security_mode import set_security_mode

        _mk_offensive_skill("rev-useskill")
        _wire_provider()
        cc = get_constitution()
        set_security_mode("productive", confirmed=True)
        # The tool pipeline calls is_allowed("use_skill", ...) — the §9.2 rule
        # must match that real action name.
        assert not cc.is_allowed("use_skill", "agent-x", target="rev-useskill").get("allowed")

    def test_constitution_allows_use_skill_action_with_full_power(self):
        from l1.kernel.constitution import get_constitution
        from l3.tool_system.security_mode import set_security_mode

        _mk_offensive_skill("rev-useskill2")
        _wire_provider()
        cc = get_constitution()
        set_security_mode("security-test", confirmed=True)
        assert cc.is_allowed("use_skill", "agent-x", target="rev-useskill2").get("allowed")

    def test_offensive_policy_set_parses_string_false(self):
        from l4.api_handlers.api_handlers_skills import handle_skills_offensive_policy_set

        r = handle_skills_offensive_policy_set({"enabled": "false", "agent_id": "l3a", "role": "l3"})
        assert r["success"]
        assert r["enabled"] is False  # string "false" must not invert to True

    def test_notifications_limit_guarded(self):
        from l4.api_handlers import ApiHandlers

        h = ApiHandlers.__new__(ApiHandlers)
        # malformed limit (string from query params) must not 500
        r = h._security_mode_notifications({"limit": "abc"})
        assert r["success"]
        r2 = h._security_mode_notifications({"limit": ""})
        assert r2["success"]


class TestRCBridge:
    """P0/P1: security events must land in StatsCenter/RC time series."""

    def _q(self, metric: str):
        from l3.services.stats_center import get_center

        r = get_center().query(metrics=[metric], window="all", agg="sum")
        return [(x["name"], x["value"]) for x in r]

    def test_mode_change_and_warning_metrics(self):
        from l3.services.stats_center import reset_center
        from l3.tool_system.security_mode import set_security_mode

        reset_center()
        set_security_mode("security-test", confirmed=False)  # warning
        set_security_mode("security-test", confirmed=True)  # change
        set_security_mode("productive", confirmed=True)  # change
        assert self._q("security.mode.warning") == [("security.mode.warning", 1.0)]
        assert len(self._q("security.mode.change")) == 2

    def test_ingest_security_metric_helper(self):
        from l3.services.stats_center import reset_center
        from l3.tool_system.security_mode import ingest_security_metric

        reset_center()
        ingest_security_metric("security.gate.injection.blocked", tags={"skill": "x", "nature": ""})
        ingest_security_metric("security.warrant.denied", tags={"nature": "offensive"})
        assert self._q("security.gate.injection.blocked") == [("security.gate.injection.blocked", 1.0)]
        assert self._q("security.warrant.denied") == [("security.warrant.denied", 1.0)]

    def test_use_skill_blocked_emits_metric(self):
        from l1.kernel.skill import get_skill_manager
        from l3.services.stats_center import reset_center
        from l3.tool_system.security_mode import set_security_mode
        from l3.tools._skills import use_skill

        reset_center()
        sm = get_skill_manager()
        sm.create(name="rev-m", description="d", prompt="p", posture="offensive", internal=True)
        set_security_mode("productive", confirmed=True)
        r = use_skill({"name": "rev-m"}, "agent-x")
        assert not r["success"]
        assert self._q("security.gate.use_skill.blocked") == [("security.gate.use_skill.blocked", 1.0)]


class TestRCGapClosure:
    """Regression tests for the 14-gap closure (Phases A-G)."""

    def _q(self, metric: str):
        from l3.services.stats_center import get_center

        r = get_center().query(metrics=[metric], window="all", agg="sum")
        return [(x["name"], x["value"]) for x in r]

    def test_phase_b_bypass_distribution(self):
        from l3.services.stats_center import reset_center
        from l3.tool_system.security_mode import set_security_mode

        reset_center()
        set_security_mode("security-test", confirmed=False)  # denied
        set_security_mode("security-test", confirmed=True)  # confirmed -> gauge 1.0
        set_security_mode("productive", confirmed=True)  # back -> gauge 0.0
        assert self._q("security.bypass.denied") == [("security.bypass.denied", 1.0)]
        assert len(self._q("security.bypass.confirmed")) >= 1
        # gauge recorded both for full_power (1.0) and back-to-productive (0.0)
        assert len(self._q("security.posture.full_power")) >= 2

    def test_phase_c_warrant_issued(self):
        from l3.services.stats_center import reset_center
        from l3.tool_system.security_mode import set_security_mode

        reset_center()
        set_security_mode("security-test", confirmed=True)
        from l3.cell.peers.l3a.helpers import cardwrite_handler

        cardwrite_handler({"nature": "offensive", "title": "t", "intent": "t", "phases": []}, "l3a")
        assert self._q("security.warrant.issued") == [("security.warrant.issued", 1.0)]

    def test_phase_f_memory_events(self):
        from l3.memory.memory_graph import get_graph
        from l3.memory.memory_mer import get_mer
        from l3.services.stats_center import reset_center

        reset_center()
        get_graph()._emit_event("stats.memory.graph.compact", {"n": 1})
        get_mer()._emit_event("stats.memory.mer.switch", {"enabled": True})
        assert len(self._q("stats.memory.graph.compact")) == 1
        assert len(self._q("stats.memory.mer.switch")) == 1

    def test_phase_g_agent_lifecycle(self):
        from l3.services.hook import EventEmitHook
        from l3.services.stats_center import reset_center

        reset_center()
        h = EventEmitHook()
        h.turn_complete({"ok": True}, 0.5)
        h.session_end({"ok": True})
        assert len(self._q("agent.turn_complete")) == 1
        assert len(self._q("agent.session_end")) == 1
