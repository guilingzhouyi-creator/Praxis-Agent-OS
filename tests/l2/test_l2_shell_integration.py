"""L2 Shell integration tests — surfaces requiring runtime service mocks.

Uses pytest-mock to mock the deferred imports (cell, selector, llm, l3, etc.)
so we can exercise logic paths without booting the full system.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ═══════════════════════════════════════════════════════════════
# preconnect_enhanced — depends on selector + llm
# ═══════════════════════════════════════════════════════════════

class TestPreconnectEnhanced:
    """Exercises all 5 paths in preconnect_enhanced():

    1. preconnect rejected → allowed=False
    2. LLM provider status=error → allowed=False
    3. ImportError on get_engine → llm_module_missing
    4. AttributeError on engine → llm_api_mismatch
    5. All checks pass → allowed=True
    """

    def test_preconnect_rejected(self, mocker):
        """preconnect returns allowed=False → early return."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": False, "reason": "injection_detected"}

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert not r["allowed"]
        assert "injection_detected" in r["reason"]

    def test_llm_provider_error(self, mocker):
        """LLM provider returns status=error."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": True}

        mock_engine = mocker.patch("l3.services.adapter_bridge.get_llm_engine")
        mock_engine.return_value.provider_status.return_value = {
            "status": "error", "error": "rate limited"
        }

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert not r["allowed"]
        assert "rate limited" in r["reason"]

    def test_llm_import_error(self, mocker):
        """get_engine raises ImportError → llm_module_missing."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": True}

        mocker.patch("l3.services.adapter_bridge.get_llm_engine", side_effect=ImportError("no module"))

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert not r["allowed"]
        assert "llm_module_missing" in r["reason"]

    def test_llm_attribute_error(self, mocker):
        """get_engine itself raises AttributeError → llm_api_mismatch."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": True}

        mocker.patch("l3.services.adapter_bridge.get_llm_engine", side_effect=AttributeError("engine uninitialized"))

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert not r["allowed"]
        assert "llm_api_mismatch" in r["reason"]

    def test_preconnect_all_checks_pass(self, mocker):
        """All 3 checks pass → allowed=True."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": True}

        mock_engine = mocker.patch("l3.services.adapter_bridge.get_llm_engine")
        mock_engine.return_value.provider_status.return_value = {"status": "ok"}

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert r["allowed"]
        assert "preconnect" in r["checks"]
        assert "llm_provider" in r["checks"]

    def test_llm_unexpected_exception(self, mocker):
        """Generic Exception fallback → llm_unavailable."""
        mock_preconnect = mocker.patch("l2.selector.preconnect")
        mock_preconnect.return_value = {"allowed": True}

        mocker.patch("l3.services.adapter_bridge.get_llm_engine", side_effect=RuntimeError("OOM"))

        from l2.l2_shell import preconnect_enhanced
        r = preconnect_enhanced("cell-1", "agent-a")
        assert not r["allowed"]
        assert "llm_unavailable" in r["reason"]


# ═══════════════════════════════════════════════════════════════
# _complete_agent + _cmd_agents — depend on selector.preselect
# ═══════════════════════════════════════════════════════════════

class TestCompleteAgent:
    def test_complete_agent_matches_partial(self, mocker):
        mock_terms = mocker.patch("l3.agent_terminal.get_terminals")
        mock_terms.return_value = {
            "agent-alpha": object(), "agent-beta": object(), "scout-1": object(),
        }

        from l2.l2_shell import _complete_agent
        results = _complete_agent("alpha")
        assert len(results) == 1
        assert results[0]["value"] == "agent-alpha"
        assert results[0]["type"] == "agent"

    def test_complete_agent_empty_partial_returns_all(self, mocker):
        mock_terms = mocker.patch("l3.agent_terminal.get_terminals")
        mock_terms.return_value = {"a1": object(), "a2": object()}

        from l2.l2_shell import _complete_agent
        results = _complete_agent("")
        assert len(results) == 2

    def test_complete_agent_preselect_fails_gracefully(self, mocker):
        mocker.patch("l3.agent_terminal.get_terminals", side_effect=RuntimeError("fail"))

        from l2.l2_shell import _complete_agent
        results = _complete_agent("x")
        assert results == []


