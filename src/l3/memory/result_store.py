"""ResultStore — deterministic tool result cache with LRU eviction.

AtomCode-style: tool outputs are cached by SHA256(tool_name + canonical_args).
Repeated read-only calls with identical args return cached results.
Write tools (write_file, edit, delete, ...) invalidate matching path prefixes.

Usage:
  from l3.memory.result_store import get_result_store
  store = get_result_store()
  key = store.fingerprint("read_file", {"path": "foo.py"})
  cached = store.get(key)
  if not cached:
      result = execute_tool("read_file", {"path": "foo.py"})
      store.set(key, result, tool_name="read_file", path="foo.py")
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_LONG, RESULT_STORE_MAX_ENTRIES, RESULT_STORE_TTL

logger = logging.getLogger(__name__)

# Write tool names — on execution, invalidate cached results with matching paths
_WRITE_TOOLS: frozenset[str] = frozenset()  # populated lazily via ToolConfig


def _canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, no extra whitespace."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


class ResultStore:
    """Deterministic tool result cache with LRU eviction and write-invalidation."""

    def __init__(self, max_entries: int = RESULT_STORE_MAX_ENTRIES,
                 ttl: float = RESULT_STORE_TTL):
        self.max_entries = max_entries
        self.ttl = ttl
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    def fingerprint(self, tool_name: str, args: dict) -> str:
        """Deterministic cache key for (tool_name + canonical args).

        Returns SHA256 hex digest for collision-resistant identification.
        """
        raw = f"{tool_name}|{_canonical_json(args)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:HASH_TRUNC_LONG]

    def get(self, fp: str) -> dict | None:
        """Get cached result by fingerprint. Returns None on miss or expiry."""
        with self._lock:
            if fp not in self._cache:
                self._misses += 1
                return None
            entry = self._cache[fp]
            if time.time() > entry["expires_at"]:
                del self._cache[fp]
                self._misses += 1
                return None
            self._cache.move_to_end(fp)
            self._hits += 1
            return entry["result"]

    def set(self, fp: str, result: dict, tool_name: str = "",
            path: str = "") -> None:
        """Store a tool result. 'path' enables write-invalidation later."""
        with self._lock:
            self._cache[fp] = {
                "result": result,
                "tool_name": tool_name,
                "path": path,
                "created_at": time.time(),
                "expires_at": time.time() + self.ttl,
            }
            self._cache.move_to_end(fp)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
                logger.debug("result_store: evicted LRU entry")

    def invalidate_for_tool(self, tool_name: str, args: dict | None = None) -> int:
        """Invalidate cached results affected by a write tool.

        If tool_name is a write tool, invalidates all entries.
        If path is in args, also invalidates entries matching that path.
        """
        inv_path = (args or {}).get("path", "")
        with self._lock:
            before = len(self._cache)
            keys_to_del = []
            for fp, entry in self._cache.items():
                if entry["tool_name"] == tool_name or inv_path and entry["path"] and inv_path in entry["path"]:
                    keys_to_del.append(fp)
            for fp in keys_to_del:
                del self._cache[fp]
            n = before - len(self._cache)
            if n:
                self._invalidations += n
            return n

    def invalidate_path(self, path: str) -> int:
        """Invalidate all cached results referencing a given path."""
        with self._lock:
            before = len(self._cache)
            keys = [fp for fp, e in self._cache.items()
                    if e.get("path") and path in e["path"]]
            for fp in keys:
                del self._cache[fp]
            n = before - len(self._cache)
            if n:
                self._invalidations += n
            return n

    def clear(self) -> None:
        """Clear the result cache and reset all counters."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._invalidations = 0

    def stats(self) -> dict:
        """Return cache statistics: entries, counters, and hit rate."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "invalidations": self._invalidations,
                "hit_rate": round(self._hits / max(total, 1) * 100, 1),
            }


_store: ResultStore | None = None
_store_lock = threading.Lock()


def get_result_store() -> ResultStore:
    """Get the ResultStore singleton, creating it on first call."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ResultStore()
    return _store


def reset_result_store() -> None:
    """Reset the ResultStore singleton (for testing)."""
    global _store
    _store = None
