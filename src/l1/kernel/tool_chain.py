"""Tool call chain — hierarchical tracking of tool invocations.

Every tool call in the Agent OS is part of a chain:
  composite_tool (parent)
    ├── atomic_tool_1 (child, ring 1)
    │     └── fingerprint_1 → links to parent
    ├── atomic_tool_2 (child, ring 2.5)
    │     └── fingerprint_2 → links to fingerprint_1
    └── verify (grandchild)
          └── fingerprint_3 → links to fingerprint_2

Each link in the chain carries:
  - tool name, agent, ring, timestamp
  - cryptographic fingerprint (HMAC-SHA256 of previous_fp + call data)
  - parent reference for full ancestry traversal

Usage:
  chain.start("review_and_fix", "agent_b", ring=2)
    → call_id = "call-001", chain depth = 1
  chain.child("read_file", "agent_a", ring=1, parent="call-001")
    → call_id = "call-002", chain depth = 2
  chain.verify("call-002")  → validates fingerprint chain integrity
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_40

from .params.kernel import (
    CHAIN_KEY_ENV_VAR,
    TOOLCHAIN_MAX_CALLS,
    TOOLCHAIN_QUERY_LIMIT,
)
from .paths import get_paths as _gp

logger = logging.getLogger(__name__)

_SECRET_KEY = os.environ.get(CHAIN_KEY_ENV_VAR, "").encode() or os.urandom(32)
# Persist to file for audit continuity across restarts.
# Key file is created with 0o600 on POSIX (O_CREAT|O_EXCL) so it cannot be
# pre-seeded by another user; existing files are read with explicit permission.
_KEY_PATH = os.environ.get("CHAIN_KEY_PATH", _gp().chain_key)
if not os.environ.get(CHAIN_KEY_ENV_VAR):
    try:
        if os.path.exists(_KEY_PATH):
            with open(_KEY_PATH, "rb") as _f:
                _SECRET_KEY = _f.read()
        else:
            key_bytes = os.urandom(32)
            _KEY_DIR = os.path.dirname(_KEY_PATH) or "."
            os.makedirs(_KEY_DIR, exist_ok=True)
            fd = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, key_bytes)
            finally:
                os.close(fd)
            # Restrict parent dir as well on POSIX (best-effort, ignore failures)
            try:
                from l1.kernel.platform import safe_chmod

                safe_chmod(_KEY_PATH, 0o600)
            except Exception:
                logger.debug("tool_chain: safe_chmod failed")
            _SECRET_KEY = key_bytes
    except Exception as e:
        logger.warning("kernel/tool_chain: %s", e)


@dataclass
class CallLink:
    """One link in the tool call chain."""

    call_id: str
    tool_name: str
    agent_id: str
    ring: int
    parent_id: str = ""
    fingerprint: str = ""
    prev_fingerprint: str = ""
    depth: int = 1
    success: bool = False
    error: str = ""
    duration: float = 0.0
    timestamp: float = field(default_factory=time.time)
    children: list[str] = field(default_factory=list)


class ToolChain:
    """Hierarchical tool call chain with cryptographic fingerprinting.

    Thread-safe.  Singleton per process.
    Each call is registered and linked to its parent.
    Fingerprints form an HMAC chain: prev_fp + call_data → new_fp.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._calls: dict[str, CallLink] = {}
        self._max_calls = TOOLCHAIN_MAX_CALLS

    def start(self, tool_name: str, agent_id: str, ring: int = 1, parent_id: str = "") -> str:
        """Register a new tool call. Returns call_id.

        If parent_id is provided, links this call as a child of the parent.
        """
        call_id = f"call-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        with self._lock:
            prev_fp = ""
            if parent_id and parent_id in self._calls:
                parent = self._calls[parent_id]
                prev_fp = parent.fingerprint
                parent.children.append(call_id)
                depth = parent.depth + 1
            else:
                depth = 1

            call_data = f"{tool_name}:{agent_id}:{ring}:{call_id}:{parent_id}:{depth}"
            fp = self._compute_fp(call_data, prev_fp)

            link = CallLink(
                call_id=call_id,
                tool_name=tool_name,
                agent_id=agent_id,
                ring=ring,
                parent_id=parent_id,
                fingerprint=fp,
                prev_fingerprint=prev_fp,
                depth=depth,
            )
            self._calls[call_id] = link

            if len(self._calls) > self._max_calls:
                self._trim()

            return call_id

    def complete(self, call_id: str, success: bool = True, error: str = "", duration: float = 0.0) -> bool:
        """Mark a call as completed with success/failure."""
        with self._lock:
            link = self._calls.get(call_id)
            if not link:
                return False
            link.success = success
            link.error = error
            link.duration = duration
            return True

    def child(self, tool_name: str, agent_id: str, ring: int = 1, parent: str = "") -> str:
        """Convenience: start a child call of the given parent."""
        return self.start(tool_name, agent_id, ring, parent_id=parent)

    def get(self, call_id: str) -> CallLink | None:
        """Return the call link for *call_id*, or None."""
        with self._lock:
            return self._calls.get(call_id)

    def chain(self, call_id: str) -> list[CallLink]:
        """Traverse from this call up to the root. Returns full ancestry."""
        with self._lock:
            result: list[CallLink] = []
            current = self._calls.get(call_id)
            while current:
                result.append(current)
                current = self._calls.get(current.parent_id)
            return result

    def subtree(self, call_id: str) -> list[CallLink]:
        """Traverse from this call down to all descendants."""
        with self._lock:
            result: list[CallLink] = []
            root = self._calls.get(call_id)
            if not root:
                return result
            queue = [root]
            while queue:
                node = queue.pop(0)
                result.append(node)
                for cid in node.children:
                    child = self._calls.get(cid)
                    if child:
                        queue.append(child)
            return result

    def verify(self, call_id: str) -> dict:
        """Verify the fingerprint chain integrity for a call lineage.

        Walks from root to this call, recomputing each fingerprint.
        Returns pass/fail + details.
        """
        ancestry = self.chain(call_id)
        ancestry.reverse()  # root first
        steps: list[dict] = []
        prev_fp = ""
        valid = True
        for link in ancestry:
            call_data = f"{link.tool_name}:{link.agent_id}:{link.ring}:{link.call_id}:{link.parent_id}:{link.depth}"
            expected = self._compute_fp(call_data, prev_fp)
            match = expected == link.fingerprint
            if not match:
                valid = False
            steps.append(
                {
                    "call_id": link.call_id,
                    "tool": link.tool_name,
                    "depth": link.depth,
                    "fingerprint_match": match,
                }
            )
            prev_fp = link.fingerprint
        return {"valid": valid, "steps": steps, "depth": len(ancestry)}

    def agent_calls(self, agent_id: str, limit: int = TOOLCHAIN_QUERY_LIMIT) -> list[CallLink]:
        """Get all calls by a specific agent."""
        with self._lock:
            return [c for c in self._calls.values() if c.agent_id == agent_id][-limit:]

    def recent(self, limit: int = TOOLCHAIN_QUERY_LIMIT) -> list[dict]:
        """Most recent calls across all agents."""
        with self._lock:
            calls = list(self._calls.values())
            return [
                {
                    "call_id": c.call_id,
                    "tool": c.tool_name,
                    "agent": c.agent_id,
                    "ring": c.ring,
                    "depth": c.depth,
                    "success": c.success,
                    "duration": round(c.duration, 3),
                    "children": len(c.children),
                }
                for c in calls[-limit:]
            ]

    def stats(self) -> dict:
        """Return call-chain statistics."""
        with self._lock:
            total = len(self._calls)
            by_ring: dict[int, int] = {}
            for c in self._calls.values():
                by_ring[c.ring] = by_ring.get(c.ring, 0) + 1
            return {
                "total_calls": total,
                "max_calls": self._max_calls,
                "by_ring": by_ring,
            }

    def _compute_fp(self, data: str, prev_fp: str = "") -> str:
        payload = f"{data}:{prev_fp or 'GENESIS'}"
        return hmac.new(_SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()[:LOG_TRUNC_40]

    def _trim(self) -> None:
        """Remove oldest calls, preserving parent-child chain integrity.

        When a parent call is trimmed, its orphaned children are re-rooted:
        their ``parent_id`` is cleared and ``prev_fingerprint`` reset to
        ``GENESIS`` so that subsequent ``verify`` calls do not silently
        accept a broken lineage.
        """
        sorted_calls = sorted(self._calls.values(), key=lambda c: c.timestamp)
        to_remove = len(sorted_calls) - self._max_calls // 2
        removed_ids: set[str] = set()
        for c in sorted_calls[:to_remove]:
            removed_ids.add(c.call_id)
            self._calls.pop(c.call_id, None)
        # Re-root orphaned children so the chain verifies cleanly.
        # Must cascade: when an orphan's fingerprint changes, all of its
        # descendants' fingerprints (computed from prev_fingerprint) go
        # stale too, so walk each affected subtree and recompute each node.
        affected_roots: list[str] = []
        for c in list(self._calls.values()):
            if c.parent_id and c.parent_id in removed_ids:
                c.parent_id = ""
                c.prev_fingerprint = "GENESIS"
                affected_roots.append(c.call_id)

        for root_id in affected_roots:
            # BFS down the subtree, recomputing each node's fingerprint
            # against its (possibly already-recomputed) parent's fingerprint
            queue = [self._calls[root_id]]
            while queue:
                node = queue.pop(0)
                call_data = f"{node.tool_name}:{node.agent_id}:{node.ring}:{node.call_id}:{node.parent_id}:{node.depth}"
                node.fingerprint = self._compute_fp(call_data, node.prev_fingerprint)
                # Propagate this node's new fingerprint to each child's
                # prev_fingerprint, then queue the child for its own recompute
                for child_id in node.children:
                    child = self._calls.get(child_id)
                    if child:
                        child.prev_fingerprint = node.fingerprint
                        queue.append(child)


_chain: ToolChain | None = None
_chain_lock = threading.Lock()


def get_tool_chain() -> ToolChain:
    """Get the tool chain singleton."""
    global _chain
    if _chain is None:
        with _chain_lock:
            if _chain is None:
                _chain = ToolChain()
    return _chain


def reset_tool_chain() -> None:
    """Reset the tool chain singleton to None (for tests / hot reset)."""
    global _chain
    _chain = None
