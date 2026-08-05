"""System-prompt injection switches — prompt.inject.<domain> gating.

Each domain (profile/constitution/skills/verification/memory) appends a
block to agent system prompts; the SettingsCenter key ``prompt.inject.<domain>``
(default true) lets users strip any of them at runtime via the settings API.
"""

from __future__ import annotations

import pytest

from l1.kernel.settings import get_settings, inject_enabled, reset_settings


@pytest.fixture(autouse=True)
def _clean_settings():
    reset_settings()
    # Force all switches on regardless of any persisted settings file
    sc = get_settings()
    for d in ("profile", "constitution", "skills", "verification", "memory"):
        sc.set(f"prompt.inject.{d}", True)
    yield
    reset_settings()


class TestInjectSwitch:
    def test_defaults_all_on(self):
        for d in ("profile", "constitution", "skills", "verification", "memory"):
            assert inject_enabled(d) is True

    def test_toggle_off_via_settings_center(self):
        get_settings().set("prompt.inject.profile", False)
        assert inject_enabled("profile") is False
        get_settings().set("prompt.inject.constitution", False)
        assert inject_enabled("constitution") is False
        # unrelated domains unaffected
        assert inject_enabled("skills") is True


class TestAgentLoopGating:
    def _run_loop(self, system: str = "BASE"):
        """Run one AgentLoop step with a stub LLM, returning the system prompt."""
        from l1.kernel.ports import register_port

        captured: list[str] = []

        class _StubLLM:
            def context_window(self, cell_id: str = "", agent_id: str = "") -> int:
                return 8192

            def generate(self, prompt: str = "", system: str = "", **kwargs) -> dict:
                captured.append(system)
                return {"content": "ok", "tool_calls": []}

            def tool_use(self, prompt: str = "", system: str = "", tools=None,
                         **kwargs) -> dict:
                captured.append(system)
                return {"content": "done", "tool_call_results": [],
                        "turns": 1, "finish_reason": "stop",
                        "context_trail": [], "tools_elapsed": 0.001}

        register_port("llm", _StubLLM())
        from l3.agent.agent_loop import AgentLoop

        loop = AgentLoop(task="probe task", agent_id="agent-t",
                         role="tester", system=system)
        loop.run(max_steps=1, timeout=10)
        return captured

    def test_constitution_inject_on(self, monkeypatch):
        import l1.kernel.constitution as _const

        class _StubConst:
            def summary(self, for_agent: str = "") -> str:
                return "CONSTITUTION_MARKER_RULES"

        monkeypatch.setattr(_const, "get_constitution", lambda: _StubConst())
        sys_prompts = self._run_loop()
        assert sys_prompts, "LLM was never invoked"
        assert "CONSTITUTION_MARKER_RULES" in "\n".join(sys_prompts)

    def test_constitution_inject_off(self, monkeypatch):
        import l1.kernel.constitution as _const

        class _StubConst:
            def summary(self, for_agent: str = "") -> str:
                return "CONSTITUTION_MARKER_RULES"

        monkeypatch.setattr(_const, "get_constitution", lambda: _StubConst())
        get_settings().set("prompt.inject.constitution", False)
        sys_prompts = self._run_loop()
        joined = "\n".join(sys_prompts)
        assert "BASE" in joined
        assert "CONSTITUTION_MARKER_RULES" not in joined

    def test_verification_inject_off(self):
        from l1.kernel.prompts import get_prompt

        vc = get_prompt("agent_loop.verification_culture", "")
        if not vc:
            pytest.skip("verification culture template not present")
        get_settings().set("prompt.inject.verification", False)
        sys_prompts = self._run_loop()
        joined = "\n".join(sys_prompts)
        marker = vc.split("\n")[0][:30]
        assert marker not in joined


class TestProfileGating:
    def test_profile_inject_switch(self):
        from l3.services.user_profile import get_service, reset_service

        reset_service()
        get_service().set_enabled(True)
        get_service().start()
        get_service().ingest("alice", "preference", "concise", confidence=0.9)
        from l3.cell.peers.l3a.helpers import build_l3a_prompt

        get_settings().set("prompt.inject.profile", False)
        assert "User Profile Reference" not in build_l3a_prompt(user_id="alice")
        get_settings().set("prompt.inject.profile", True)
        assert "User Profile Reference" in build_l3a_prompt(user_id="alice")
        reset_service()
