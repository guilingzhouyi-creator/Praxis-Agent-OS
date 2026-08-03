"""Session — durable session entity with history, inbox, epoch, and lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import params as _p
from l1.kernel.params.system import (
    TOKEN_CHARS_PER_TOKEN, SESSION_MSG_OVERHEAD, LOG_TRUNC_200,
)
from .model import L3AModelConfig
from .context import ContextEpoch, ContextRegistry
from .inbox import PromptInbox, Admission
from .task_table import SessionTaskTable, SessionTask
from . import archive as _archive
from l3.error_bus import capture

logger = logging.getLogger(__name__)


@dataclass
class Page:
    items: list[dict]
    cursor: str | None = None
    total: int = 0


@dataclass
class Message:
    id: str
    role: str
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class SessionHistory:
    def __init__(self):
        self._messages: list[Message] = []
        self._lock = threading.RLock()

    def append(self, msg: Message) -> None:
        with self._lock:
            self._messages.append(msg)

    def extend(self, msgs: list[Message]) -> None:
        with self._lock:
            self._messages.extend(msgs)

    def project(self, max_tokens: int = _p.SESSION_HISTORY_MAX_TOKENS,
                keep_last: int = _p.SESSION_HISTORY_TRUNC) -> list[dict]:
        with self._lock:
            msgs = self._messages[-keep_last:]
        tokens = 0
        projected = []
        for m in reversed(msgs):
            est = len(m.content) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
            if tokens + est > max_tokens and projected:
                break
            tokens += est
            entry = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            projected.append(entry)
        projected.reverse()
        return projected

    def to_context_trail(self) -> list[dict]:
        return self.project(max_tokens=_p.SESSION_HISTORY_MAX_TOKENS * 2)

    def count(self) -> int:
        with self._lock:
            return len(self._messages)

    def messages_page(self, cursor: str | None = None,
                      limit: int = 20) -> Page:
        with self._lock:
            msgs = list(self._messages)
        start = 0
        if cursor:
            for i, m in enumerate(msgs):
                if m.id == cursor:
                    start = i + 1
                    break
        chunk = msgs[start:start + limit]
        items = [{
            "id": m.id, "role": m.role, "content": m.content,
            "tool_calls": m.tool_calls, "created_at": m.created_at,
        } for m in chunk]
        next_cursor = chunk[-1].id if len(chunk) == limit else None
        return Page(items=items, cursor=next_cursor, total=len(msgs))

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()


def _est_tokens(text: str) -> int:
    return len(text) // TOKEN_CHARS_PER_TOKEN


class Session:
    def __init__(self, session_id: str, title: str,
                 model_config: L3AModelConfig | None = None,
                 registry: ContextRegistry | None = None):
        self.id = session_id
        self.title = title
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

    @classmethod
    def create(cls, title: str = "",
               model_config: L3AModelConfig | None = None,
               registry: ContextRegistry | None = None) -> Session:
        sid = f"l3a-{uuid.uuid4().hex[:_p.SID_LENGTH]}"
        title = title or f"Session {time.strftime('%Y-%m-%d %H:%M')}"
        inst = cls(session_id=sid, title=title,
                   model_config=model_config, registry=registry)
        inst.epoch = ContextEpoch.create(registry or ContextRegistry())
        inst.inbox.reload()
        logger.info("l3a session: created %s — %s", sid, title)
        try:
            from l3.bus.log import get_service as _ls
            _ls().info(f"Session created: {title}", service="l3a", agent_id=_p.AGENT_ID, task_id=sid)
        except Exception:
            pass
        return inst

    @classmethod
    def resume_from_archive(cls, archived_session_id: str,
                            model_config: L3AModelConfig | None = None,
                            registry: ContextRegistry | None = None) -> Session | None:
        """Resume an archived session from R4 — new live session seeded with
        the archived metadata, transcript, task table, and TODO list."""
        blob = _archive.load_session_blob(archived_session_id)
        if not blob:
            return None
        meta = blob.get("metadata", {})
        transcript = blob.get("transcript", [])
        tasks_data = meta.get("tasks", {})
        todos_data = meta.get("todos", [])

        inst = cls(session_id=f"l3a-{uuid.uuid4().hex[:_p.SID_LENGTH]}",
                   title=(meta.get("title") or "Resumed session") + " (resumed)",
                   model_config=model_config, registry=registry)
        inst.epoch = ContextEpoch.create(registry or ContextRegistry())
        inst.inbox.reload()
        inst.turn_count = int(meta.get("turn_count", 0))
        inst.card_count = int(meta.get("card_count", 0))
        inst.tasks.from_dict(tasks_data or {})
        inst._resumed_from = archived_session_id
        if todos_data:
            try:
                from l3.services.todo_tracker import TodoTracker
                inst._resume_todos = list(todos_data)
            except Exception:
                pass
        if transcript:
            for m in transcript:
                try:
                    inst.history.append(Message(
                        id=m.get("id", f"r-{uuid.uuid4().hex[:4]}"),
                        role=m.get("role", "user"),
                        content=m.get("content", ""),
                        tool_calls=m.get("tool_calls", []),
                        created_at=float(m.get("created_at") or time.time()),
                        metadata=m.get("metadata", {}),
                    ))
                except Exception:
                    continue
        logger.info("l3a session: resumed %s → %s (%d msgs)",
                    archived_session_id, inst.id, inst.history.count())
        return inst

    def prompt(self, text: str, mode: str = "steer") -> dict:
        limits = self._resolve_limits()
        if limits["max_turns"] > 0 and self.turn_count >= limits["max_turns"]:
            return {"success": False, "error": f"max turns reached ({limits['max_turns']})"}
        admission = self.inbox.admit(text, mode=mode)
        self.last_active_at = time.time()
        self._ensure_epoch()
        changes = self.epoch.sync(self.registry) if self.registry else []
        for c in changes:
            self.history.append(Message(
                id=f"sys-{uuid.uuid4().hex[:4]}",
                role="system", content=c.text,
                metadata={"context_key": c.key},
            ))
        admitted = self.inbox.promote()
        if not admitted:
            return {"success": False, "error": "no pending prompt"}
        self.history.append(Message(
            id=admitted.id, role="user", content=admitted.text,
        ))

        try:
            self._report_stats()
        except Exception:
            capture("l3a session: stats report failed", error_code="E_L3A_STATS", component="l3a")
            logger.warning("l3a session: stats report failed")
        ctx_trail = self.history.to_context_trail()
        self._ensure_loop()
        self._loop._context_trail = ctx_trail
        self._loop.task = admitted.text
        model_cfg = self._resolve_model_config()
        # Capture pre-call projected tokens for savings tracking
        pre_tokens = self.context_stats()["projected_tokens"]
        result = self._loop.run(
            max_steps=limits["max_steps"],
            timeout=limits["timeout"],
            model_config=model_cfg,
        )
        self.turn_count += 1
        answer = result.get("answer", "")
        tool_calls = result.get("tool_calls", [])
        answer_msg = Message(
            id=f"asst-{uuid.uuid4().hex[:4]}",
            role="assistant", content=answer,
            tool_calls=tool_calls,
        )
        self.history.append(answer_msg)
        self._persist_state()
        result["session_id"] = self.id
        result["turn"] = self.turn_count

        # Record tool call metrics to StatsCenter
        if tool_calls:
            t0 = time.time()
            try:
                from l3.services.stats_center import get_center, MetricPoint as _Mp
                sc = get_center()
                ts = time.time()
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    err = tc.get("error", "")
                    success = err == ""
                    latency = (time.time() - t0) / max(len(tool_calls), 1)
                    sc.ingest(_Mp(name="l3a.tools.executed", value=1.0,
                              tags={"tool": fn_name, "success": str(success).lower(),
                                    "session": self.id, "agent": _p.AGENT_ID},
                              timestamp=ts, metric_type="counter"))
                    sc.ingest(_Mp(name="l3a.tools.latency", value=round(latency, 3),
                              tags={"tool": fn_name, "session": self.id},
                              timestamp=ts, metric_type="gauge"))
                    sc.ingest(_Mp(name="l3a.tokens.consumed",
                              value=float(tc.get("tokens", 0)),
                              tags={"tool": fn_name, "session": self.id},
                              timestamp=ts, metric_type="counter"))
            except Exception:
                capture("l3a session: stats_center tool recording failed", error_code="E_L3A_SESSION", component="l3a")
                logger.debug("l3a session: stats_center tool recording failed")

        # Token savings tracking: compare projected vs actual
        post_tokens = self.context_stats()["projected_tokens"]
        token_saved = pre_tokens - post_tokens
        try:
            from l3.services.stats_center import get_center, MetricPoint as _Mp
            sc = get_center()
            ts = time.time()
            sc.ingest(_Mp(name="l3a.tokens.projected", value=float(pre_tokens),
                      tags={"session": self.id, "agent": _p.AGENT_ID},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(_Mp(name="l3a.tokens.actual", value=float(post_tokens),
                      tags={"session": self.id, "agent": _p.AGENT_ID},
                      timestamp=ts, metric_type="gauge"))
            if token_saved > 0:
                sc.ingest(_Mp(name="l3a.tokens.saved", value=float(token_saved),
                          tags={"session": self.id},
                          timestamp=ts, metric_type="counter"))
        except Exception:
            capture("l3a session: token savings recording failed", error_code="E_L3A_SESSION", component="l3a")
            logger.debug("l3a session: token savings recording failed")
        return result

    def set_pmu(self, pmu: Any) -> None:
        self._pmu = pmu

    def context_stats(self) -> dict:
        epoch_tok = self.epoch.estimate_tokens() if self.epoch else 0
        history_tok = _est_tokens(
            " ".join(m.content for m in self.history._messages)
        ) if self.history._messages else 0
        projected = self.history.project()
        projected_tok = sum(_est_tokens(m.get("content", "")) for m in projected)
        window = self._query_context_window()
        pressure = projected_tok / window if window > 0 else 0.0
        level = "ok"
        if pressure >= 0.95:
            level = "critical"
        elif pressure >= 0.80:
            level = "medium"
        elif pressure >= 0.60:
            level = "warn"
        limits = self._resolve_limits()
        return {
            "epoch_id": self.epoch.id if self.epoch else "",
            "epoch_baseline_tokens": epoch_tok,
            "history_tokens": history_tok,
            "projected_tokens": projected_tok,
            "context_window": window,
            "pressure_ratio": round(pressure, 3),
            "pressure_level": level,
            "max_steps": limits["max_steps"],
            "max_turns": limits["max_turns"],
            "turns_used": self.turn_count,
        }

    _ctx_window_cache: int = 0

    def _query_context_window(self) -> int:
        if isinstance(self._ctx_window_cache, int) and self._ctx_window_cache > 0:
            return self._ctx_window_cache
        try:
            from l1.kernel.ports import get_port as _get_port
            engine = _get_port("llm")
            raw = engine.context_window(
                cell_id=self._cell_id, agent_id=_p.AGENT_ID)
            # The LLM port may return an int or a dict like
            # {"context_window": N, "source": "llm"} — normalize both.
            if isinstance(raw, dict):
                raw = raw.get("context_window", raw.get("max", 0))
            self._ctx_window_cache = int(raw or 0)
        except Exception:
            capture("l3a session: context window query failed", error_code="E_L3A_SESSION", component="l3a")
            self._ctx_window_cache = _p.CONTEXT_WINDOW_FALLBACK
        return self._ctx_window_cache

    def close(self) -> dict:
        with self._lock:
            if self.status != "active":
                return {"success": False, "error": "already closed"}
            sid = self.id
            title = self.title
            status = self.status
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
            "session_id": sid, "title": title,
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
        logger.info("l3a session: closed %s — %s (%d turns)",
                    sid, title, self.turn_count)
        try:
            from l3.bus.log import get_service as _ls
            _ls().info(f"Session closed: {title}", service="l3a", agent_id=_p.AGENT_ID, task_id=sid)
        except Exception:
            pass
        return {"success": True, "session_id": sid, "title": title}

    def messages(self, cursor: str | None = None,
                 limit: int = 20) -> Page:
        return self.history.messages_page(cursor=cursor, limit=limit)

    # ── Session TODO table (LLM task list via todowrite tool) ──

    def todos(self) -> dict:
        """Query the session's TodoTracker state (LLM task list)."""
        if not self._loop:
            return {"status": "open", "total_tasks": 0, "by_status": {},
                    "tasks": [], "note": "loop not created yet"}
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

    def info(self) -> dict:
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
            }

    def _resolve_model_config(self) -> dict:
        if self._model_spec_cache:
            return self._model_spec_cache
        try:
            from l3.services.model_service import get_service as _gs
            spec = _gs().resolve_dict("l3a")
            cfg = self.model_config.resolve()
            cfg.update({k: v for k, v in spec.items() if k not in cfg or not cfg[k]})
            self._model_spec_cache = cfg
        except Exception:
            capture("l3a session: model spec resolve failed", error_code="E_L3A_SESSION", component="l3a")
            cfg = self.model_config.resolve()
            self._model_spec_cache = cfg
        return cfg

    def _resolve_limits(self) -> dict:
        try:
            from l3.config.settings_center import get_center
            sc = get_center()
            l3a_steps = sc.get("l3a.max_steps", 0)
            loop_steps = sc.get("loop.max_steps", 0)
            steps = l3a_steps if l3a_steps > 0 else (loop_steps if loop_steps > 0 else 999999)
            timeout = sc.get("l3a.timeout", sc.get("loop.timeout", 0))
            max_turns = sc.get("l3a.max_turns", sc.get("session.max_turns", 0))
        except Exception:
            capture("l3a session: limits resolve failed", error_code="E_L3A_SESSION", component="l3a")
            steps = 999999
            timeout = 0
            max_turns = 0
        return {"max_steps": steps, "timeout": timeout, "max_turns": max_turns}

    def _report_stats(self) -> None:
        stats = self.context_stats()
        est = stats["projected_tokens"]
        window = stats["context_window"]
        pressure = stats["pressure_ratio"]
        level = stats["pressure_level"]

        if self._pmu:
            self._pmu.increment("token.estimated", est)
            if level == "critical":
                self._pmu.increment("memory.context.critical")
            elif level == "medium":
                self._pmu.increment("memory.context.warnings")

        try:
            from l3.services.stats_center import get_center, MetricPoint
            sc = get_center()
            ts = time.time()
            sc.ingest(MetricPoint(name="l3a.epoch.tokens", value=float(est),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.epoch.pressure", value=float(pressure),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.session.turns", value=float(self.turn_count),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="gauge"))
            sc.ingest(MetricPoint(name="l3a.session.tokens_consumed", value=float(est + stats["epoch_baseline_tokens"]),
                      tags={"cell": self._cell_id, "agent": _p.AGENT_ID, "session": self.id},
                      timestamp=ts, metric_type="counter"))
        except Exception:
            capture("l3a session: StatsCenter ingest failed", error_code="E_L3A_STATS", component="l3a")
            logger.warning("l3a session: StatsCenter ingest failed")

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
            pass
        summary = result.get("summary", "")
        if not summary:
            summary = result.get("answer", "")
        if not summary:
            summary = str(result)[:LOG_TRUNC_200]
        # Convention convergence → distill L3A summary into dedicated store
        if result.get("issue_card_id") or result.get("doc_path"):
            self._distill_convention_summary(card_id, title, result)
        text = (f"Card {card_id} ({title}) → {state}"
                + (f": {summary}" if summary else ""))
        self.tasks.update(card_id, state, result)
        with self._lock:
            self.history.append(Message(
                id=f"card-{uuid.uuid4().hex[:4]}",
                role="system",
                content=text,
                metadata={"card_id": card_id, "card_state": state},
            ))
        logger.info("l3a session %s: card %s → %s", self.id, card_id, state)

    def _distill_convention_summary(self, card_id: str, title: str,
                                    result: dict) -> None:
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
            idx_r = l3a_convention_handler({"issue_id": issue_id,
                                            "action": "index"})
            if not idx_r.get("success"):
                logger.debug("l3a: summary distill index failed: %s",
                             idx_r.get("error"))
                return
            idx = idx_r.get("index", {})
            issues = []
            for it in idx.get("issues", []):
                block = l3a_convention_handler({"issue_id": issue_id,
                                                "anchor": it.get("anchor", "")})
                answer = ""
                if block.get("success"):
                    for ln in block["content"].splitlines():
                        if "**Answer**" in ln:
                            answer = ln.split("):", 1)[-1].strip() if "):" in ln else ln
                issues.append({
                    "anchor": it.get("anchor", ""),
                    "title": it.get("title", ""),
                    "domain": it.get("domain", ""),
                    "assigned_to": it.get("assigned_to", ""),
                    "status": it.get("status", ""),
                    "answer": answer,
                })
            decisions = []
            for d in idx.get("decisions", []):
                block = l3a_convention_handler({"issue_id": issue_id,
                                                "anchor": d.get("anchor", "")})
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
                issue_id=issue_id, source_card_id=card_id, title=title,
                domain=domain,
                agents=idx.get("participants", []),
                issues=issues, decisions=decisions,
                doc_path=result.get("doc_path", ""),
                archive_ref=result.get("archive_ref", ""),
                session_id=self.id,
            )
            get_store().save(s)
        except Exception as e:
            capture("l3a: summary distill failed", error_code="E_L3A_SESSION", component="l3a", context={"error": str(e)})
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

        self._base_system = build_l3a_prompt()
        try:
            from l1.kernel.paths import get_paths as _gp
            todo_path = os.path.join(_gp().data_dir,
                                     f"l3a_todos_{self.id}.json")
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
            r = cardwrite_handler(args, agent_id)
            if r.get("success"):
                cid = r.get("card_id", "")
                self.card_count += 1
                self._subscribed_cards.add(cid)
                self.tasks.track(cid, title=args.get("title", cid),
                                 turn=self.turn_count)
                try:
                    from l3.card.card_registry import get_registry
                    get_registry().subscribe(cid, self._on_card_completed)
                except Exception:
                    capture("l3a session: card subscribe failed", error_code="E_L3A_SESSION", component="l3a", context={"card_id": cid})
                    logger.debug("l3a session: card subscribe failed for %s", cid)
            return r

        self._loop.add_tool("cardwrite",
            "Create and submit a structured card.",
            {"nature": "string", "title": "string", "description": "string",
             "columns": "dict", "priority": "int", "phases": "list"},
            _session_cardwrite,
            parallel_safe=False,
        )
        from .subagent import l3a_spawn_handler, l3a_collect_handler, l3a_peek_handler
        self._loop.add_tool("l3a_spawn",
            "Spawn an async subagent. Returns task_id immediately.",
            {"spec": "string", "task": "string", "group": "string"},
            l3a_spawn_handler, parallel_safe=True)
        self._loop.add_tool("l3a_collect",
            "Wait for a group of subagents and collect results.",
            {"group": "string", "timeout": "number"},
            l3a_collect_handler, parallel_safe=False)
        self._loop.add_tool("l3a_result",
            "Peek at a single subagent result (non-blocking).",
            {"task_id": "string"},
            l3a_peek_handler, parallel_safe=True)
        from .helpers import l3a_convention_handler
        self._loop.add_tool("l3a_convention",
            "Navigate a converged convention document. First call action=index "
            "for the issue/decision catalog, then fetch specific blocks: "
            "anchor=I-2 (issue), anchor=D-1 (decision), or agent=agent-b "
            "(all lines for that agent). max_chars bounds reads.",
            {"issue_id": "string", "action": "string", "anchor": "string",
             "agent": "string", "max_chars": "int"},
            l3a_convention_handler, parallel_safe=True)
        from .helpers import l3a_summary_handler
        self._loop.add_tool("l3a_summary",
            "Query L3A deliberation-memory: action=latest [domain] for recent "
            "convention distillations, action=search <query> for keyword hits, "
            "action=get <issue_id> for one full summary with overlap notes.",
            {"action": "string", "issue_id": "string", "query": "string",
             "domain": "string", "limit": "int"},
            l3a_summary_handler, parallel_safe=True)
        if self._pmu:
            try:
                self._loop.set_pmu(self._pmu)
            except Exception:
                capture("l3a session: set_pmu on AgentLoop failed", error_code="E_L3A_SESSION", component="l3a")
                logger.warning("l3a session: set_pmu on AgentLoop failed")

    def _persist_state(self) -> None:
        try:
            from l3.agent.agent_persist import save_snapshot
            save_snapshot(_p.AGENT_ID, {
                "session_id": self.id, "title": self.title,
                "turn_count": self.turn_count,
                "card_count": self.card_count,
                "model_config": self.model_config.show(),
            })
        except Exception:
            capture("l3a session: state persist failed", error_code="E_L3A_SESSION", component="l3a")
            logger.warning("l3a session: state persist failed")


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, title: str = "",
               model_config: L3AModelConfig | None = None,
               registry: ContextRegistry | None = None) -> Session:
        s = Session.create(title=title, model_config=model_config,
                           registry=registry)
        with self._lock:
            self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> dict:
        s = self.get(session_id)
        if not s:
            return {"success": False, "error": f"unknown session: {session_id}"}
        r = s.close()
        with self._lock:
            self._sessions.pop(session_id, None)
        return r

    def list_active(self) -> list[dict]:
        with self._lock:
            return [s.info() for s in self._sessions.values()
                    if s.status == "active"]

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
