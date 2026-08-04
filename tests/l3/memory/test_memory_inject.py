"""任务感知动态记忆注入（memory_inject）测试。

覆盖：分类器（卡路径/提示词路径）、策略解析、注入器（summary/mer/layered）、
Cell 挂钩、L3A 挂钩。
"""

from l3.memory.memory_inject import (
    MemoryInjector, build_context, classify_task, TASK_EXECUTE,
    TASK_DECIDE, TASK_RESUME,
)


class FakeCard:
    def __init__(self, nature="execution", action="write_file", target="x"):
        self.nature = nature
        self.action = action
        self.target = target


def test_classify_card_execution_defaults_to_summary():
    assert classify_task(FakeCard()) == TASK_EXECUTE


def test_classify_card_decision_nature():
    assert classify_task(FakeCard(nature="decision")) == TASK_DECIDE


def test_classify_card_decision_keyword():
    assert classify_task(FakeCard(action="review")) == TASK_DECIDE
    assert classify_task(FakeCard(action="audit")) == TASK_DECIDE


def test_classify_prompt_keywords():
    assert classify_task(prompt="please review the auth module") == TASK_DECIDE
    assert classify_task(prompt="analyze the failure") == TASK_DECIDE
    assert classify_task(prompt="implement the fix") == TASK_EXECUTE
    assert classify_task(prompt="resume the previous session") == TASK_RESUME


def test_classify_card_wins_over_prompt():
    # 卡是权威任务源（Cell 路径），提示词兜底（L3A 路径）
    assert classify_task(FakeCard(), prompt="analyze everything") == TASK_EXECUTE


def test_injector_summary_falls_back(tmp_path):
    """summary 维度回退到现有 build_context（无记忆时为空串）。"""
    inj = MemoryInjector()
    r = inj.build_context("a1", card=FakeCard(), max_tokens=512)
    assert isinstance(r, str)  # 空或摘要文本——不抛异常


def test_injector_mer_requires_graph(tmp_path):
    """Mer 维度在图未启用时回退 summary（零影响）。"""
    inj = MemoryInjector()
    r = inj.build_context("a1", card=FakeCard(nature="decision"),
                          max_tokens=512)
    assert isinstance(r, str)


def test_build_context_module_level(tmp_path):
    r = build_context("a1", card=FakeCard(), max_tokens=256)
    assert isinstance(r, str)


def test_l3a_prompt_injection(tmp_path):
    """L3A prompt 路径：提示词分类 → 注入块加入 context_trail。"""
    from l3.cell.peers.l3a import get_daemon
    from l3.memory.central_memory import reset_center
    reset_center()
    d = get_daemon()
    s = d.create_session("inject-test")
    s._ensure_loop()

    def fake_run(**kw):
        return {"answer": "ok", "success": True, "tool_calls": [],
                "reasoning_trail": ["t"], "reasoning_tokens": 1}
    s._loop.run = fake_run
    r = s.prompt("please review the memory injection design")
    assert r.get("success")
    # 决策类提示词 → 注入块应出现（Task-Aware Memory）
    injected = [m for m in s._loop._context_trail
                if isinstance(m, dict)
                and m.get("role") == "system"
                and "Task-Aware Memory" in m.get("content", "")]
    assert injected, "task-aware block should be injected for decide prompts"
    s.close()
