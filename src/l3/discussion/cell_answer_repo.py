"""CellAnswerRepo — per-Cell answer persistence with checkpoint recovery.

Each Cell gets its own CellAnswerRepo instance.  Answers are persisted to:
  - Archive SQLite (tagged with cell_id, session_id, agent_id, phase)
  - Ring 3 FTS5 (full-text indexed for search)

Checkpoints enable crash recovery: after watchdog reboot, AnswerSession
reads the latest checkpoint and resumes from the failed phase without
re-executing completed phases.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from l1.kernel.params.system import (
    CONVERGENCE_BUFFER_SIZE,
    HASH_TRUNC_LONG,
    LOG_TRUNC_2000,
    LOG_TRUNC_5000,
    MEMORY_IMPORTANCE_CRITICAL,
    MEMORY_IMPORTANCE_HIGH,
)

logger = logging.getLogger(__name__)


# ── Data types ───────────────────────────────────────────────

@dataclass
class CellAnswer:
    """A structured answer from one agent in one Cell."""
    cell_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    phase: int = 0
    answer_type: str = "answer"       # "answer"|"examination"|"rebuttal"|"supplement"|"resolution"
    content: dict = field(default_factory=dict)
    fingerprint: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()
        if not self.fingerprint:
            raw = json.dumps(self.content, sort_keys=True, default=str)
            self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:HASH_TRUNC_LONG]


@dataclass
class AnswerCheckpoint:
    """Snapshot of AnswerSession phase state for crash recovery."""
    session_id: str = ""
    cell_id: str = ""
    phase: int = 0
    phase_name: str = ""
    status: str = "in_progress"       # "in_progress" | "completed" | "failed"
    completed_agents: list[str] = field(default_factory=list)
    pending_agents: list[str] = field(default_factory=list)
    answer_count: int = 0
    supplement_count: int = 0
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()


# ── Repository ────────────────────────────────────────────────

class CellAnswerRepo:
    """Per-Cell answer persistence with checkpoints.

    Thread-safe.  Persists to:
      1. Archive SQLite (via archive_store tool)
      2. Ring 3 FTS5 (via MemoryManager.remember())
    """

    def __init__(self, cell_id: str, session_id: str):
        self.cell_id = cell_id
        self.session_id = session_id
        self._lock = threading.RLock()
        # Ring buffer for fast in-memory access (per-phase, bounded by CONVERGENCE_BUFFER_SIZE)
        self._answers: dict[str, deque] = {}
        self._checkpoints: list[AnswerCheckpoint] = []

    # ── Answer CRUD ───────────────────────────────────────────

    def store_answer(self, answer: CellAnswer) -> dict:
        """Persist an answer to Archive + Ring 3 + in-memory buffer."""
        answer.cell_id = self.cell_id
        answer.session_id = self.session_id
        answer.created_at = time.time()

        phase_key = str(answer.phase)
        with self._lock:
            buf = self._answers.get(phase_key)
            if buf is None:
                buf = deque(maxlen=CONVERGENCE_BUFFER_SIZE)
                self._answers[phase_key] = buf
            buf.append(answer)

        # Persist to Archive SQLite
        try:
            self._archive_store(answer)
        except Exception as e:
            logger.warning("answer_repo: archive store failed: %s", e)

        # Persist to Ring 3 for FTS5 search
        try:
            self._ring3_store(answer)
        except Exception as e:
            logger.warning("answer_repo: ring3 store failed: %s", e)

        return {"success": True, "fingerprint": answer.fingerprint}

    def get_answers(self, phase: int = 0,
                    answer_type: str = "") -> list[CellAnswer]:
        """Get answers for a given phase, optionally filtered by type."""
        with self._lock:
            phase_key = str(phase)
            results = list(self._answers.get(phase_key, []))
        if answer_type:
            results = [a for a in results if a.answer_type == answer_type]
        return results

    def get_all(self) -> list[CellAnswer]:
        """Get all answers across all phases."""
        with self._lock:
            results: list[CellAnswer] = []
            for phase_buf in self._answers.values():
                results.extend(phase_buf)
            return results

    # ── Checkpoint management ─────────────────────────────────

    def save_checkpoint(self, checkpoint: AnswerCheckpoint) -> dict:
        """Save a checkpoint and persist to disk."""
        checkpoint.cell_id = self.cell_id
        checkpoint.session_id = self.session_id
        checkpoint.created_at = time.time()

        with self._lock:
            self._checkpoints.append(checkpoint)
            # Keep last 10 checkpoints
            if len(self._checkpoints) > 10:
                self._checkpoints = self._checkpoints[-10:]

        # Persist checkpoint to Ring 3
        try:
            self._persist_checkpoint(checkpoint)
        except Exception as e:
            logger.warning("answer_repo: checkpoint persist: %s", e)

        return {"success": True, "phase": checkpoint.phase}

    def latest_checkpoint(self) -> AnswerCheckpoint | None:
        """Get the latest checkpoint for crash recovery."""
        with self._lock:
            if not self._checkpoints:
                return None
            return self._checkpoints[-1]

    def get_checkpoint(self, phase: int) -> AnswerCheckpoint | None:
        """Get checkpoint for a specific phase."""
        with self._lock:
            for cp in reversed(self._checkpoints):
                if cp.phase == phase:
                    return cp
            return None

    # ── Persistence backends ──────────────────────────────────

    def _archive_store(self, answer: CellAnswer) -> None:
        """Store answer in Archive SQLite with tags."""
        try:
            from l3.tools._archive import archive_store
            tags = [
                f"cell:{self.cell_id}",
                f"session:{self.session_id}",
                f"agent:{answer.agent_id}",
                f"phase:{answer.phase}",
                f"type:{answer.answer_type}",
            ] + (answer.tags or [])
            archive_store("answer_repo", "answer", {
                "fonds": f"CELL:{self.cell_id}:{self.session_id}",
                "series": f"phase:{answer.phase}",
                "title": f"{answer.agent_id}/{answer.answer_type}",
                "content": json.dumps(answer.content, default=str)[:LOG_TRUNC_5000],
                "tags": ",".join(tags),
            })
        except Exception:
            raise

    def _ring3_store(self, answer: CellAnswer) -> None:
        """Store answer in Ring 3 for FTS5 searchability."""
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            mem.remember(
                agent_id=answer.agent_id,
                cell_id=self.cell_id,
                entry_type=f"discussion.{answer.answer_type}",
                content=json.dumps(answer.content, default=str)[:LOG_TRUNC_2000],
                ring=3,
                importance=MEMORY_IMPORTANCE_HIGH,
                tags=list(answer.tags or []) + [
                    "discussion", self.session_id,
                    f"phase:{answer.phase}",
                ],
            )
        except Exception:
            raise

    def _persist_checkpoint(self, cp: AnswerCheckpoint) -> None:
        """Persist checkpoint to Ring 3 for crash recovery."""
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            mem.remember(
                agent_id="system",
                cell_id=self.cell_id,
                entry_type="discussion.checkpoint",
                content=json.dumps({
                    "session_id": cp.session_id,
                    "phase": cp.phase,
                    "phase_name": cp.phase_name,
                    "status": cp.status,
                    "completed_agents": cp.completed_agents,
                    "pending_agents": cp.pending_agents,
                }, default=str)[:LOG_TRUNC_2000],
                ring=3,
                importance=MEMORY_IMPORTANCE_CRITICAL,
                tags=["discussion", "checkpoint", self.session_id],
            )
        except Exception:
            raise

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return repository statistics (answers, phases, checkpoints)."""
        with self._lock:
            total = sum(len(v) for v in self._answers.values())
            return {
                "cell_id": self.cell_id,
                "session_id": self.session_id,
                "total_answers": total,
                "phases": sorted(self._answers.keys()),
                "checkpoints": len(self._checkpoints),
                "latest_phase": self._checkpoints[-1].phase if self._checkpoints else 0,
            }
