"""Prompt Engine — context assembly + sliding window + layered prompts

Three-layer architecture:
  1. ContextAssembler  — assembles context from memory ring / LSP diagnostics / file summaries / conversation history
  2. WindowManager     — priority sliding window (high-value retained, low-value evicted)
  3. PromptBuilder     — role system prompt + task prompt + constraint prompt → merged output

API:
  POST /api/prompt/build      — build full prompt (assemble context + merge layers)
  POST /api/prompt/template   — get/test prompt template
  POST /api/prompt/context    — assemble context only (for frontend preview)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_STEPS
from l1.kernel.params.system import KERNEL_VERSION, PRAXIS_CODENAME

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 1. Data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class ContextItem:
    """Context fragment with priority metadata."""
    content: str
    source: str                # "memory_ring" | "lsp_diag" | "file_summary" | "history"
    priority: float = 0.5      # 0.0 ~ 1.0
    tokens: int = 0
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content": self.content[:200],
            "source": self.source,
            "priority": self.priority,
            "tokens": self.tokens,
            "tags": self.tags,
        }


@dataclass
class PromptTemplate:
    """Layered prompt template."""
    role: str = ""             # Role prompt: "You are a senior Python engineer..."
    task: str = ""             # Task prompt: "Fix the bug in login.py..."
    constraints: str = ""      # Constraint prompt: "Do not modify tests..."
    context: str = ""          # Assembled context
    tools: str = ""            # Available tool description

    def build(self) -> str:
        parts = []
        if self.role:
            parts.append(self.role)
        if self.task:
            parts.append(f"\n## Task\n{self.task}")
        if self.context:
            parts.append(f"\n## Context\n{self.context}")
        if self.tools:
            parts.append(f"\n## Tools\n{self.tools}")
        if self.constraints:
            parts.append(f"\n## Constraints\n{self.constraints}")
        return "\n\n".join(parts)

    def estimate_tokens(self) -> int:
        return len(self.build()) // 4

    def to_dict(self) -> dict:
        return {
            "role": self.role[:100],
            "task": self.task[:100],
            "constraints": self.constraints[:100],
            "context_len": len(self.context),
            "tools": self.tools[:100],
            "total_tokens": self.estimate_tokens(),
        }


# ══════════════════════════════════════════════════════════════════════
# 2. Context Assembler
# ══════════════════════════════════════════════════════════════════════


class ContextAssembler:
    """Assemble LLM context from multiple sources."""

    def __init__(self, max_tokens: int = 4096):
        self._max_tokens = max_tokens
        self._items: list[ContextItem] = []

    def add_memory_context(self, agent_id: str = "") -> int:
        """Load recent context from memory ring."""
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            ring_context = mem.build_context(agent_id, max_tokens=self._max_tokens // 2)
            if ring_context:
                item = ContextItem(
                    content=ring_context,
                    source="memory_ring",
                    priority=0.8,
                    tokens=len(ring_context) // 4,
                    tags=["memory"],
                )
                self._items.append(item)
                return item.tokens
        except Exception as e:
            logger.warning("prompt_engine: memory context: %s", e)
        return 0

    def add_file_context(self, file_paths: list[str] = None,
                         max_chars_per_file: int = 2000) -> int:
        """Load summary context for specified files."""
        if not file_paths:
            return 0
        total = 0
        for path in file_paths[:5]:  # Max 5 files
            try:
                from pathlib import Path
                p = Path(path)
                if not p.exists():
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                snippet = content[:max_chars_per_file]
                item = ContextItem(
                    content=f"=== {path} ===\n{snippet}",
                    source="file_summary",
                    priority=0.7,
                    tokens=len(snippet) // 4,
                    tags=["file", path],
                )
                self._items.append(item)
                total += item.tokens
            except Exception as e:
                logger.warning("prompt_engine: file context: %s: %s", path, e)
        return total

    def add_lsp_diagnostics(self, file_path: str = "") -> int:
        """Add diagnostics context from LSP."""
        try:
            from l4.lsp import LocalAnalyzer
            analyzer = LocalAnalyzer()
            diag = analyzer.type_check()
            if diag and diag.get("diagnostics"):
                content = json.dumps(diag["diagnostics"][:20], indent=1)
                item = ContextItem(
                    content=f"=== Diagnostics ===\n{content}",
                    source="lsp_diag",
                    priority=0.9 if diag.get("errors") else 0.3,
                    tokens=len(content) // 4,
                    tags=["lsp", "diagnostics"],
                )
                self._items.append(item)
                return item.tokens
        except Exception as e:
            logger.debug("prompt_engine: lsp diagnostics: %s", e)
        return 0

    def add_history_context(self, history: list[dict] = None,
                            max_messages: int = 10) -> int:
        """Load context from conversation history."""
        if not history:
            return 0
        recent = history[-max_messages:]
        lines = []
        for msg in recent:
            role = msg.get("role", "?")
            content = (msg.get("content", "") or "")[:200]
            lines.append(f"[{role}] {content}")
        content = "\n".join(lines)
        item = ContextItem(
            content=content,
            source="history",
            priority=0.6,
            tokens=len(content) // 4,
            tags=["history"],
        )
        self._items.append(item)
        return item.tokens

    def add_string(self, content: str, source: str = "custom",
                   priority: float = 0.5, tags: list[str] = None) -> int:
        """Add custom context fragment."""
        item = ContextItem(
            content=content,
            source=source,
            priority=priority,
            tokens=len(content) // 4,
            tags=tags or [],
        )
        self._items.append(item)
        return item.tokens

    def assemble(self, max_tokens: int = 0) -> str:
        """Sort by priority + sliding window truncation → assemble context string."""
        budget = max_tokens or self._max_tokens
        if not self._items:
            return ""

        # Sort by descending priority
        sorted_items = sorted(self._items, key=lambda x: -x.priority)

        parts = []
        used = 0
        for item in sorted_items:
            if used + item.tokens > budget:
                continue
            parts.append(item.content)
            used += item.tokens

        result = "\n\n".join(parts)
        # Fallback character-level truncation
        max_chars = budget * 4
        if len(result) > max_chars:
            result = result[:max_chars] + "\n...[truncated]"
        return result

    def stats(self) -> dict:
        return {
            "total_items": len(self._items),
            "sources": list(set(i.source for i in self._items)),
            "estimated_tokens": sum(i.tokens for i in self._items),
        }

    def reset(self) -> None:
        self._items.clear()


# ══════════════════════════════════════════════════════════════════════
# 3. Prompt Builder
# ══════════════════════════════════════════════════════════════════════


class PromptBuilder:
    """Layered Prompt Builder."""

    # Default system prompt template (from kernel.prompts)
    SYSTEM_TEMPLATES: dict[str, str] = {}  # loaded lazily

    CONSTRAINT_TEMPLATES: dict[str, str] = {}  # loaded lazily

    def __init__(self):
        self._custom_templates: dict[str, str] = {}

    def build(self, role: str = "default", task: str = "",
              context: str = "", tools_desc: str = "",
              constraints: list[str] = None,
              variables: dict[str, Any] = None) -> PromptTemplate:
        """Build complete layered prompt."""
        vars = variables or {}
        vars.setdefault("version", KERNEL_VERSION)
        vars.setdefault("codename", PRAXIS_CODENAME)
        vars.setdefault("max_steps", AGENT_LOOP_DEFAULT_STEPS)

        # Role prompt (from kernel.prompts registry)
        from l1.kernel.prompts import get_prompt as _gp
        role_key = role if (role in self._custom_templates or _gp(f"prompt_engine.system.{role}", "")) else "default"
        role_prompt = (self._custom_templates.get(role)
                       or _gp(f"prompt_engine.system.{role_key}",
                              _gp("prompt_engine.system.default", ""))).format(**vars)

        # Constraint prompt (from kernel.prompts registry)
        constraint_parts = []
        for key in (constraints or []):
            tpl = _gp(f"prompt_engine.constraint.{key}", key)
            constraint_parts.append(tpl.format(**vars))

        return PromptTemplate(
            role=role_prompt,
            task=task,
            context=context,
            tools=tools_desc,
            constraints="\n".join(constraint_parts) if constraint_parts else "",
        )

    def register_template(self, name: str, template: str) -> dict:
        """Register custom system prompt template."""
        self._custom_templates[name] = template
        return {"success": True, "name": name, "preview": template[:80]}

    def list_templates(self) -> dict:
        templates = dict(self._custom_templates)
        return {
            "success": True,
            "count": len(templates),
            "templates": {k: v[:80] for k, v in templates.items()},
        }


# ══════════════════════════════════════════════════════════════════════
# 4. PromptEngine (facade)
# ══════════════════════════════════════════════════════════════════════


class PromptEngine:
    """PromptEngine — Unified entry for context assembly + sliding window + layered prompts."""

    def __init__(self, max_context_tokens: int = 4096):
        self._assembler = ContextAssembler(max_tokens=max_context_tokens)
        self._builder = PromptBuilder()
        self._lock = threading.RLock()

    def build_prompt(self, task: str = "", role: str = "default",
                     agent_id: str = "", file_paths: list[str] = None,
                     history: list[dict] = None,
                     constraints: list[str] = None,
                     include_diagnostics: bool = False,
                     tools_desc: str = "",
                     max_tokens: int = 0) -> dict:
        """One-stop prompt build: assemble context → merge layers → return full prompt."""
        with self._lock:
            self._assembler.reset()

            # 1. Load memory context
            if agent_id:
                self._assembler.add_memory_context(agent_id)

            # 2. Load file context
            if file_paths:
                self._assembler.add_file_context(file_paths)

            # 3. Load LSP diagnostics
            if include_diagnostics:
                for fp in (file_paths or [])[:3]:
                    self._assembler.add_lsp_diagnostics(fp)

            # 4. Load conversation history
            if history:
                self._assembler.add_history_context(history)

            # 5. Assemble
            context = self._assembler.assemble(max_tokens=max_tokens)

            # 6. Build layered prompt
            pt = self._builder.build(
                role=role,
                task=task,
                context=context,
                tools_desc=tools_desc,
                constraints=constraints,
                variables={"max_steps": AGENT_LOOP_DEFAULT_STEPS},
            )

            full = pt.build()

        return {
            "success": True,
            "prompt": full,
            "estimated_tokens": pt.estimate_tokens(),
            "context_stats": self._assembler.stats(),
            "template": pt.to_dict(),
        }

    def build_context_only(self, agent_id: str = "",
                           file_paths: list[str] = None,
                           history: list[dict] = None,
                           include_diagnostics: bool = False,
                           max_tokens: int = 0) -> dict:
        """Assemble context only, without building full prompt (for frontend preview)."""
        with self._lock:
            self._assembler.reset()
            if agent_id:
                self._assembler.add_memory_context(agent_id)
            if file_paths:
                self._assembler.add_file_context(file_paths)
            if include_diagnostics:
                for fp in (file_paths or [])[:3]:
                    self._assembler.add_lsp_diagnostics(fp)
            if history:
                self._assembler.add_history_context(history)

            context = self._assembler.assemble(max_tokens=max_tokens)

        return {
            "success": True,
            "context": context,
            "stats": self._assembler.stats(),
        }

    def get_templates(self) -> dict:
        return self._builder.list_templates()

    def register_template(self, name: str, template: str) -> dict:
        return self._builder.register_template(name, template)


# ══════════════════════════════════════════════════════════════════════
# 5. Global Singleton
# ══════════════════════════════════════════════════════════════════════

_engine: PromptEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> PromptEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PromptEngine()
    return _engine


# ══════════════════════════════════════════════════════════════════════
# 6. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_prompt_build(body: dict | None = None) -> dict:
    """POST /api/prompt/build — Build full prompt"""
    b = body or {}
    return get_engine().build_prompt(
        task=b.get("task", ""),
        role=b.get("role", "default"),
        agent_id=b.get("agent_id", ""),
        file_paths=b.get("file_paths"),
        history=b.get("history"),
        constraints=b.get("constraints"),
        include_diagnostics=b.get("include_diagnostics", False),
        tools_desc=b.get("tools_desc", ""),
        max_tokens=b.get("max_tokens", 0),
    )


def handle_prompt_context(body: dict | None = None) -> dict:
    """POST /api/prompt/context — Assemble context only"""
    b = body or {}
    return get_engine().build_context_only(
        agent_id=b.get("agent_id", ""),
        file_paths=b.get("file_paths"),
        history=b.get("history"),
        include_diagnostics=b.get("include_diagnostics", False),
        max_tokens=b.get("max_tokens", 0),
    )


def handle_prompt_templates(body: dict | None = None) -> dict:
    """GET /api/prompt/templates — List all prompt templates"""
    return get_engine().get_templates()


def handle_prompt_template_register(body: dict | None = None) -> dict:
    """POST /api/prompt/template — Register custom template"""
    b = body or {}
    name = b.get("name", "")
    template = b.get("template", "")
    if not name or not template:
        return {"success": False, "error": "name and template required"}
    return get_engine().register_template(name, template)


# ── Route Registration ──

PROMPT_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/prompt/build", handle_prompt_build, "Build full prompt with context assembly"),
    ("POST", "/api/prompt/context", handle_prompt_context, "Assemble context only (preview)"),
    ("GET", "/api/prompt/templates", handle_prompt_templates, "List prompt templates"),
    ("POST", "/api/prompt/template", handle_prompt_template_register, "Register custom template"),
]