class TestCmdAgents:
    def test_cmd_agents_returns_preselect(self, mocker):
        mock_preselect = mocker.patch("l2.l2_shell.commands.connect.preselect")
        mock_preselect.return_value = {"agents": [{"agent_id": "a1"}]}

        from l2.l2_shell import _cmd_agents
        r = _cmd_agents([])
        assert r["success"] is True
        assert r["data"] == {"agents": [{"agent_id": "a1"}]}


# ═══════════════════════════════════════════════════════════════
# _cmd_connect + _cmd_disconnect — full flow with session
# ═══════════════════════════════════════════════════════════════

class TestCmdConnectFull:
    def test_connect_no_args(self):
        from l2.l2_shell import _cmd_connect
        r = _cmd_connect([])
        assert not r["success"]

    def test_connect_unknown_agent(self, mocker):
        from l2.l2_shell import _cmd_connect, reset_state
        reset_state()
        mocker.patch("l3.agent_terminal.get_terminals", return_value={})
        r = _cmd_connect(["agent-x"])
        assert not r["success"]
        assert "unknown agent" in r["error"]

    def test_connect_send_fails(self, mocker):
        from l2.l2_shell import _cmd_connect, reset_state
        reset_state()
        mocker.patch("l3.agent_terminal.get_terminals", return_value={"agent-z": object()})
        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.send_direct_message.return_value = {
            "success": False, "error": "agent_unreachable"
        }
        r = _cmd_connect(["agent-z"])
        assert not r["success"]
        assert "agent_unreachable" in r["error"]

    def test_connect_success(self, mocker):
        from l2.l2_shell import _cmd_connect, get_state, reset_state
        reset_state()
        mocker.patch("l3.agent_terminal.get_terminals", return_value={"agent-y": object()})
        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.send_direct_message.return_value = {
            "success": True, "card_id": "card-1"
        }
        r = _cmd_connect(["agent-y"])
        assert r["success"]
        s = get_state()
        assert s.is_direct()
        assert s.agent_id == "agent-y"


class TestCmdDisconnectWithSession:
    def test_disconnect_active_session(self, mocker):
        from l2.l2_shell import _cmd_disconnect, get_state, reset_state
        reset_state()

        s = get_state()
        s.switch_to_direct("cell-1", "agent-active")

        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.close_direct_session.return_value = {"success": True}

        r = _cmd_disconnect([])
        assert r["success"]
        assert not s.is_direct()

    def test_disconnect_fails_still_clears_state(self, mocker):
        """Even if close_direct_session fails, state reverts to L3A."""
        from l2.l2_shell import _cmd_disconnect, get_state, reset_state
        reset_state()

        s = get_state()
        s.switch_to_direct("cell-1", "agent-fail")

        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.close_direct_session.side_effect = RuntimeError("crash")

        r = _cmd_disconnect([])
        assert r["success"]
        assert not s.is_direct()


# ═══════════════════════════════════════════════════════════════
# 9 Central control commands
# ═══════════════════════════════════════════════════════════════

class TestCmdIntents:
    def test_list_intents(self, mocker):
        mock_reg = mocker.patch("l3.scheduler.think_registry.get_think_registry")
        mock_reg.return_value.stats.return_value = {"cells": {"cell-1": {}}}

        from l2.l2_shell import _cmd_intents
        r = _cmd_intents([])
        assert r["success"]
        assert "intents" in r


class TestCmdScheduler:
    def test_scheduler_with_stats(self, mocker):
        mock_sched = mocker.patch("l3.scheduler.scheduler.get_scheduler")
        mock_sched.return_value.stats.return_value = {"queued": 5}

        from l2.l2_shell import _cmd_scheduler
        r = _cmd_scheduler([])
        assert r["success"]
        assert r["data"] == {"queued": 5}

    def test_scheduler_without_stats(self, mocker):
        mock_sched = mocker.patch("l3.scheduler.scheduler.get_scheduler")
        mock_sched.return_value = object()  # no stats() method

        from l2.l2_shell import _cmd_scheduler
        r = _cmd_scheduler([])
        assert r["success"]
        assert "data" in r


class TestCmdObserve:
    def test_observe_default_health(self, mocker):
        mock_bus = mocker.patch("l3.bus.observability_bus.get_obs_bus")
        mock_bus.return_value.summary.return_value = {"health": "ok"}

        from l2.l2_shell import _cmd_observe
        r = _cmd_observe([])
        assert r["success"]
        assert r["data"] == {"health": "ok"}

    def test_observe_with_kind(self, mocker):
        mock_bus = mocker.patch("l3.bus.observability_bus.get_obs_bus")
        mock_bus.return_value.summary.return_value = {"alerts": []}

        from l2.l2_shell import _cmd_observe
        r = _cmd_observe(["alert"])
        assert r["success"]
        assert "data" in r


