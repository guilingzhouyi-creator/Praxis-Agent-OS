"""SessionPersistMixin — session archive/resume, close, and state persistence.

Extracted from session.py (P1-1 split).  ``Message`` is imported lazily from
session.py to avoid a circular import — by method-call time the session
module is fully loaded.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from l1.kernel.params.system import HASH_TRUNC_SHORTEST, LOG_TRUNC_200
from l3.error_bus import capture

from . import archive as _archive
from . import params as _p
from .context import ContextEpoch, ContextRegistry
from .model import L3AModelConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SessionPersistMixin:
    """Archive/resume, close, convention-summary distillation, and state persistence."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    title: str
    user_id: str
    turn_count: int
    card_count: int
    status: str
    history: Any
    epoch: Any
    registry: Any
    tasks: Any
    _resumed_from: str
    _resume_todos: list[dict]

    @classmethod
    def resume_from_archive(
        cls,
        archived_session_id: str,
        model_config: L3AModelConfig | None = None,
        registry: ContextRegistry | None = None,
    ) -> Any | None:
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
            from .session_history import Message

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
