"""Tests for l3.services.approval_policy — danger level resolve/override."""

from __future__ import annotations


class TestApprovalPolicy:
    """ApprovalPolicy — three-layer danger level: Agent > Cell > Global."""

    def _make(self):
        from l3.services.approval_policy import ApprovalPolicy
        return ApprovalPolicy()

    def test_resolve_global_default(self):
        """无 override 时返回全局默认 danger 等级。"""
        p = self._make()
        level = p.resolve("cell-1", "agent-a", "read_file")
        assert isinstance(level, int)
        assert level >= 1

    def test_cell_override(self):
        """Cell 级 override 应覆盖全局默认值。"""
        p = self._make()
        p.set_cell_danger("cell-1", "read_file", 5)
        level = p.resolve("cell-1", "agent-a", "read_file")
        assert level == 5

    def test_agent_override_highest_priority(self):
        """Agent 级 override 应优先于 Cell 级。"""
        p = self._make()
        p.set_cell_danger("cell-1", "read_file", 3)
        p.set_agent_danger("cell-1", "agent-a", "read_file", 5)
        level = p.resolve("cell-1", "agent-a", "read_file")
        assert level == 5

    def test_cell_override_isolated(self):
        """不同 Cell 的 override 不应互相影响。"""
        p = self._make()
        p.set_cell_danger("cell-1", "write_file", 5)
        level_c1 = p.resolve("cell-1", "agent-a", "write_file")
        level_c2 = p.resolve("cell-2", "agent-a", "write_file")
        assert level_c1 == 5
        assert level_c2 != 5

    def test_agent_override_isolated(self):
        """不同 Agent 的 override 不应互相影响。"""
        p = self._make()
        p.set_agent_danger("cell-1", "agent-a", "write_file", 5)
        level_a = p.resolve("cell-1", "agent-a", "write_file")
        level_b = p.resolve("cell-1", "agent-b", "write_file")
        assert level_a == 5
        assert level_b != 5

    def test_unknown_tool_returns_global(self):
        """未知工具的 danger 应返回全局默认值。"""
        p = self._make()
        level = p.resolve("cell-1", "agent-a", "nonexistent_tool_xyz")
        assert isinstance(level, int)

    def test_stats(self):
        """stats 应返回正确的 override 统计。"""
        p = self._make()
        p.set_cell_danger("cell-1", "read_file", 5)
        p.set_cell_danger("cell-1", "write_file", 4)
        p.set_agent_danger("cell-1", "agent-a", "delete_file", 5)
        s = p.stats()
        assert "cell_overrides" in s
        assert "agent_overrides" in s
        assert s["cell_overrides"].get("cell-1", 0) == 2
        assert s["agent_overrides"].get("cell-1.agent-a", 0) == 1

    def test_get_cell_dangers(self):
        """get_cell_dangers 返回指定 Cell 的 override 字典。"""
        p = self._make()
        p.set_cell_danger("cell-1", "read_file", 5)
        dangers = p.get_cell_dangers("cell-1")
        assert dangers.get("read_file") == 5

    def test_get_agent_dangers(self):
        """get_agent_dangers 返回指定 Agent 的 override 字典。"""
        p = self._make()
        p.set_agent_danger("cell-1", "agent-a", "write_file", 4)
        dangers = p.get_agent_dangers("cell-1", "agent-a")
        assert dangers.get("write_file") == 4

    def test_multiple_cells(self):
        """多个 Cell 的 override 共存时独立运行。"""
        p = self._make()
        p.set_cell_danger("cell-1", "tool_a", 2)
        p.set_cell_danger("cell-2", "tool_a", 5)
        assert p.resolve("cell-1", "agent-x", "tool_a") == 2
        assert p.resolve("cell-2", "agent-x", "tool_a") == 5
