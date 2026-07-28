"""Tests for l3.services.counter — CellCounter token/tool/loop recording + query."""

from __future__ import annotations


class TestCellCounterRecord:
    """CellCounter 基础记录功能。"""

    def _make(self):
        from l3.services.counter import CellCounter
        return CellCounter()

    def test_record_token(self):
        c = self._make()
        c.record_token("agent-a", input_tokens=100, output_tokens=50)
        s = c.token_summary("agent-a")
        assert s["calls"] == 1
        assert s["input_tokens"] == 100
        assert s["output_tokens"] == 50
        assert s["total_tokens"] == 150

    def test_record_tool(self):
        c = self._make()
        c.record_tool("agent-a", "read_file", success=True, elapsed=0.5)
        s = c.tool_summary("agent-a")
        assert s["total"] == 1
        assert s["by_tool"]["read_file"]["calls"] == 1

    def test_record_loop(self):
        c = self._make()
        c.record_loop("agent-a", turns=5, steps=10, elapsed=2.0)
        s = c.loop_summary("agent-a")
        assert s["total"] == 1
        assert s["total_turns"] == 5
        assert s["total_steps"] == 10


class TestCellCounterQuery:
    """CellCounter 查询功能。"""

    def _make(self):
        from l3.services.counter import CellCounter
        c = CellCounter()
        c.record_token("agent-a", 100, 50)
        c.record_token("agent-b", 200, 100)
        c.record_tool("agent-a", "read_file", True, 0.3)
        c.record_tool("agent-a", "write_file", False, 0.8)
        c.record_loop("agent-a", 5, 10, 2.0)
        return c

    def test_token_summary_all(self):
        c = self._make()
        s = c.token_summary()
        assert "agent-a" in s
        assert "agent-b" in s

    def test_tool_summary_counts(self):
        c = self._make()
        s = c.tool_summary("agent-a")
        assert s["by_tool"]["read_file"]["success"] == 1
        assert s["by_tool"]["write_file"]["failure"] == 1

    def test_cell_total_aggregates(self):
        c = self._make()
        ct = c.cell_total()
        assert "agent-a" in ct["agents"]
        assert "agent-b" in ct["agents"]

    def test_token_rate(self):
        c = self._make()
        r = c.token_rate(window=60.0)
        assert "tokens_per_min" in r
        assert "by_agent" in r

    def test_empty_counter(self):
        c = CellCounter()
        assert c.token_summary() == {}
        assert c.tool_summary("nonexistent") == {"total": 0}
        assert c.loop_summary("nonexistent") == {"total": 0}


class TestCellCounterSingleton:
    """get_counter() / reset_counter() 单例模式。"""

    def test_singleton(self):
        from l3.services.counter import get_counter, reset_counter
        reset_counter()
        c1 = get_counter()
        c2 = get_counter()
        assert c1 is c2

    def test_reset(self):
        from l3.services.counter import get_counter, reset_counter
        reset_counter()
        c1 = get_counter()
        reset_counter()
        c2 = get_counter()
        assert c1 is not c2
