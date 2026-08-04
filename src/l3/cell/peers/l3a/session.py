"""Session — durable session entity with history, inbox, epoch, and lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import (
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LOG_TRUNC_500,
    LOG_TRUNC_2000,
    SESSION_MSG_OVERHEAD,
    TOKEN_CHARS_PER_TOKEN,
)
from l3.error_bus import capture

from . import archive as _archive
from . import params as _p
from .context import ContextEpoch, ContextRegistry
from .inbox import PromptInbox
from .model import L3AModelConfig
from .task_table import SessionTaskTable

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
    reasoning_content: str = ""
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
            if m.reasoning_content:
                entry["reasoning_content"] = m.reasoning_content
            projected.append(entry)
        projected.reverse()
        return projected

    def to_context_trail(self) -> list[dict]:
        return self.project(max_tokens=_p.SESSION_HISTORY_MAX_TOKENS * 2)

    def count(self) -> int:
        with self._lock:
            return len(self._messages)

    def messages_page(self, cursor: str | None = None,
                      limit: int = _p.SESSION_PAGE_SIZE) -> Page:
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
            "reasoning_content": m.reasoning_content,
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
        self._ask: Any = None

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
                        all_entries = mem.recall(
                            agent_id=_p.AGENT_ID, rings=[1, 2, 3], limit=50)
                        by_id = {e.id: e for e in all_entries}
                        ctx_lines = []
                        for nid in gr["nodes"][:6]:
                            e = by_id.get(nid)
                            if e and e.content and e.id not in seeds:
                                ctx_lines.append(
                                    f"- [{e.entry_type}] {e.content[:LOG_TRUNC_200]}")
                        if ctx_lines:
                            inst.history.append(Message(
                                id=f"graph-{uuid.uuid4().hex[:4]}",
                                role="system",
                                content=("Related context from memory graph:\n"
                                         + "\n".join(ctx_lines)),
                                metadata={"graph_recall": True}))
        except Exception:
            logger.debug("l3a session: resume graph recall failed")
        return inst

    def prompt(self, text: str, mode: str = "steer") -> dict:
        limits = self._resolve_limits()
        if limits["max_turns"] > 0 and self.turn_count >= limits["max_turns"]:
            return {"success": False, "error": f"max turns reached ({limits['max_turns']})"}
        # ASK awaiting: the chat input is treated as answers to the pending
        # clarification questions (chat-window semantics), then the loop resumes.
        if self._ask and self._ask.status == _p.ASK_STATUS_AWAITING:
            return self._continue_after_ask(text)
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
        # 任务感知注入：提示词决定维度（execute→summary, decide→Mer, resume→layered）
        try:
            from l3.memory.memory_inject import build_context as _inject
            inject_block = _inject(_p.AGENT_ID, prompt=admitted.text,
                                   max_tokens=1024)
            if inject_block:
                ctx_trail.insert(0, {
                    "role": "system",
                    "content": f"[Task-Aware Memory]\n{inject_block}",
                })
        except Exception:
            logger.debug("l3a session: task-aware injection failed")
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
        reasoning = ""
        try:
            trail = getattr(self._loop, "_context_trail", None) or []
            for m in reversed(trail):
                if m.get("role") == "assistant":
                    reasoning = m.get("reasoning_content", "") or ""
                    break
        except Exception:
            pass
        answer_msg = Message(
            id=f"asst-{uuid.uuid4().hex[:4]}",
            role="assistant", content=answer,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
        )
        self.history.append(answer_msg)
        self._persist_state()
        self._ingest_tool_results(result, admitted.text)
        self._ingest_reasoning(result, admitted.text)
        rtok = int(result.get("reasoning_tokens", 0) or 0)
        if rtok > 0:
            try:
                from l3.services.stats_center import MetricPoint as _Mp
                from l3.services.stats_center import get_center
                ts = time.time()
                get_center().ingest(_Mp(
                    name="l3a.tokens.reasoning", value=float(rtok),
                    tags={"session": self.id, "agent": _p.AGENT_ID},
                    timestamp=ts, metric_type="counter"))
            except Exception:
                logger.debug("l3a session: reasoning token stats failed")
        if rtok > 0:
            try:
                from l3.bus.monitor_bus import MonitorEvent as _ME4
                from l3.bus.monitor_bus import get_bus as _MB4
                _MB4().emit(_ME4(
                    type="stats.l3a.reasoning", source="l3a",
                    severity="info",
                    message=f"{self.id} turn {self.turn_count}: {rtok} thinking tokens",
                    agent_id=_p.AGENT_ID, cell_id=self._cell_id,
                    data={"session": self.id, "turn": self.turn_count,
                          "reasoning_tokens": rtok}))
            except Exception:
                logger.debug("l3a session: reasoning monitor emit failed")
        result["session_id"] = self.id
        result["turn"] = self.turn_count

        # Record tool call metrics to StatsCenter
        if tool_calls:
            t0 = time.time()
            try:
                from l3.services.stats_center import MetricPoint as _Mp
                from l3.services.stats_center import get_center
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
            from l3.services.stats_center import MetricPoint as _Mp
            from l3.services.stats_center import get_center
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
                 limit: int = _p.SESSION_PAGE_SIZE) -> Page:
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

    # ── Manual context compression ──

    @staticmethod
    def _message_value(m: Message) -> int:
        """Rate a message's information value (rate-distortion weighting).

        3 = high value — user explicit intent, card results, convention
            references, prior compression summaries. Preserved in full.
        2 = medium     — assistant answers, tool-call records.
        1 = low        — verbose tool output, boilerplate.
        """
        if m.role == "user":
            return 3
        if m.role == "system":
            meta = m.metadata or {}
            if meta.get("card_id") or meta.get("compression"):
                return 3
            if meta.get("context_key"):
                return 2
            return 2
        return 2

    def compress(self, keep_last: int = _p.SESSION_COMPRESS_KEEP, summary: str = "") -> dict:
        """Compress session history into a summary, keeping the last N messages.

        Rate-distortion aware:
          1. Lossless snapshot — the folded messages' full text is archived
             to R4 (fonds=AGENT:l3a, series=session_compression_snapshot)
             BEFORE folding, so compression = deferred access, not loss.
          2. Value-weighted summary — high-value messages (user intents,
             card results, convention refs) are preserved in full; medium
             ones get a preview list; low-value ones are only counted.
          3. Distortion report — returns role/type distribution, high-value
             preservation counts, and the snapshot archive_ref.
        """
        with self._lock:
            total = len(self.history._messages)
            if total <= keep_last:
                return {"success": True, "note": "nothing to compress",
                        "compressed": 0, "kept": total}
            keep = self.history._messages[-keep_last:]
            old = self.history._messages[:-keep_last]
            before_tokens = sum(
                len(m.content) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
                for m in old)

        # ── 1. Lossless snapshot to R4 (deferred access, not loss) ──
        snapshot_ref = ""
        try:
            import json as _json

            from l3.tools._archive import _cmd_archive_store
            snapshot = {
                "session_id": self.id,
                "turn": self.turn_count,
                "compressed_at": time.time(),
                "compressed_count": len(old),
                "messages": [
                    {"id": m.id, "role": m.role, "content": m.content,
                     "created_at": m.created_at, "metadata": m.metadata}
                    for m in old
                ],
            }
            r = _cmd_archive_store(
                fonds="AGENT:l3a",
                series="session_compression_snapshot",
                content=_json.dumps(snapshot, ensure_ascii=False, default=str),
                tags=f"l3a,session_compression,{self.id}",
            )
            if r.get("success"):
                snapshot_ref = f"snapshot:l3a:{self.turn_count}"
        except Exception:
            logger.debug("l3a session: compression snapshot failed")

        # ── 2. Value-weighted summary ──
        high = [m for m in old if self._message_value(m) >= 3]
        medium = [m for m in old if self._message_value(m) == 2]
        low = [m for m in old if self._message_value(m) <= 1]
        lines = []
        if high:
            lines.append("Earlier key context (preserved in full):")
            for m in high:
                prefix = "USER" if m.role == "user" else "CARD"
                lines.append(f"- [{prefix}] {m.content[:LOG_TRUNC_300]}")
        if medium:
            user_med = [m for m in medium if m.role == "user"]
            if user_med:
                lines.append("Earlier user requests:")
                for m in user_med[:5]:
                    lines.append(f"- {m.content[:LOG_TRUNC_200]}")
                if len(user_med) > 5:
                    lines.append(f"- ... and {len(user_med) - 5} more")
        if low:
            lines.append(f"(dropped {len(low)} low-value items, see snapshot)")
        if not lines:
            lines.append("(prior conversation summarized)")
        summary_text = summary or "\n".join(lines)

        # Persist the summary into L3A's own memory (ring 2) before folding
        try:
            from l3.memory.central_memory import get_l3a_memory
            mem = get_l3a_memory()
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="session_compression",
                content=f"[session:{self.id}] turn={self.turn_count}: {summary_text}",
                tags=["l3a", "compression", self.id],
                importance=0.6,
                ring=2,
            )
            # Link compression into all three rings:
            # R1 — compression action record (recent activity)
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_compression_action",
                content=f"[session:{self.id}] turn={self.turn_count}: "
                        f"compressed {len(old)} msgs, snapshot={snapshot_ref}",
                tags=["l3a", "compression", self.id],
                importance=0.4,
                ring=1,
            )
            # R3 — long-term compression index with lossless snapshot ref
            mem.remember(
                agent_id=_p.AGENT_ID,
                entry_type="l3a_compression_index",
                content=f"[session:{self.id}] turn={self.turn_count}: "
                        f"compressed {len(old)} msgs | high-value kept "
                        f"{len(high)} | snapshot: {snapshot_ref or 'n/a'}",
                tags=["l3a", "compression", "index", self.id],
                importance=0.8,
                ring=3,
            )
        except Exception:
            logger.debug("l3a session: compression memory persist failed")

        with self._lock:
            summary_msg = Message(
                id=f"sum-{uuid.uuid4().hex[:4]}",
                role="system",
                content=f"[SESSION COMPRESSED at turn {self.turn_count}] {summary_text}",
                metadata={"compression": True,
                          "compressed": len(old),
                          "snapshot_ref": snapshot_ref,
                          "high_value_preserved": len(high),
                          "kept": keep_last},
            )
            self.history._messages = [summary_msg] + keep
        after_tokens = len(summary_text) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
        logger.info("l3a session %s: compressed %d msgs → summary (+%d kept)",
                    self.id, len(old), keep_last)
        # ── R5 swarm-domain graph linkage: graph reduction after compaction (derived layer, failures non-blocking) ──
        try:
            from l3.memory.memory_graph import get_graph as _gg
            g = _gg()
            if g.enabled:
                g.compact(min_degree=2, dry_run=False)
        except Exception:
            logger.debug("l3a session: graph compact after compress failed")
        return {
            "success": True, "session_id": self.id,
            "compressed": len(old), "kept": keep_last,
            "before_tokens": before_tokens, "after_tokens": after_tokens,
            "summary": summary_text,
            "snapshot_ref": snapshot_ref,
            "distortion": {
                "high_value_preserved": len(high),
                "medium_value_summarized": len(medium),
                "low_value_dropped": len(low),
                "by_role": {
                    "user": sum(1 for m in old if m.role == "user"),
                    "assistant": sum(1 for m in old if m.role == "assistant"),
                    "system": sum(1 for m in old if m.role == "system"),
                },
                "note": ("high-value messages preserved in full; "
                         "full text recoverable via snapshot_ref")
                if snapshot_ref else "snapshot unavailable",
            },
        }

    # ── R1-R3 memory usage / ingress rate ──

    def auto_compress_check(self, force: bool = False) -> dict:
        """System-monitored auto-compression: checks context pressure against
        the configured threshold and compresses when exceeded.

        Strategy (SettingsCenter):
          l3a.auto_compress           — master switch (default True)
          l3a.auto_compress_threshold — pressure_ratio trigger (default 0.6)
          l3a.auto_compress_keep      — messages kept (default 10)
        """
        try:
            from l3.config.settings_center import get_center
            sc = get_center()
            enabled = bool(sc.get("l3a.auto_compress", True))
            threshold = float(sc.get("l3a.auto_compress_threshold", 0.6))
            keep = int(sc.get("l3a.auto_compress_keep", 10))
        except Exception:
            enabled, threshold, keep = True, 0.6, 10

        if not enabled and not force:
            return {"success": True, "action": "skipped",
                    "reason": "auto_compress disabled"}
        if self.status != "active":
            return {"success": True, "action": "skipped",
                    "reason": "session closed"}

        stats = self.context_stats()
        pressure = stats.get("pressure_ratio", 0.0)
        if pressure < threshold and not force:
            return {"success": True, "action": "none",
                    "pressure": pressure, "threshold": threshold}
        if self.history.count() <= keep:
            return {"success": True, "action": "none",
                    "pressure": pressure, "threshold": threshold,
                    "reason": "history below keep size"}
        r = self.compress(keep_last=keep)
        r["action"] = "compressed"
        r["pressure_before"] = pressure
        r["threshold"] = threshold
        logger.info("l3a session %s: auto-compressed at pressure %.2f "
                    "(threshold %.2f)", self.id, pressure, threshold)
        return r

    def memory_usage(self, window: float = _p.SESSION_MEMORY_WINDOW_SECONDS) -> dict:
        """Report the session's R1-R3 ring usage and ingress rates.

        window: seconds for the ingress-rate window (default 1h).
        Reads from L3A's own isolated memory instance via CentralMemory.
        """
        try:
            from l3.memory.central_memory import get_l3a_memory
            mem = get_l3a_memory()
            stats = mem.stats() if hasattr(mem, "stats") else {}
            now = time.time()
            since = now - window
            recent = mem.recall(agent_id=_p.AGENT_ID, rings=[1, 2, 3],
                                limit=500)
            ingress = {"count": 0, "by_type": {}}
            for e in recent:
                if getattr(e, "timestamp", 0) >= since:
                    ingress["count"] += 1
                    t = getattr(e, "entry_type", "?")
                    ingress["by_type"][t] = ingress["by_type"].get(t, 0) + 1
            pressure = mem.pressure() if hasattr(mem, "pressure") else {}
        except Exception as e:
            logger.debug("l3a session: memory_usage failed: %s", e)
            return {"success": False, "error": str(e)}
        return {
            "success": True, "session_id": self.id,
            "window_seconds": window,
            "rings": stats,
            "pressure": pressure,
            "ingress": {
                "count": ingress["count"],
                "per_hour": round(ingress["count"] / max(window / 3600.0, 0.001), 2),
                "by_type": dict(sorted(ingress["by_type"].items(),
                                       key=lambda x: -x[1])),
            },
        }

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
                "ask": self._ask.to_dict() if self._ask else None,
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
            steps = l3a_steps if l3a_steps > 0 else (loop_steps if loop_steps > 0 else _p.SESSION_MAX_STEPS_UNLIMITED)
            timeout = sc.get("l3a.timeout", sc.get("loop.timeout", 0))
            max_turns = sc.get("l3a.max_turns", sc.get("session.max_turns", 0))
        except Exception:
            capture("l3a session: limits resolve failed", error_code="E_L3A_SESSION", component="l3a")
            steps = _p.SESSION_MAX_STEPS_UNLIMITED
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
            from l3.services.stats_center import MetricPoint, get_center
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
        from .subagent import l3a_collect_handler, l3a_peek_handler, l3a_spawn_handler
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
        from .ask import ask_handler as _l3a_ask_handler
        self._loop.add_tool("l3a_ask",
            "Ask the user to clarify the request. Call when the user's prompt "
            "is ambiguous or critical information is missing (target platform, "
            "scope, constraints, acceptance criteria, etc.). Pass up to "
            f"{_p.ASK_MAX_QUESTIONS} questions as a list of dicts "
            "{question, options?, required?}. Execution pauses until the user "
            "answers in the chat window; answers are injected back before "
            "resuming.",
            {"questions": "list"},
            lambda args, agent_id="": _l3a_ask_handler(self, args, agent_id),
            parallel_safe=False)
        if self._pmu:
            try:
                self._loop.set_pmu(self._pmu)
            except Exception:
                capture("l3a session: set_pmu on AgentLoop failed", error_code="E_L3A_SESSION", component="l3a")
                logger.warning("l3a session: set_pmu on AgentLoop failed")

    def ask_status(self) -> dict:
        """Public status of the pending clarification (empty when none)."""
        st = self._ask
        if not st:
            return {"success": True, "status": "none"}
        return {"success": True, "status": st.status, "ask": st.to_dict()}

    def submit_answers(self, answers: dict, free_form: str = "") -> dict:
        """Fill answers for pending questions (command/API path)."""
        from .ask import submit_answers as _submit
        r = _submit(self, answers, free_form)
        if r.get("success"):
            self._persist_state()
        return r

    def _continue_after_ask(self, text: str) -> dict:
        """Chat-window path: the next user input answers the pending questions.

        The raw text becomes the free-form answer plus a per-question fallback
        (structured ``q1=..; q2=..`` syntax is honored); the Q&A block is
        injected into history and the tool loop resumes.
        """
        from .ask import submit_answers as _submit
        answers: dict = {}
        if "=" in text:
            pairs = [part.strip() for part in text.split(";")]
            answers = {
                part.split("=", 1)[0].strip(): part.split("=", 1)[1].strip()
                for part in pairs if "=" in part
            }
        _submit(self, answers, text)
        return self.resume_after_ask()

    def resume_after_ask(self) -> dict:
        """Inject the answered Q&A block into history and resume the loop."""
        from .ask import build_answer_block
        st = self._ask
        if not st or st.status != _p.ASK_STATUS_ANSWERED:
            return {"success": False, "error": "no answered questions to resume"}
        block = build_answer_block(st)
        self.history.append(Message(
            id=f"ask-{uuid.uuid4().hex[:4]}",
            role="user", content=block,
            metadata={"kind": "ask_answer"},
        ))
        self.last_active_at = time.time()
        try:
            self._report_stats()
        except Exception:
            pass
        ctx_trail = self.history.to_context_trail()
        self._ensure_loop()
        self._loop._context_trail = ctx_trail
        self._loop.task = st.free_form or "continue after clarification"
        limits = self._resolve_limits()
        model_cfg = self._resolve_model_config()
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
        self._ingest_tool_results(result, st.free_form or "clarification")
        return {
            "success": True,
            "session_id": self.id,
            "answer": answer,
            "tool_calls": tool_calls,
            "ask_resolved": True,
            "turn_count": self.turn_count,
        }

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
        high_value_tools = {"cardwrite", "l3a_ask", "l3a_collect", "l3a_convention",
                            "l3a_spawn", "l3a_summary"}
        decision_entries = []
        for sr in tool_results:
            tool_name = sr.get("tool_name", "") or sr.get("action", "?")
            if isinstance(sr, dict) and "result" in sr:
                payload = sr.get("result", {})
            else:
                payload = sr
            content = (f"[turn:{self.turn_count}] {tool_name} "
                       f"→ {str(payload)[:LOG_TRUNC_300]}")
            ring = 2 if tool_name in high_value_tools else 1
            entry_type = ("l3a_tool_decision" if ring == 2
                          else "l3a_tool_call")
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
            summary = (f"[session:{self.id} turn:{self.turn_count}] "
                       f"user: {user_text[:LOG_TRUNC_100]}"
                       + (f" | decisions: {'; '.join(decision_entries)[:LOG_TRUNC_300]}"
                          if decision_entries else ""))
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
        folded = "\n---\n".join(
            t.strip()[:LOG_TRUNC_500] for t in trail[:_p.REASONING_TRAIL_MAX_TURNS]
        )[:LOG_TRUNC_2000]
        if not folded:
            return
        rtok = int(result.get("reasoning_tokens", 0) or 0)
        content = (f"[session:{self.id} turn:{self.turn_count}] "
                   f"reasoning_tokens:{rtok} user: {user_text[:LOG_TRUNC_100]}\n"
                   f"reasoning:\n{folded}")
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
                "session_id": self.id, "title": self.title,
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
