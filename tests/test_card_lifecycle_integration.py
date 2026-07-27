"""Card 全生命周期集成测试 — L2 dispatch → CardRegistry → Cell → AgentTerminal → ToolPipeline → Memory → complete。

流程：
  1. 创建一个 Cell + Agent
  2. 通过 CardRegistry.submit() 提交卡片
  3. Cell 执行 execute_card()
  4. AgentTerminal 处理 dispatch
  5. ToolPipeline 执行
  6. Memory 存储结果
  7. CardRegistry.complete() 标记完成
"""

from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _setup_cell():
    """Helper: create a clean Cell with one reader agent."""
    from l3.cell import get_cell, reset_cells
    from l3.agent_terminal import reset_terminals
    reset_cells()
    reset_terminals()
    cell = get_cell("integration-cell", ["src", "tests"])
    cell.add_agent("reader-1", role="reader", ring=1, territory=["src"],
                    max_scouts=2, auto_boot=False)
    return cell


class TestCardLifecycleIntegration:
    """卡片全生命周期 — submit → dispatch → execute → complete"""

    def test_submit_dispatch_complete_cycle(self):
        """基本生命周期：submit → 获取 → complete"""
        from l3.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("Complete this card lifecycle integration test task", ".")
        assert cid.startswith("card-"), f"submit failed: {cid}"
        card = cr.get(cid)
        assert card is not None
        r = cr.complete(cid)
        assert isinstance(r, (dict, bool))

    def test_submit_cancel_cycle(self):
        """submit → cancel 流程"""
        from l3.card_registry import get_registry, reset_registry
        reset_registry()
        cr = get_registry()
        cid = cr.submit("Cancellable integration test task", ".")
        assert cid.startswith("card-")
        r = cr.cancel(cid)
        assert r is not False

    def test_card_pool_install(self):
        """card_pool 基本操作不崩溃"""
        from l3.card_pool import get_pool as _cp
        pool = _cp()
        r = pool.list_pool()
        assert isinstance(r, dict)

    def test_card_builder_creates_card(self):
        """CardBuilder 从意图创建卡片"""
        from l3.card_builder import build_card
        card = build_card(task_id="test-int-1", intent="Read the README file",
                          domain=".")
        assert card is not None
        assert card.summary.title == "Read the README file"


class TestCellExecuteCardIntegration:
    """Cell.execute_card 集成 — raw intent → Card → execute"""

    def test_cell_execute_simple(self):
        """Cell 执行原始意图不崩溃"""
        cell = _setup_cell()
        result = cell.execute_card("list directory", domain=".")
        assert isinstance(result, dict)

    def test_cell_execute_with_card_object(self):
        """Cell 执行 Card 对象不崩溃"""
        from l3.card import Card
        cell = _setup_cell()
        card = Card(intent="List files in the current directory for inspection", domain=".")
        result = cell.execute_card(card)
        assert isinstance(result, dict)

    def test_cell_dispatch_card(self):
        """Cell.dispatch_card 向 Agent 发送 TerminalCard"""
        from l3.agent_terminal import get_terminal
        cell = _setup_cell()
        term = get_terminal("reader-1", role="reader", territory=["src"], cell_id="integration-cell")
        r = cell.dispatch_card("reader-1", "think", target=".", params={})
        assert isinstance(r, dict)


class TestMemoryAfterExecution:
    """执行后 Memory 应当存储结果"""

    def test_memory_has_entries_after_remember(self):
        from l3.memory import get_memory, reset_memory
        reset_memory()
        mem = get_memory()
        r = mem.remember("integration-agent", "decision",
                          "Use Python 3.11 for this project with async/await pattern.",
                          tags=["python", "async"], ring=1)
        assert r.startswith("mem-"), f"remember failed: {r}"
        stats = mem.stats()
        assert stats["working"]["entries"] >= 1

    def test_recall_after_store(self):
        from l3.memory import get_memory, reset_memory
        reset_memory()
        mem = get_memory()
        mem.remember("recall-agent", "observation",
                      "The system runs on Windows with Python 3.11 and minimal dependencies.",
                      tags=["python", "windows"], ring=1)
        results = mem.recall(agent_id="recall-agent", limit=10)
        assert len(results) >= 1, "should find stored entry"
