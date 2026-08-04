"""MemoryInjector — 任务感知的动态记忆注入。

激活路径（按任务来源分类）：
  Cell 路径：按卡信息分类（card.nature / card.action / card.target 关键词）
  L3A 路径：按提示词分类（prompt 关键词）

注入维度（压缩维度的选择，非固定混合）：
  summary（执行流）——线性叙事（现有 build_context 行为，零改变）
  mer    （决策流）——群域图扩散骨架（关系视角：contradicts/depends_on）
  layered（恢复/复杂）——骨架 + 摘要（分层注入，token 预算内）

策略（memory.injection.strategy）：
  auto     ——按任务分类自动选择（默认）
  summary  ——强制摘要
  mer      ——强制 Mer 骨架
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 任务类型 ─────────────────────────────────────────────

TASK_EXECUTE = "execute"
TASK_DECIDE = "decide"
TASK_RESUME = "resume"
_TASKS = (TASK_EXECUTE, TASK_DECIDE, TASK_RESUME)

_EXECUTE_KEYWORDS = (
    "implement", "fix", "build", "write", "create", "refactor",
    "update", "add", "remove", "delete", "test", "run", "compile",
)
_DECIDE_KEYWORDS = (
    "review", "analyze", "compare", "conflict", "converge",
    "discuss", "decide", "evaluate", "assess", "audit", "design",
    "convention", "conference",
)
_RESUME_KEYWORDS = ("resume", "continue", "restore", "recall", "history")


def _match_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


def classify_task(card=None, prompt: str = "") -> str:
    """Classify the injection dimension by task source.

    Card wins (Cell path) — the card is the authoritative task spec;
    prompt is the fallback (L3A path).
    """
    if card is not None:
        try:
            nature = str(getattr(card, "nature", "") or "").lower()
            action = str(getattr(card, "action", "") or "").lower()
            target = str(getattr(card, "target", "") or "")
            hay = f"{nature} {action} {target}"
            if nature == "decision" or "decision" in hay or "issue" in nature:
                return TASK_DECIDE
            if _match_keywords(hay, _DECIDE_KEYWORDS):
                return TASK_DECIDE
            if _match_keywords(hay, _RESUME_KEYWORDS):
                return TASK_RESUME
            return TASK_EXECUTE  # execution cards default to summary
        except Exception:
            pass
    if _match_keywords(prompt, _DECIDE_KEYWORDS):
        return TASK_DECIDE
    if _match_keywords(prompt, _RESUME_KEYWORDS):
        return TASK_RESUME
    return TASK_EXECUTE


def resolve_strategy() -> str:
    """memory.injection.strategy — auto|summary|mer (default auto)."""
    try:
        from l1.kernel.settings import get_settings
        s = str(get_settings().get("memory.injection.strategy", "auto"))
        return s if s in ("auto", "summary", "mer") else "auto"
    except Exception:
        return "auto"


# ── 注入器 ────────────────────────────────────────────────

_MER_MAX_NODES = 30
_MER_NODE_CHARS = 120


class MemoryInjector:
    """Task-aware memory context builder (side-channel, zero-impact on default)."""

    def build_context(self, agent_id: str = "", *,
                      card=None, prompt: str = "",
                      max_tokens: int = 1024, memory=None) -> str:
        """Build the injection block for the current task.

        Returns the memory context string (empty when nothing applicable).
        Strategy resolution:
          auto → classify_task(card, prompt)
          summary → summary block only
          mer → Mer skeleton only
        """
        strategy = resolve_strategy()
        task = classify_task(card, prompt) if strategy == "auto" else (
            TASK_EXECUTE if strategy == "summary" else TASK_DECIDE)
        try:
            if task == TASK_DECIDE:
                mer = self._mer_block(agent_id, max_tokens)
                if mer:
                    return mer
                return self._summary_block(agent_id, max_tokens, memory)
            if task == TASK_RESUME:
                return self._layered_block(agent_id, max_tokens, memory)
            return self._summary_block(agent_id, max_tokens, memory)
        except Exception as e:
            logger.debug("memory_inject: build_context failed: %s", e)
            return self._summary_block(agent_id, max_tokens, memory)

    def _summary_block(self, agent_id: str, max_tokens: int,
                       memory=None) -> str:
        """Linear narrative — existing behavior (zero change)."""
        try:
            from l1.kernel.params.system import CONTEXT_BUILD_MAX_TOKENS
            m = memory
            if m is None:
                from l3.memory.memory import get_memory
                m = get_memory()
            if m is None:
                return ""
            budget = min(max_tokens, CONTEXT_BUILD_MAX_TOKENS)
            return m.build_context(agent_id, max_tokens=budget)
        except Exception:
            return ""

    def _mer_block(self, agent_id: str, max_tokens: int) -> str:
        """Mer skeleton — graph diffusion from recent memory seeds."""
        try:
            from l3.memory.memory_graph import get_graph
            from l3.memory.central_memory import get_center
            g = get_graph()
            if not g.enabled:
                return ""
            center = get_center()
            mem = center.get("l3a") or center.get(agent_id)
            seeds = []
            if mem is not None:
                recent = mem.recall(agent_id=agent_id or None,
                                    rings=[1, 2, 3], limit=5)
                seeds = [e.id for e in recent if e and e.id]
            if not seeds:
                return ""
            gr = g.recall(seeds, depth=2, limit=_MER_MAX_NODES)
            if not gr["nodes"]:
                return ""
            by_rel: dict[str, list[str]] = {}
            for ed in gr.get("edges", []):
                key = ed.get("relation", "related")
                by_rel.setdefault(key, []).append(
                    f"{ed.get('from_id', '')[:8]}→{ed.get('to_id', '')[:8]}")
            lines = ["=== Memory Relations (Mer) ==="]
            for rel, pairs in by_rel.items():
                lines.append(f"- {rel}: {', '.join(pairs[:_MER_MAX_NODES])}")
            if gr["nodes"]:
                lines.append(f"- nodes: {len(gr['nodes'])} reached via diffusion")
            text = "\n".join(lines)
            return text[:max_tokens * 4]
        except Exception:
            return ""

    def _layered_block(self, agent_id: str, max_tokens: int,
                       memory=None) -> str:
        """Skeleton + narrative (layered injection, budget-aware)."""
        mer = self._mer_block(agent_id, max_tokens // 2)
        summary = self._summary_block(agent_id, max_tokens // 2, memory)
        parts = [p for p in (mer, summary) if p]
        return "\n\n".join(parts)


def build_context(agent_id: str = "", *, card=None, prompt: str = "",
                  max_tokens: int = 1024, memory=None) -> str:
    """Module-level convenience — task-aware injection."""
    return MemoryInjector().build_context(
        agent_id, card=card, prompt=prompt, max_tokens=max_tokens, memory=memory)
