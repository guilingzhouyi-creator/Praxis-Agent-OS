"""MemoryInjector — task-aware dynamic memory injection (side-channel).

Activation paths (classified by task source):
  Cell path: classify by card metadata (card.nature / card.action / card.target keywords)
  L3A path:  classify by prompt keywords

Injection dimensions (dimension selected by task, not a fixed mix):
  summary (execution) — linear narrative (existing build_context behavior, zero change)
  mer    (decision)   — swarm-domain graph diffusion skeleton (relation view: contradicts/depends_on)
  layered (resume/complex) — skeleton + summary (layered injection, token-budget aware)

Strategy (memory.injection.strategy):
  auto     — auto-select by task classification (default)
  summary  — force summary
  mer      — force Mer skeleton
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Task types ────────────────────────────────────────────

TASK_EXECUTE = "execute"
TASK_DECIDE = "decide"
TASK_RESUME = "resume"

_DECIDE_KEYWORDS = (
    "review",
    "analyze",
    "compare",
    "conflict",
    "converge",
    "discuss",
    "decide",
    "evaluate",
    "assess",
    "audit",
    "design",
    "convention",
    "conference",
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
            logger.debug("memory_inject: task type classification failed, falling back", exc_info=True)
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


# ── Injector ──────────────────────────────────────────────

_MER_MAX_NODES = 30


class MemoryInjector:
    """Task-aware memory context builder (side-channel, zero-impact on default)."""

    def build_context(
        self, agent_id: str = "", *, card=None, prompt: str = "", max_tokens: int = 1024, memory=None
    ) -> str:
        """Build the injection block for the current task.

        Returns the memory context string (empty when nothing applicable).
        Strategy resolution:
          auto → classify_task(card, prompt)
          summary → summary block only
          mer → Mer skeleton only
        """
        strategy = resolve_strategy()
        task = (
            classify_task(card, prompt)
            if strategy == "auto"
            else (TASK_EXECUTE if strategy == "summary" else TASK_DECIDE)
        )
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

    def _summary_block(self, agent_id: str, max_tokens: int, memory=None) -> str:
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
            from l3.memory.central_memory import get_center
            from l3.memory.memory_graph import get_graph

            g = get_graph()
            if not g.enabled:
                return ""
            center = get_center()
            mem = center.get("l3a") or center.get(agent_id)
            seeds = []
            if mem is not None:
                recent = mem.recall(agent_id=agent_id or None, rings=[1, 2, 3], limit=5)
                seeds = [e.id for e in recent if e and e.id]
            if not seeds:
                return ""
            gr = g.recall(seeds, depth=2, limit=_MER_MAX_NODES)
            if not gr["nodes"]:
                return ""
            by_rel: dict[str, list[str]] = {}
            for ed in gr.get("edges", []):
                key = ed.get("relation", "related")
                by_rel.setdefault(key, []).append(f"{ed.get('from_id', '')[:8]}→{ed.get('to_id', '')[:8]}")
            lines = ["=== Memory Relations (Mer) ==="]
            for rel, pairs in by_rel.items():
                lines.append(f"- {rel}: {', '.join(pairs[:_MER_MAX_NODES])}")
            if gr["nodes"]:
                lines.append(f"- nodes: {len(gr['nodes'])} reached via diffusion")
            text = "\n".join(lines)
            return text[: max_tokens * 4]
        except Exception:
            return ""

    def _layered_block(self, agent_id: str, max_tokens: int, memory=None) -> str:
        """Skeleton + narrative (layered injection, budget-aware)."""
        mer = self._mer_block(agent_id, max_tokens // 2)
        summary = self._summary_block(agent_id, max_tokens // 2, memory)
        parts = [p for p in (mer, summary) if p]
        return "\n\n".join(parts)


def build_context(agent_id: str = "", *, card=None, prompt: str = "", max_tokens: int = 1024, memory=None) -> str:
    """Module-level convenience — task-aware injection."""
    return MemoryInjector().build_context(agent_id, card=card, prompt=prompt, max_tokens=max_tokens, memory=memory)
