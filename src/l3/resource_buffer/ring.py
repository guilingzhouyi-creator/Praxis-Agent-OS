"""RingBuffer — async ring file buffer for delayed write operations.

Each file gets a hash directory under .praxis/resource_buffer/:
  <hash>/_pending/slot_NNNN.dat   — staged modifications (ring)
  <hash>/_checkpoint.dat           — last committed snapshot
  <hash>/_hidden/                  — timed-out pending slots
  <hash>/_journal.jsonl            — operation journal for crash recovery
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


from l1.kernel.params.system import (
    HASH_TRUNC_LONG,
    RESOURCE_BUFFER_AUTO_EXPAND,
    RESOURCE_BUFFER_CHECKPOINT_FILE,
    RESOURCE_BUFFER_FLUSH_INTERVAL,
    RESOURCE_BUFFER_HIDDEN_DIR,
    RESOURCE_BUFFER_HIDDEN_TTL,
    RESOURCE_BUFFER_JOURNAL_FILE,
    RESOURCE_BUFFER_PENDING_DIR,
    RESOURCE_BUFFER_ROOT_DIR,
    RESOURCE_BUFFER_SLOT_CAPACITY,
    RESOURCE_BUFFER_SLOT_GLOB,
    RESOURCE_BUFFER_SLOT_NAME,
)
from l1.kernel.paths import get_paths as _gp


class RingBuffer:
    """Ring file buffer — not in-memory, backed by hidden files."""

    RING_ROOT: str = ""
    SLOT_CAPACITY: int = RESOURCE_BUFFER_SLOT_CAPACITY
    SLOT_NAME: str = RESOURCE_BUFFER_SLOT_NAME
    AUTO_EXPAND: bool = RESOURCE_BUFFER_AUTO_EXPAND
    FLUSH_INTERVAL: float = RESOURCE_BUFFER_FLUSH_INTERVAL
    HIDDEN_TTL: float = RESOURCE_BUFFER_HIDDEN_TTL

    def __init__(self, root: str = ""):
        self.RING_ROOT = os.path.join(_gp().data_dir, RESOURCE_BUFFER_ROOT_DIR)
        self._root = Path(root or self.RING_ROOT)
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._running = True
        self._thread = threading.Thread(target=self._flush_loop, daemon=True,
                                        name="resource-buffer-flush")
        self._thread.start()

    def stop(self) -> None:
        """Stop the flush loop thread."""
        self._running = False

    # ── Hash ──

    @staticmethod
    def _hash(path: str) -> str:
        return hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:HASH_TRUNC_LONG]

    def _lock_for(self, path: str) -> threading.Lock:
        h = self._hash(path)
        if h not in self._locks:
            self._locks[h] = threading.Lock()
        return self._locks[h]

    # ── Core API ──

    def stage(self, path: str, content: str, op: str = "edit") -> dict:
        """Store a file modification into the ring buffer (no disk commit)."""
        file_hash = self._hash(path)
        slot_dir = self._root / file_hash / RESOURCE_BUFFER_PENDING_DIR
        slot_dir.mkdir(parents=True, exist_ok=True)

        with self._lock_for(path):
            slot_idx = self._next_slot(slot_dir)
            slot_file = slot_dir / self.SLOT_NAME.format(slot_idx)
            slot_file.write_text(content, encoding="utf-8")
            self._append_journal(file_hash, slot_idx, path, op)
            logger.debug("buffer stage[%d]: %s (%s)", slot_idx, path, op)

        return {"success": True, "slot": slot_idx, "path": path, "operation": op}

    def commit(self, path: str) -> dict:
        """Merge all pending slots → write real file → clear slots."""
        file_hash = self._hash(path)
        slot_dir = self._root / file_hash / RESOURCE_BUFFER_PENDING_DIR

        with self._lock_for(path):
            if not slot_dir.exists():
                return {"success": False, "error": "no pending changes", "path": path}

            slots = sorted(slot_dir.glob(RESOURCE_BUFFER_SLOT_GLOB))
            if not slots:
                return {"success": False, "error": "no pending slots", "path": path}

            # Read latest content from last slot
            latest = slots[-1].read_text(encoding="utf-8")

            # Write to real file
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(latest)

            # Write checkpoint
            checkpoint = self._root / file_hash / RESOURCE_BUFFER_CHECKPOINT_FILE
            checkpoint.write_text(latest, encoding="utf-8")

            # Clean slots
            for sf in slots:
                sf.unlink(missing_ok=True)

            logger.info("buffer commit: %s (%d slots merged)", path, len(slots))

        return {"success": True, "path": path, "slots_merged": len(slots)}

    def commit_all(self) -> dict:
        """Commit all files with pending buffers."""
        results = {}
        for pending_dir in self._root.rglob(RESOURCE_BUFFER_PENDING_DIR):
            if not pending_dir.is_dir():
                continue
            # Walk the closest parent that has a journal to find file path
            file_hash = pending_dir.parent.name
            journal = self._root / file_hash / RESOURCE_BUFFER_JOURNAL_FILE
            if not journal.exists():
                continue
            path = self._resolve_path_from_journal(journal)
            if path:
                results[path] = self.commit(path)
        return {"success": True, "committed": len(results), "results": results}

    def discard(self, path: str) -> dict:
        """Discard all pending buffer changes for a file."""
        file_hash = self._hash(path)
        target = self._root / file_hash
        with self._lock_for(path):
            if target.exists():
                shutil.rmtree(target)
        return {"success": True, "path": path}

    def read(self, path: str) -> str:
        """Read file content — buffer first, then real file."""
        file_hash = self._hash(path)
        slot_dir = self._root / file_hash / RESOURCE_BUFFER_PENDING_DIR

        # Check pending slots first
        if slot_dir.exists():
            with self._lock_for(path):
                slots = sorted(slot_dir.glob(RESOURCE_BUFFER_SLOT_GLOB))
                if slots:
                    return slots[-1].read_text(encoding="utf-8")

        # Check checkpoint
        checkpoint = self._root / file_hash / RESOURCE_BUFFER_CHECKPOINT_FILE
        if checkpoint.exists():
            return checkpoint.read_text(encoding="utf-8")

        # Fall back to real file
        with open(path, encoding="utf-8") as f:
            return f.read()

    def diff(self, path: str) -> dict:
        """Show diff between pending buffer and committed/real file."""
        file_hash = self._hash(path)
        slot_dir = self._root / file_hash / RESOURCE_BUFFER_PENDING_DIR
        checkpoint = self._root / file_hash / RESOURCE_BUFFER_CHECKPOINT_FILE

        with self._lock_for(path):
            # Get base content
            if checkpoint.exists():
                old = checkpoint.read_text(encoding="utf-8")
            else:
                try:
                    with open(path, encoding="utf-8") as f:
                        old = f.read()
                except FileNotFoundError:
                    old = ""

            # Get pending content
            if slot_dir.exists():
                slots = sorted(slot_dir.glob(RESOURCE_BUFFER_SLOT_GLOB))
                if slots:
                    new = slots[-1].read_text(encoding="utf-8")
                else:
                    return {"success": False, "error": "no pending changes", "path": path}
            else:
                return {"success": False, "error": "no pending changes", "path": path}

        diff = list(difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}",
        ))
        return {"success": True, "path": path, "diff": diff, "lines": len(diff)}

    def status(self) -> dict:
        """Buffer statistics — files with pending changes."""
        files = []
        total_slots = 0
        for pending_dir in self._root.rglob(RESOURCE_BUFFER_PENDING_DIR):
            if not pending_dir.is_dir():
                continue
            slots = list(pending_dir.glob(RESOURCE_BUFFER_SLOT_GLOB))
            if not slots:
                continue
            file_hash = pending_dir.parent.name
            journal = self._root / file_hash / RESOURCE_BUFFER_JOURNAL_FILE
            path = self._resolve_path_from_journal(journal) or file_hash
            oldest = min(s.stat().st_mtime for s in slots)
            files.append({"path": path, "slots": len(slots), "oldest_age_s": time.time() - oldest,
                          "hash": file_hash})
            total_slots += len(slots)
        return {"success": True, "files": files, "total_files": len(files),
                "total_slots": total_slots, "root": str(self._root)}

    # ── Journal ──

    def _append_journal(self, file_hash: str, slot_idx: int,
                        path: str, op: str) -> None:
        journal = self._root / file_hash / RESOURCE_BUFFER_JOURNAL_FILE
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "slot": slot_idx, "path": path, "op": op,
                "ts": time.time(),
            }, ensure_ascii=False) + "\n")

    def _resolve_path_from_journal(self, journal: Path) -> str:
        """Read the last journal entry to find the original file path."""
        try:
            with open(journal, encoding="utf-8") as f:
                last_line = None
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
                if last_line:
                    return json.loads(last_line).get("path", "")
        except Exception:
            logger.debug("ring: last slot path failed")
        return ""

    # ── Slot management ──

    def _next_slot(self, slot_dir: Path) -> int:
        existing = list(slot_dir.glob(RESOURCE_BUFFER_SLOT_GLOB))
        if not existing:
            return 0
        indices = sorted(int(sf.stem.split("_")[1]) for sf in existing)
        if len(indices) < self.SLOT_CAPACITY:
            return indices[-1] + 1
        if self.AUTO_EXPAND:
            return indices[-1] + 1  # auto-expand by allowing higher indices
        raise RuntimeError(f"ring buffer full for {slot_dir}")

    # ── Background flush ──

    def _flush_loop(self) -> None:
        """Background: move stale pending slots to _hidden/."""
        while self._running:
            time.sleep(5)
            try:
                self._flush_stale_slots()
            except Exception as e:
                logger.warning("buffer flush: %s", e)

    def _flush_stale_slots(self) -> None:
        now = time.time()
        for pending_dir in self._root.rglob(RESOURCE_BUFFER_PENDING_DIR):
            if not pending_dir.is_dir():
                continue
            hidden_dir = pending_dir.parent / RESOURCE_BUFFER_HIDDEN_DIR
            for slot_file in pending_dir.glob(RESOURCE_BUFFER_SLOT_GLOB):
                try:
                    age = now - slot_file.stat().st_mtime
                    if age > self.HIDDEN_TTL:
                        hidden_dir.mkdir(exist_ok=True)
                        shutil.move(str(slot_file), str(hidden_dir / slot_file.name))
                        logger.debug("buffer flushed to _hidden: %s", slot_file)
                except Exception:
                    logger.debug("ring: flush move failed")

    # ── Recovery ──

    def recover(self) -> dict:
        """On boot: scan _hidden/ and journal, restore pending status."""
        recovered = 0
        for hidden_dir in self._root.rglob(RESOURCE_BUFFER_HIDDEN_DIR):
            if not hidden_dir.is_dir():
                continue
            pending_dir = hidden_dir.parent / RESOURCE_BUFFER_PENDING_DIR
            pending_dir.mkdir(exist_ok=True)
            for f in hidden_dir.glob(RESOURCE_BUFFER_SLOT_GLOB):
                shutil.move(str(f), str(pending_dir / f.name))
                recovered += 1
        logger.info("buffer recover: %d slots restored from _hidden/", recovered)
        return {"success": True, "recovered": recovered}
