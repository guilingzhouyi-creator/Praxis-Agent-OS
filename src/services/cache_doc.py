"""CacheDocument — addressable session document cache for Agent OS.

Each CacheDocument has a buffer_id, addressable during Agent OS lifetime.
Auto-cleaned on shutdown. Supports optional Archive reference linking.

Two-tier document mechanism:
  - CacheDocument (buffer): valid during Agent OS session, addressed by buffer_id
  - Archive (Ring 4): persistent disk storage, addressed by archive_id
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from kernel.params import CACHE_DOC_MAX_ENTRIES, CACHE_DOC_TTL

logger = logging.getLogger(__name__)


@dataclass
class CacheDocument:
    """Addressable meeting document."""

    buffer_id: str = ""
    title: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    archive_ref: str = ""           # Linked Archive entry_id
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + CACHE_DOC_TTL)
    access_count: int = 0

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


class CacheDocumentStore:
    """CacheDocument store - in-memory stack, valid for Agent OS lifetime.

    Supports:
      - put / get / delete / list
      - tag search
      - expiry cleanup
      - archive_ref linking
    """

    def __init__(self):
        self._docs: dict[str, CacheDocument] = {}
        self._lock = threading.Lock()

    def put(self, title: str, content: str,
            metadata: dict | None = None,
            tags: list[str] | None = None,
            archive_ref: str = "") -> str:
        buffer_id = f"cache-{uuid.uuid4().hex[:12]}"
        doc = CacheDocument(
            buffer_id=buffer_id, title=title, content=content,
            metadata=metadata or {}, tags=tags or [],
            archive_ref=archive_ref,
        )
        with self._lock:
            self._docs[buffer_id] = doc
            self._evict()
        return buffer_id

    def get(self, buffer_id: str) -> CacheDocument | None:
        with self._lock:
            doc = self._docs.get(buffer_id)
            if doc is None:
                return None
            if doc.expired:
                del self._docs[buffer_id]
                return None
            doc.access_count += 1
            return doc

    def get_content(self, buffer_id: str) -> str:
        doc = self.get(buffer_id)
        if doc is None:
            logger.warning("cache_doc get_content: buffer %s not found", buffer_id)
            return ""
        return doc.content

    def delete(self, buffer_id: str) -> bool:
        with self._lock:
            return self._docs.pop(buffer_id, None) is not None

    def list_by_tag(self, tag: str) -> list[dict]:
        with self._lock:
            return [
                {"buffer_id": d.buffer_id, "title": d.title,
                 "tags": d.tags, "created_at": d.created_at,
                 "archive_ref": d.archive_ref,
                 "size": len(d.content)}
                for d in self._docs.values()
                if not d.expired and tag in d.tags
            ]

    def list_all(self) -> list[dict]:
        with self._lock:
            return [
                {"buffer_id": d.buffer_id, "title": d.title,
                 "tags": d.tags, "created_at": d.created_at,
                 "expired": d.expired, "access_count": d.access_count}
                for d in self._docs.values() if not d.expired
            ]

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._docs),
                "tags": len(set(t for d in self._docs.values() for t in d.tags)),
                "max_entries": CACHE_DOC_MAX_ENTRIES,
                "ttl": CACHE_DOC_TTL,
            }

    def archive_ref_count(self) -> int:
        with self._lock:
            return sum(1 for d in self._docs.values() if d.archive_ref)

    def _evict(self) -> None:
        if len(self._docs) <= CACHE_DOC_MAX_ENTRIES:
            return
        sorted_docs = sorted(
            self._docs.values(), key=lambda d: (d.access_count, d.expires_at)
        )
        to_remove = len(self._docs) - CACHE_DOC_MAX_ENTRIES
        for d in sorted_docs[:to_remove]:
            del self._docs[d.buffer_id]


_store: CacheDocumentStore | None = None


def get_store() -> CacheDocumentStore:
    global _store
    if _store is None:
        _store = CacheDocumentStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None