class TestCmdSkills:
    def test_skills_list_default(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = [
            {"name": "s1"}, {"name": "s2"}, {"name": "s3"},
        ]

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills([])
        assert r["success"]
        assert r["count"] == 3

    def test_skills_lean(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = [{"name": "s1"}]

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["lean"])
        assert r["success"]
        assert "skills" in r

    def test_skills_evolve(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = []
        mock_sm.return_value.authorize_write.return_value = (True, "l3")
        mock_r4 = mocker.patch("l3.memory.r4_agent.get_r4_agent")
        mock_r4.return_value.evolve_skill.return_value = {"success": True, "skill": "x"}

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["evolve", "optimize", "build"])
        assert r["success"]

    def test_skills_evolve_without_method(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.list_skills.return_value = []
        mock_sm.return_value.authorize_write.return_value = (True, "l3")
        mock_r4 = mocker.patch("l3.memory.r4_agent.get_r4_agent")
        mock_r4.return_value.evolve_skill.return_value = {"success": True, "skill": "x"}

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["evolve", "something"])
        assert r["success"]

    def test_skills_get(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.get.return_value = {"name": "s1", "prompt": "p"}

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["get", "s1"])
        assert r["success"]
        assert r["skill"]["name"] == "s1"

    def test_skills_permissions(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.write_policy.return_value = {"write_min_ring": 3, "write_roles": ["l3"]}

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["permissions"])
        assert r["success"]
        assert r["policy"]["write_min_ring"] == 3

    def test_skills_create_with_role(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.create.return_value = {"success": True, "skill": "k"}

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["create", "k", "desc", "prompt", "--role", "l3"])
        assert r["success"]
        mock_sm.return_value.create.assert_called_once()
        kwargs = mock_sm.return_value.create.call_args.kwargs
        assert kwargs["role"] == "l3"

    def test_skills_reload_denied(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")
        mock_sm.return_value.authorize_write.return_value = (False, "permission denied: reader")

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["reload", "--role", "reader"])
        assert not r["success"]

    def test_skills_update_unsupported_field(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["update", "k", "bogus", "v"])
        assert not r["success"]
        assert "unsupported field" in r["error"]

    def test_skills_unknown_sub(self, mocker):
        mock_sm = mocker.patch("l1.kernel.skill.get_skill_manager")

        from l2.l2_shell import _cmd_skills
        r = _cmd_skills(["bogus"])
        assert not r["success"]
        assert "unknown skills subcommand" in r["error"]


class TestCmdCells:
    def test_cells_list(self, mocker):
        from l2.l2_shell import _cmd_cells
        r = _cmd_cells([])
        assert r["success"]
        assert "cell" in r

    def test_cells_get_events(self, mocker):
        from l2.l2_shell import _cmd_cells
        r = _cmd_cells(["cell-x"])
        assert r["success"]


class TestCmdCross:
    def test_cross_cell_status(self, mocker):
        mock_coord = mocker.patch("l3.cell.peers.l3.get_coordinator")
        mock_coord.return_value.cross_cell_active = True

        from l2.l2_shell import _cmd_cross
        r = _cmd_cross([])
        assert r["success"]
        assert "cross" in r

    def test_cross_cell_no_status_method(self, mocker):
        mock_coord = mocker.patch("l3.cell.peers.l3.get_coordinator")
        mock_coord.return_value = object()  # no cross_cell_active

        from l2.l2_shell import _cmd_cross
        r = _cmd_cross([])
        assert r["success"]
        assert "cross" in r


class TestCmdSecurity:
    def test_security_stats(self, mocker):
        mock_sec = mocker.patch("l3.services.central_security.get_center")
        mock_sec.return_value.audit_log.return_value = []

        from l2.l2_shell import _cmd_security
        r = _cmd_security(["audit"])
        assert r["success"]
        assert "audit" in r

    def test_security_default(self, mocker):
        mock_sec = mocker.patch("l3.services.central_security.get_center")

        from l2.l2_shell import _cmd_security
        r = _cmd_security([])
        assert r["success"]
        assert r["status"] == "ok"

    def test_security_invalid_sub(self, mocker):
        mock_sec = mocker.patch("l3.services.central_security.get_center")

        from l2.l2_shell import _cmd_security
        r = _cmd_security(["stats"])
        assert r["success"]


class TestCmdMemory:
    def test_memory_stats(self, mocker):
        mocker.patch("l3.agent_terminal.get_terminals", return_value={"agent-a": object()})
        mock_mem = mocker.patch("l3.memory.memory.get_memory")
        mock_mem.return_value.aggregate_stats.return_value = {"entries": 100}

        from l2.l2_shell import _cmd_memory
        r = _cmd_memory(["stats"])
        assert r["success"]
        assert r["data"] == {"entries": 100}

    def test_memory_recall(self, mocker):
        mocker.patch("l3.agent_terminal.get_terminals", return_value={"agent-a": object()})
        mock_mem = mocker.patch("l3.memory.memory.get_memory")
        mock_mem.return_value.recall.return_value = [{"id": "mem-1"}]

        from l2.l2_shell import _cmd_memory
        r = _cmd_memory(["search", "login", "bug"])
        assert r["success"]
        assert "data" in r

    def test_memory_usage_error(self, mocker):
        mocker.patch("l3.memory.memory.get_memory")

        from l2.l2_shell import _cmd_memory
        r = _cmd_memory(["recall"])  # no agents in scope
        assert not r["success"] or "error" in r


class TestCmdPlugins:
    def test_plugins_list(self, mocker):
        mock_plug = mocker.patch("l3.services.central_plugin.get_center")
        mock_plug.return_value.list_plugins.return_value = ["plugin-a"]

        from l2.l2_shell import _cmd_plugins
        r = _cmd_plugins([])
        assert r["success"]
        assert "plugins" in r

    def test_plugins_stats(self, mocker):
        mock_plug = mocker.patch("l3.services.central_plugin.get_center")
        mock_plug.return_value.stats.return_value = {"count": 3}

        from l2.l2_shell import _cmd_plugins
        r = _cmd_plugins(["stats"])
        assert r["success"]
        assert "stats" in r


# ═══════════════════════════════════════════════════════════════
# _cmd_status — Direct mode with liveness check
# ═══════════════════════════════════════════════════════════════

class TestCmdStatusDirect:
    def test_status_direct_mode_with_liveness(self, mocker):
        from l2.l2_shell import _cmd_status, get_state, reset_state
        reset_state()

        s = get_state()
        s.switch_to_direct("cell-1", "agent-live", "sess-42")

        r = _cmd_status([])
        assert r["mode"] == "DIRECT"
        assert r["agent_id"] == "agent-live"
        assert r["cell_id"] == "cell-1"

    def test_status_direct_mode_liveness_error(self, mocker):
        from l2.l2_shell import _cmd_status, get_state, reset_state
        reset_state()

        s = get_state()
        s.switch_to_direct("cell-1", "agent-dead")

        r = _cmd_status([])
        assert r["mode"] == "DIRECT"
        assert r["agent_id"] == "agent-dead"


# ═══════════════════════════════════════════════════════════════
# _direct_message — full success path with output guard
# ═══════════════════════════════════════════════════════════════

class TestDirectMessage:
    def test_direct_message_sends_and_guards(self, mocker):
        """Verify _direct_message sends via cell and runs output guard."""
        from l2.l2_shell import ShellState, _direct_message

        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.send_direct_message.return_value = {
            "success": True, "output": "safe reply"
        }

        state = ShellState()
        state.switch_to_direct("cell-1", "agent-a")

        r = _direct_message(state, "hello")
        assert r["success"]
        assert r["answer"] == "safe reply"
        assert not r["output_guarded"]

    def test_direct_message_cell_failure_auto_disconnects(self, mocker):
        """Cell failure triggers _auto_disconnect and returns to L3A."""
        from l2.l2_shell import ShellState, _direct_message

        mock_cell = mocker.patch("l3.cell.get_cell")
        mock_cell.return_value.send_direct_message.return_value = {
            "success": False, "error": "agent_not_found"
        }

        state = ShellState()
        state.switch_to_direct("cell-1", "agent-a")

        r = _direct_message(state, "ping")
        assert not r["success"]
        # State should have auto-fallbacked to L3A
        assert not state.is_direct()
