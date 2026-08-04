"""Agent tests conftest — provide a mock LLM engine port for AgentLoop tests.

agent_loop.run() resolves its engine via ``_get_port("llm")`` (see
l1.kernel.ports).  Tests that drive AgentLoop without booting the system
need a registered ``llm`` port; otherwise run() raises
``KeyError: port 'llm' not registered``.

The fixture registers a minimal mock engine for every test in this
directory and restores the previous adapter afterwards.
"""

import pytest

from l1.kernel.ports import _PORTS, register_port


class _MockLLMEngine:
    """Minimal LLM engine: no tool calls, immediate finish."""

    def context_window(self, cell_id="", agent_id=""):
        return 32_000

    def tool_use(self, prompt, tools, system="", max_turns=5,
                 user_id="", **overrides):
        return {
            "content": "",
            "tool_calls": [],
            "tool_call_results": [],
            "turns": 0,
            "finish_reason": "stop",
        }

    def generate(self, prompt, system="", user_id="", **overrides):
        return {"content": ""}


@pytest.fixture(autouse=True)
def _mock_llm_port():
    saved = _PORTS.get("llm")
    register_port("llm", _MockLLMEngine())
    yield
    if saved is None:
        _PORTS.pop("llm", None)
    else:
        _PORTS["llm"] = saved
