"""AgentTerminal lifecycle test — boot/dispatch/wait/pause/resume/shutdown.

Covered scenarios:
  - Initial state after terminal creation
  - boot() → IDLE state transition
  - dispatch() → PROCESSING
  - wait_for_result() timeout behavior
  - pause() / resume() state locking
  - shutdown() cleanup
  - read_stdout / read_stderr
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentTerminalInit:
    """Initial state after creation"""

    def test_init_state(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("init-agent", role="reader", territory=["."])
        assert term.agent_id == "init-agent"
        assert term.role == "reader"
        assert term.status.name == "BOOTING"

    def test_init_booting_no_tools(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("no-tool-agent", role="test")
        # Before boot, list_tools should be empty or safely degraded
        tools = term.list_tools()
        assert isinstance(tools, list)


class TestAgentTerminalBoot:
    """boot() state transition"""

    def test_boot_transitions_to_idle(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("boot-agent", role="reader", territory=["."])
        r = term.boot()
        assert r.get("success"), f"boot failed: {r}"
        assert term.status.name == "IDLE", f"expected IDLE, got {term.status.name}"

    def test_boot_twice_is_safe(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("reboot-agent", role="reader", territory=["."])
        term.boot()
        r2 = term.boot()
        assert isinstance(r2, dict)


class TestAgentTerminalDispatch:
    """dispatch() + wait_for_result()"""

    def test_dispatch_returns_card_id(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        from l3.agent._term_types import TerminalCard, CardMode
        reset_terminals()
        term = get_terminal("disp-agent", role="reader", territory=["."])
        card = TerminalCard(mode=CardMode.EXECUTE, action="think",
                            target=".", params={}, sender="test")
        cid = term.dispatch(card)
        assert isinstance(cid, str)
        assert len(cid) > 0, "dispatch should return a card_id"

    def test_wait_for_result_timeout(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        from l3.agent._term_types import TerminalCard, CardMode
        reset_terminals()
        term = get_terminal("wait-agent", role="reader", territory=["."])
        card = TerminalCard(mode=CardMode.EXECUTE, action="think",
                            target=".", params={}, sender="test")
        cid = term.dispatch(card)
        # Without boot, process_card won't run → timeout
        result = term.wait_for_result(cid, timeout=0.1)
        assert result is None, "should timeout with None result"


class TestAgentTerminalPauseResume:
    """pause() / resume() state locking"""

    def test_pause_changes_state(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("pause-agent", role="reader", territory=["."])
        term.boot()
        r = term.pause()
        assert r.get("success"), f"pause failed: {r}"
        assert term._paused, "should be paused"

    def test_resume_clears_pause(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("resume-agent", role="reader", territory=["."])
        term.boot()
        term.pause()
        r = term.resume()
        assert r.get("success"), f"resume failed: {r}"
        assert not term._paused, "should not be paused after resume"


class TestAgentTerminalShutdown:
    """shutdown() cleanup"""

    def test_shutdown_clears_state(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("sd-agent", role="reader", territory=["."])
        term.boot()
        from l3.agent._term_types import TerminalCard, CardMode
        card = TerminalCard(mode=CardMode.EXECUTE, action="shutdown_test",
                            target=".", params={}, sender="test")
        term.dispatch(card)
        r = term.shutdown()
        assert isinstance(r, dict)
        assert term.status.name == "STOPPED", \
            f"expected STOPPED, got {term.status.name}"

    def test_shutdown_idempotent(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("sd2-agent", role="reader", territory=["."])
        term.shutdown()
        r2 = term.shutdown()
        assert isinstance(r2, dict)


class TestAgentTerminalIO:
    """I/O pipeline"""

    def test_read_stdout_returns_list(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("io-agent", role="reader", territory=["."])
        out = term.read_stdout(clear=False)
        assert isinstance(out, list)

    def test_read_stderr_returns_list(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        reset_terminals()
        term = get_terminal("io-agent2", role="reader", territory=["."])
        err = term.read_stderr(clear=False)
        assert isinstance(err, list)

    def test_stdout_maxlen(self):
        """Verify stdout deque does not grow unbounded"""
        from l3.agent_terminal import get_terminal, reset_terminals
        from l3.agent._term_types import CardResult
        reset_terminals()
        term = get_terminal("io-agent3", role="reader", territory=["."])
        for i in range(600):
            term.stdout.append(CardResult(card_id=f"c{i}", action="test",
                                           success=True, output="x"))
        assert len(term.stdout) <= 550, "stdout should be bounded"
