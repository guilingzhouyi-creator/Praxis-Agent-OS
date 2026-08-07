"""SessionCompressMixin — history compression + memory accounting for L3A Session.

Extracted from session.py (P1-1 split).  ``Message`` is imported lazily from
session.py to avoid a circular import — by method-call time the session
module is fully loaded.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from l1.kernel.params.system import (
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    SESSION_MSG_OVERHEAD,
    TOKEN_CHARS_PER_TOKEN,
)

from . import params as _p

if TYPE_CHECKING:
    from l3.cell.peers.l3a.session import Message, SessionHistory

logger = logging.getLogger(__name__)


class SessionCompressMixin:
    """SessionCompressMixin — rate-distortion-aware history compression."""

    # ── Attributes injected by the concrete Session (see session.py) ──
    id: str
    turn_count: int
    status: str
    _lock: threading.RLock
    history: SessionHistory

    def context_stats(self) -> dict:
        """Compute session context pressure (provided by SessionPromptMixin)."""
        raise NotImplementedError

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
        from l3.cell.peers.l3a.session import Message as _Message

        with self._lock:
            total = len(self.history._messages)
            if total <= keep_last:
                return {"success": True, "note": "nothing to compress", "compressed": 0, "kept": total}
            keep = self.history._messages[-keep_last:]
            old = self.history._messages[:-keep_last]
            before_tokens = sum(len(m.content) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD for m in old)

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
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                        "metadata": m.metadata,
                    }
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
            summary_msg = _Message(
                id=f"sum-{uuid.uuid4().hex[:4]}",
                role="system",
                content=f"[SESSION COMPRESSED at turn {self.turn_count}] {summary_text}",
                metadata={
                    "compression": True,
                    "compressed": len(old),
                    "snapshot_ref": snapshot_ref,
                    "high_value_preserved": len(high),
                    "kept": keep_last,
                },
            )
            self.history._messages = [summary_msg] + keep
        after_tokens = len(summary_text) // TOKEN_CHARS_PER_TOKEN + SESSION_MSG_OVERHEAD
        logger.info("l3a session %s: compressed %d msgs → summary (+%d kept)", self.id, len(old), keep_last)
        # ── R5 swarm-domain graph linkage: graph reduction after compaction (derived layer, failures non-blocking) ──
        try:
            from l3.memory.memory_graph import get_graph as _gg

            g = _gg()
            if g.enabled:
                g.compact(min_degree=2, dry_run=False)
        except Exception:
            logger.debug("l3a session: graph compact after compress failed")
        return {
            "success": True,
            "session_id": self.id,
            "compressed": len(old),
            "kept": keep_last,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
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
                "note": ("high-value messages preserved in full; full text recoverable via snapshot_ref")
                if snapshot_ref
                else "snapshot unavailable",
            },
        }

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
            return {"success": True, "action": "skipped", "reason": "auto_compress disabled"}
        if self.status != "active":
            return {"success": True, "action": "skipped", "reason": "session closed"}

        stats = self.context_stats()
        pressure = stats.get("pressure_ratio", 0.0)
        if pressure < threshold and not force:
            return {"success": True, "action": "none", "pressure": pressure, "threshold": threshold}
        if self.history.count() <= keep:
            return {
                "success": True,
                "action": "none",
                "pressure": pressure,
                "threshold": threshold,
                "reason": "history below keep size",
            }
        r = self.compress(keep_last=keep)
        r["action"] = "compressed"
        r["pressure_before"] = pressure
        r["threshold"] = threshold
        logger.info("l3a session %s: auto-compressed at pressure %.2f (threshold %.2f)", self.id, pressure, threshold)
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
            recent = mem.recall(agent_id=_p.AGENT_ID, rings=[1, 2, 3], limit=500)
            ingress: dict[str, Any] = {"count": 0, "by_type": {}}
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
            "success": True,
            "session_id": self.id,
            "window_seconds": window,
            "rings": stats,
            "pressure": pressure,
            "ingress": {
                "count": ingress["count"],
                "per_hour": round(ingress["count"] / max(window / 3600.0, 0.001), 2),
                "by_type": dict(sorted(ingress["by_type"].items(), key=lambda x: x[1], reverse=True)),
            },
        }
