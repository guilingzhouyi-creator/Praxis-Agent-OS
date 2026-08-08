"""Session — durable session entity with history, inbox, epoch, and lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

from l1.kernel.params.system import (
    HASH_TRUNC_SHORTEST,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LOG_TRUNC_500,
    LOG_TRUNC_2000,
)
from l3.error_bus import capture

from . import archive as _archive
from . import params as _p
from .context import ContextEpoch, ContextRegistry
from .inbox import PromptInbox
from .model import L3AModelConfig
from .session_ask import SessionAskMixin
from .session_compress import SessionCompressMixin
from .session_history import Message, Page, SessionHistory, _est_tokens  # noqa: F401 — re-export
from .session_prompt import SessionPromptMixin
from .task_table import SessionTaskTable

logger = logging.getLogger(__name__)


class Session(SessionPromptMixin, SessionAskMixin, SessionCompressMixin):
    """Live L3A session — history, inbox, task table, ask state, model config.

    Cross-mixin protocol methods are delegated explicitly on the concrete
    class so real implementations always win over the ``NotImplementedError``
    protocol stubs declared on the mixins (mypy sees the concrete
    delegations; the runtime never hits a stub).
    """

    # ── Cross-mixin delegation ──

    def _continue_after_ask(self, text: str) -> dict:
        """Resume the loop after clarification answers (SessionAskMixin)."""
        return SessionAskMixin._continue_after_ask(self, text)

    def _report_stats(self) -> None:
        """Emit token/pressure/turn metrics (SessionPromptMixin)."""
        SessionPromptMixin._report_stats(self)

    def _resolve_limits(self) -> dict:
        """Resolve step/time/turn limits (SessionPromptMixin)."""
        return SessionPromptMixin._resolve_limits(self)

    def _resolve_model_config(self) -> dict:
        """Resolve effective model config (SessionPromptMixin)."""
        return SessionPromptMixin._resolve_model_config(self)

    def context_stats(self) -> dict:
        """Compute session context pressure (SessionPromptMixin)."""
        return SessionPromptMixin.context_stats(self)

    def __init__(
        self,
        session_id: str,
        title: str,
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ):
        self.id = session_id
        self.title = title
        self.user_id = user_id
        self.created_at = time.time()
        self.last_active_at = time.time()
        self.closed_at: float | None = None
        self.turn_count = 0
        self.card_count = 0
        self.status = "active"
        self.history = SessionHistory()
        self.model_config = model_config or L3AModelConfig()
        self.inbox = PromptInbox(session_id)
        self.epoch: ContextEpoch | None = None
        self.registry = registry
        self._lock = threading.RLock()
        self._loop: Any = None
        self._base_system: str = ""
        self._pmu: Any = None
        self._cell_id: str = "l3a"
        self.max_turns: int = 0
        self._model_spec_cache: dict | None = None
        self._subscribed_cards: set[str] = set()
        self.tasks: SessionTaskTable = SessionTaskTable(session_id)
        self._resumed_from: str = ""
        self._resume_todos: list[dict] = []
        self._ask: Any = None

    @classmethod
    def create(
        cls,
        title: str = "",
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ) -> Session:
        """Create a new session with a fresh epoch and reloaded inbox; return it."""
        sid = f"l3a-{uuid.uuid4().hex[: _p.SID_LENGTH]}"
        title = title or f"Session {time.strftime('%Y-%m-%d %H:%M')}"
        inst = cls(session_id=sid, title=title, model_config=model_config, registry=registry, user_id=user_id)
        inst.epoch = ContextEpoch.create(registry or ContextRegistry())
        inst.inbox.reload()
        logger.info("l3a session: created %s — %s", sid, title)
        try:
            from l3.bus.log import get_service as _ls

            _ls().info(f"Session created: {title}", service="l3a", agent_id=_p.AGENT_ID, task_id=sid)
        except Exception:
            logger.debug("l3a.session: log service unavailable at session create, skipped", exc_info=True)
        return inst

    @classmethod
    def resume_from_archive(
        cls,
        archived_session_id: str,
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
    ) -> Session | None:
        """Resume an archived session from R4 — new live session seeded with
        the archived metadata, transcript, task table, and TODO list."""
        blob = _archive.load_session_blob(archived_session_id)
        if not blob:
            return None
        meta = blob.get("metadata", {})
        transcript = blob.get("transcript", [])
        tasks_data = meta.get("tasks", {})
        todos_data = meta.get("todos", [])

        inst = cls(
            session_id=f"l3a-{uuid.uuid4().hex[: _p.SID_LENGTH]}",
            title=(meta.get("title") or "Resumed session") + " (resumed)",
            model_config=model_config,
            registry=registry,
        )
        inst.epoch = ContextEpoch.create(registry or ContextRegistry())
        inst.inbox.reload()
        inst.turn_count = int(meta.get("turn_count", 0))
        inst.card_count = int(meta.get("card_count", 0))
        inst.tasks.from_dict(tasks_data or {})
        inst._resumed_from = archived_session_id
        if todos_data:
            try:
                inst._resume_todos = list(todos_data)
            except Exception:
                logger.debug("l3a.session: resume todos parse failed, ignored", exc_info=True)
        if transcript:
            for m in transcript:
                try:
                    inst.history.append(
                        Message(
                            id=m.get("id", f"r-{uuid.uuid4().hex[:HASH_TRUNC_SHORTEST]}"),
                            role=m.get("role", "user"),
                            content=m.get("content", ""),
                            tool_calls=m.get("tool_calls", []),
                            created_at=float(m.get("created_at") or time.time()),
                            metadata=m.get("metadata", {}),
                        )
                    )
                except Exception:
                    continue
        logger.info("l3a session: resumed %s → %s (%d msgs)", archived_session_id, inst.id, inst.history.count())
        # ── R5 swarm-domain graph: diffusion recall of related context on restore (when graph enabled) ──
        try:
            from l3.memory.central_memory import get_l3a_memory as _glm
            from l3.memory.memory_graph import get_graph as _gg

            g = _gg()
            if g.enabled:
                mem = _glm()
                recent = mem.recall(agent_id=_p.AGENT_ID, rings=[1, 2, 3], limit=5)
                seeds = [e.id for e in recent if e and e.id]
                if seeds:
                    gr = g.recall(seeds, depth=2, limit=10)
                    if gr["nodes"]:
                        all_entries = mem.recall(agent_id=_p.AGENT_ID, rings=[1, 2, 3], limit=50)
                        by_id = {e.id: e for e in all_entries}
                        ctx_lines = []
                        for nid in gr["nodes"][:6]:
                            e = by_id.get(nid)
                            if e and e.content and e.id not in seeds:
                                ctx_lines.append(f"- [{e.entry_type}] {e.content[:LOG_TRUNC_200]}")
                        if ctx_lines:
                            inst.history.append(
                                Message(
                                    id=f"graph-{uuid.uuid4().hex[:HASH_TRUNC_SHORTEST]}",
                                    role="system",
                                    content=("Related context from memory graph:\n" + "\n".join(ctx_lines)),
                                    metadata={"graph_recall": True},
                                )
                            )
        except Exception:
            logger.debug("l3a session: resume graph recall failed")
        return inst

    def set_pmu(self, pmu: Any) -> None:
        """Attach the PMU instance used for session metrics."""
        self._pmu = pmu

    _ctx_window_cache: int = 0

    def close(self) -> dict:
        """Close the session, archive it, and return the close result dict."""
        with self._lock:
            if self.status != "active":
                return {"success": False, "error": "already closed"}
            sid = self.id
            title = self.title
            self.status = "closed"
            self.closed_at = time.time()
            self.last_active_at = time.time()
            # Capture TODO state BEFORE nulling the loop
            try:
                todo_state = self.todos()
            except Exception:
                capture("l3a session: todo state capture failed", error_code="E_L3A_SESSION", component="l3a")
                todo_state = {"tasks": []}
            self._loop = None
            ctx = self.history.to_context_trail()
            self.history.clear()
        # Unsubscribe all card completion callbacks (closed session must not
        # receive zombie card results)
        if self._subscribed_cards:
            try:
                from l3.card.card_registry import get_registry

                reg = get_registry()
                for cid in self._subscribed_cards:
                    reg.unsubscribe(cid, self._on_card_completed)
            except Exception:
                capture("l3a session: unsubscribe failed on close", error_code="E_L3A_SESSION", component="l3a")
                logger.debug("l3a session: unsubscribe failed on close")
            self._subscribed_cards.clear()
        # I/O outside lock
        metadata = {
            "session_id": sid,
            "title": title,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "turn_count": self.turn_count,
            "card_count": self.card_count,
            "model_spec": "l3a",
            "tags": ["l3a", "session"],
            "tasks": self.tasks.to_dict(),
            "todos": todo_state.get("tasks", []),
        }
        _archive.store_session(sid, metadata, ctx)
        logger.info("l3a session: closed %s — %s (%d turns)", sid, title, self.turn_count)
        try:
            from l3.bus.log import get_service as _ls

            _ls().info(f"Session closed: {title}", service="l3a", agent_id=_p.AGENT_ID, task_id=sid)
        except Exception:
            logger.debug("l3a.session: log service unavailable at session close, skipped", exc_info=True)
        return {"success": True, "session_id": sid, "title": title}

    def messages(self, cursor: str | None = None, limit: int = _p.SESSION_PAGE_SIZE) -> Page:
        """Return a Page of session messages after the given cursor."""
        return self.history.messages_page(cursor=cursor, limit=limit)

    # ── Session TODO table (LLM task list via todowrite tool) ──

    def todos(self) -> dict:
        """Query the session's TodoTracker state (LLM task list)."""
        if not self._loop:
            return {"status": "open", "total_tasks": 0, "by_status": {}, "tasks": [], "note": "loop not created yet"}
        t = self._loop._todo
        stats = t.stats()
        tasks = []
        if hasattr(t, "_items"):
            tasks = [dict(item) for item in t._items]
        stats["tasks"] = tasks
        return stats

    def todos_update(self, content: str, status: str) -> dict:
        """Update a session TODO item (delegate to todowrite handler)."""
        if not self._loop:
            return {"success": False, "error": "loop not created yet"}
        r = self._loop._todo.update(content, status)
        if r.startswith("error"):
            return {"success": False, "error": r}
        return {"success": True, "status": r, "content": content}

    # ── Manual context compression ──

    def info(self) -> dict:
        """Return the session state as a dict for display."""
        with self._lock:
            epoch_info = {}
            if self.epoch:
                epoch_info = {
                    "epoch_id": self.epoch.id,
                    "epoch_created": self.epoch.created_at,
                    "baseline_chars": len(self.epoch.baseline),
                    "snapshot_keys": list(self.epoch.snapshot.keys()),
                    "turn_in_epoch": self.epoch.turn_count,
                }
            return {
                "session_id": self.id,
                "title": self.title,
                "status": self.status,
                "created_at": self.created_at,
                "last_active_at": self.last_active_at,
                "closed_at": self.closed_at,
                "turn_count": self.turn_count,
                "card_count": self.card_count,
                "message_count": self.history.count(),
                "inbox_pending": len(self.inbox.pending()),
                "model": self.model_config.show(),
                "epoch": epoch_info,
                "context": self.context_stats(),
                "tasks": {
                    "pending": self.tasks.pending_count(),
                    "total": len(self.tasks.all()),
                },
                "ask": self._ask.to_dict() if self._ask else None,
            }

    def _on_card_completed(self, card_id: str, state: str, result: dict) -> None:
        """Card completion callback — inject result into session history (closed loop)."""
        if self.status != "active":
            return
        title = ""
        try:
            from l3.card.card_registry import get_registry

            rec = get_registry().get(card_id)
            if rec and rec.summary:
                title = rec.summary.title or card_id
        except Exception:
            logger.debug("l3a.session: card title lookup failed, using card_id", exc_info=True)
        summary = result.get("summary", "")
        if not summary:
            summary = result.get("answer", "")
        if not summary:
            summary = str(result)[:LOG_TRUNC_200]
        # Convention convergence → distill L3A summary into dedicated store
        if result.get("issue_card_id") or result.get("doc_path"):
            self._distill_convention_summary(card_id, title, result)
        text = f"Card {card_id} ({title}) → {state}" + (f": {summary}" if summary else "")
        self.tasks.update(card_id, state, result)
        with self._lock:
            self.history.append(
                Message(
                    id=f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORTEST]}",
                    role="system",
                    content=text,
                    metadata={"card_id": card_id, "card_state": state},
                )
            )
        logger.info("l3a session %s: card %s → %s", self.id, card_id, state)

    def _distill_convention_summary(self, card_id: str, title: str, result: dict) -> None:
        """Distill a convention convergence into the L3A summary store.

        Reads the anchored doc index (issues/decisions/agents), performs
        second-pass dedup (overlap detection on top of in-Cell dedup), and
        persists the distilled summary to L3A's dedicated memory space.
        """
        issue_id = result.get("issue_card_id", "")
        if not issue_id:
            return
        try:
            from .helpers import l3a_convention_handler

            idx_r = l3a_convention_handler({"issue_id": issue_id, "action": "index"})
            if not idx_r.get("success"):
                logger.debug("l3a: summary distill index failed: %s", idx_r.get("error"))
                return
            idx = idx_r.get("index", {})
            issues = []
            for it in idx.get("issues", []):
                block = l3a_convention_handler({"issue_id": issue_id, "anchor": it.get("anchor", "")})
                answer = ""
                if block.get("success"):
                    for ln in block["content"].splitlines():
                        if "**Answer**" in ln:
                            answer = ln.split("):", 1)[-1].strip() if "):" in ln else ln
                issues.append(
                    {
                        "anchor": it.get("anchor", ""),
                        "title": it.get("title", ""),
                        "domain": it.get("domain", ""),
                        "assigned_to": it.get("assigned_to", ""),
                        "status": it.get("status", ""),
                        "answer": answer,
                    }
                )
            decisions = []
            for d in idx.get("decisions", []):
                block = l3a_convention_handler({"issue_id": issue_id, "anchor": d.get("anchor", "")})
                text = ""
                if block.get("success"):
                    for ln in block["content"].splitlines():
                        if ln.startswith("- "):
                            text = ln[2:].strip()
                decisions.append({"anchor": d.get("anchor", ""), "text": text})

            from .summaries import build_summary, get_store

            domain = ""
            if issues and issues[0].get("domain"):
                domain = issues[0]["domain"]
            s = build_summary(
                issue_id=issue_id,
                source_card_id=card_id,
                title=title,
                domain=domain,
                agents=idx.get("participants", []),
                issues=issues,
                decisions=decisions,
                doc_path=result.get("doc_path", ""),
                archive_ref=result.get("archive_ref", ""),
                session_id=self.id,
            )
            get_store().save(s)
        except Exception as e:
            capture(
                "l3a: summary distill failed", error_code="E_L3A_SESSION", component="l3a", context={"error": str(e)}
            )
            logger.debug("l3a: summary distill failed: %s", e)

    def _ensure_epoch(self) -> None:
        if self.epoch is not None:
            return
        restored = ContextEpoch.restore()
        if restored:
            self.epoch = restored
        else:
            self.epoch = ContextEpoch.create(self.registry or ContextRegistry())

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        from l3.agent.agent_loop import AgentLoop

        from .helpers import build_l3a_prompt

        self._base_system = build_l3a_prompt(user_id=self.user_id)
        try:
            from l1.kernel.paths import get_paths as _gp

            todo_path = os.path.join(_gp().data_dir, f"l3a_todos_{self.id}.json")
        except Exception:
            capture("l3a session: todo_path resolve failed", error_code="E_L3A_SESSION", component="l3a")
            todo_path = f".praxis/l3a_todos_{self.id}.json"
        self._loop = AgentLoop(
            task="",
            agent_id=_p.AGENT_ID,
            role="l3a",
            system=self._base_system,
            prompt_key="l3a.parse_system",
            cell_id=self._cell_id,
            todo_path=todo_path,
        )
        # Seed resumed TODO items into the fresh TodoTracker
        if self._resume_todos:
            try:
                self._loop._todo.load(self._resume_todos)
            except Exception:
                capture("l3a session: resume todos seed failed", error_code="E_L3A_SESSION", component="l3a")
                logger.debug("l3a session: resume todos seed failed")
        from .helpers import cardwrite_handler

        def _session_cardwrite(args: dict, agent_id: str = "") -> dict:
            """Session-scoped cardwrite: create card + track + subscribe to completion."""
            # Attach the session's user so the profile side-channel can
            # reference the user's established preferences on the card.
            if self.user_id and "user_id" not in args:
                args = dict(args)
                args["user_id"] = self.user_id
            r = cardwrite_handler(args, agent_id)
            if r.get("success"):
                cid = r.get("card_id", "")
                self.card_count += 1
                self._subscribed_cards.add(cid)
                self.tasks.track(cid, title=args.get("title", cid), turn=self.turn_count)
                try:
                    from l3.card.card_registry import get_registry

                    get_registry().subscribe(cid, self._on_card_completed)
                except Exception:
                    capture(
                        "l3a session: card subscribe failed",
                        error_code="E_L3A_SESSION",
                        component="l3a",
                        context={"card_id": cid},
                    )
                    logger.debug("l3a session: card subscribe failed for %s", cid)
            return r

        self._loop.add_tool(
            "cardwrite",
            "Create and submit a structured card.",
            {
                "nature": "string",
                "title": "string",
                "description": "string",
                "columns": "dict",
                "priority": "int",
                "phases": "list",
            },
            _session_cardwrite,
            parallel_safe=False,
        )
        from .subagent import l3a_collect_handler, l3a_peek_handler, l3a_spawn_handler

        self._loop.add_tool(
            "l3a_spawn",
            "Spawn an async subagent. Returns task_id immediately.",
            {"spec": "string", "task": "string", "group": "string"},
            l3a_spawn_handler,
            parallel_safe=True,
        )
        self._loop.add_tool(
            "l3a_collect",
            "Wait for a group of subagents and collect results.",
            {"group": "string", "timeout": "number"},
            l3a_collect_handler,
            parallel_safe=False,
        )
        self._loop.add_tool(
            "l3a_result",
            "Peek at a single subagent result (non-blocking).",
            {"task_id": "string"},
            l3a_peek_handler,
            parallel_safe=True,
        )
        from .helpers import l3a_convention_handler

        self._loop.add_tool(
            "l3a_convention",
            "Navigate a converged convention document. First call action=index "
            "for the issue/decision catalog, then fetch specific blocks: "
            "anchor=I-2 (issue), anchor=D-1 (decision), or agent=agent-b "
            "(all lines for that agent). max_chars bounds reads.",
            {"issue_id": "string", "action": "string", "anchor": "string", "agent": "string", "max_chars": "int"},
            l3a_convention_handler,
            parallel_safe=True,
        )
        from .helpers import l3a_summary_handler

        self._loop.add_tool(
            "l3a_summary",
            "Query L3A deliberation-memory: action=latest [domain] for recent "
            "convention distillations, action=search <query> for keyword hits, "
            "action=get <issue_id> for one full summary with overlap notes.",
            {"action": "string", "issue_id": "string", "query": "string", "domain": "string", "limit": "int"},
            l3a_summary_handler,
            parallel_safe=True,
        )
        from .ask import ask_handler as _l3a_ask_handler

        self._loop.add_tool(
            "l3a_ask",
            "Ask the user to clarify the request. Call when the user's prompt "
            "is ambiguous or critical information is missing (target platform, "
            "scope, constraints, acceptance criteria, etc.). Pass up to "
            f"{_p.ASK_MAX_QUESTIONS} questions as a list of dicts "
            "{question, options?, required?}. Execution pauses until the user "
            "answers in the chat window; answers are injected back before "
            "resuming.",
            {"questions": "list"},
            lambda args, agent_id="": _l3a_ask_handler(self, args, agent_id),
            parallel_safe=False,
        )
        if self._pmu:
            try:
                self._loop.set_pmu(self._pmu)
            except Exception:
                capture("l3a session: set_pmu on AgentLoop failed", error_code="E_L3A_SESSION", component="l3a")
                logger.warning("l3a session: set_pmu on AgentLoop failed")

    def _ingest_tool_results(self, result: dict, user_text: str) -> None:
        """Ingest this turn's tool results into L3A's three-ring memory.

        Mirrors the Cell Peer Agent pattern (context.py end()):
          tool_call results  → L3A ring 1 (entry_type=l3a_tool_call)
          decision-grade     → L3A ring 2 (entry_type=l3a_tool_decision)
          turn summary       → L3A ring 3 (entry_type=l3a_turn_summary)
        """
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
        except Exception:
            return
        tool_results = result.get("tool_call_results", []) or []
        if not tool_results:
            return
        high_value_tools = {"cardwrite", "l3a_ask", "l3a_collect", "l3a_convention", "l3a_spawn", "l3a_summary"}
        decision_entries = []
        for sr in tool_results:
            tool_name = sr.get("tool_name", "") or sr.get("action", "?")
            payload = sr.get("result", {}) if isinstance(sr, dict) and "result" in sr else sr
            content = f"[turn:{self.turn_count}] {tool_name} → {str(payload)[:LOG_TRUNC_300]}"
            ring = 2 if tool_name in high_value_tools else 1
            entry_type = "l3a_tool_decision" if ring == 2 else "l3a_tool_call"
            try:
                mem.remember(
                    agent_id=_p.AGENT_ID,
                    entry_type=entry_type,
                    content=content,
                    tags=["l3a", tool_name, self.id],
                    importance=0.7 if ring == 2 else 0.5,
                    ring=ring,
                    cell_id=self._cell_id,
                )
                if ring == 2:
                    decision_entries.append(content[:LOG_TRUNC_200])
            except Exception:
                logger.debug("l3a session: tool result memory ingest failed")
        # Turn summary → ring 3 (long-term, importance weighted)
        try:
            summary = f"[session:{self.id} turn:{self.turn_count}] user: {user_text[:LOG_TRUNC_100]}" + (
                f" | decisions: {'; '.join(decision_entries)[:LOG_TRUNC_300]}" if decision_entries else ""
            )
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_turn_summary",
                content=summary,
                tags=["l3a", "turn_summary", self.id],
                importance=0.6,
                ring=3,
                cell_id=self._cell_id,
            )
        except Exception:
            logger.debug("l3a session: turn summary ingest failed")

    def _ingest_reasoning(self, result: dict, user_text: str) -> None:
        """Persist this turn's thinking-mode reasoning trail (deepseek-v4,
        claude thinking, etc.) into L3A ring 2 as the deliberation record.

        The chain-of-thought is the decision process — more valuable than the
        final answer. Folded into ONE entry per turn (bounded rounds) so the
        memory stays usable, not a verbatim transcript.
        """
        trail = result.get("reasoning_trail") or []
        if not trail:
            return
        try:
            from l3.memory.central_memory import get_l3a_memory

            mem = get_l3a_memory()
        except Exception:
            return
        folded = "\n---\n".join(t.strip()[:LOG_TRUNC_500] for t in trail[: _p.REASONING_TRAIL_MAX_TURNS])[
            :LOG_TRUNC_2000
        ]
        if not folded:
            return
        rtok = int(result.get("reasoning_tokens", 0) or 0)
        content = (
            f"[session:{self.id} turn:{self.turn_count}] "
            f"reasoning_tokens:{rtok} user: {user_text[:LOG_TRUNC_100]}\n"
            f"reasoning:\n{folded}"
        )
        try:
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_reasoning_trail",
                content=content,
                tags=["l3a", "reasoning", self.id],
                importance=_p.REASONING_TRAIL_IMPORTANCE,
                ring=2,
                cell_id=self._cell_id,
            )
        except Exception:
            logger.debug("l3a session: reasoning trail ingest failed")

    def _persist_state(self) -> None:
        try:
            from l3.agent.agent_persist import save_snapshot

            payload = {
                "session_id": self.id,
                "title": self.title,
                "turn_count": self.turn_count,
                "card_count": self.card_count,
                "model_config": self.model_config.show(),
            }
            if self._ask:
                try:
                    payload["ask"] = self._ask.to_dict()
                except Exception:
                    logger.debug("l3a session: ask state serialize failed")
            save_snapshot(_p.AGENT_ID, payload)
        except Exception:
            capture("l3a session: state persist failed", error_code="E_L3A_SESSION", component="l3a")
            logger.warning("l3a session: state persist failed")


class SessionManager:
    """Active-session registry for the L3A daemon."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(
        self,
        title: str = "",
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
        user_id: str = "",
    ) -> Session:
        """Create a session, register it as active, and return it."""
        s = Session.create(title=title, model_config=model_config, registry=registry, user_id=user_id)
        with self._lock:
            self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        """Return the active session by id, or None when absent."""
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> dict:
        """Close and deregister a session by id, returning the close result."""
        s = self.get(session_id)
        if not s:
            return {"success": False, "error": f"unknown session: {session_id}"}
        r = s.close()
        with self._lock:
            self._sessions.pop(session_id, None)
        return r

    def list_active(self) -> list[dict]:
        """Return info dicts for all sessions with active status."""
        with self._lock:
            return [s.info() for s in self._sessions.values() if s.status == "active"]

    def count(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            return len(self._sessions)
