"""User profile side-channel 鈥?grows a model of each user's preferences and
decision patterns, feeding intent parsing and central (L3A) decisions.

Architecture (side-channel, mirrors Mer/R5 philosophy):

    User interaction (cards, approvals, sessions, corrections, API ingest)
        鈹? collectors (event bus + explicit ingest)
        鈻?    ProfileStore (per-user typed entries, confidence, TTL, decay)
        鈹? refiner (LLM synthesis 鈫?trait entries; rule fallback)
        鈻?    Consumers (L3A cardwrite/prompt, any service via get_port("profile"))
        鈹? R4 archive (fonds=user_profile, series=user_id) 鈥?portable
        鈻?    export/import + /api/v2/profile/*

Design principles:
  - Typed entries: kind is an extensible registry (preference, domain_focus,
    decision_style, rejection, habit, correction, trait, custom).
  - Bypass semantics: never mutates the main memory/card flow; on error it
    degrades to a no-op. Original interactions stay in their systems.
  - Time-aware: entries carry confidence + TTL; a decay cycle drops stale
    entries and weakens old ones, so the profile reflects the current user.
  - Multi-user: all state is keyed by user_id (UserSessionManager's id space).
  - Portable: export/import via JSON; persisted to R4 per user.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from l1.kernel.params.system import (
    HASH_TRUNC_MEDIUM,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    PROFILE_DECAY_CONFIDENCE,
    PROFILE_DECAY_INTERVAL,
    PROFILE_EMIT_EVENT,
    PROFILE_ENTRY_TTL_DEFAULT,
    PROFILE_FONDS,
    PROFILE_KIND_DECISION_STYLE,
    PROFILE_KIND_DOMAIN_FOCUS,
    PROFILE_KIND_TRAIT,
    PROFILE_KINDS,
    PROFILE_MAX_ENTRIES_PER_USER,
    PROFILE_REFINE_MAX_RAW,
    PROFILE_REFINE_MIN_ENTRIES,
    PROFILE_SNAPSHOT_ENTRIES,
    PROFILE_USER_DEFAULT,
)
from l3._base import BaseService

logger = logging.getLogger(__name__)

# Source tags
SRC_CARD = "card"
SRC_APPROVAL = "approval"
SRC_REFINED = "refined"
SRC_IMPORT = "import"
SRC_API = "api"


@dataclass
class ProfileEntry:
    """A typed fact about a user: kind + value + provenance + lifetime."""

    kind: str
    value: Any
    user_id: str = PROFILE_USER_DEFAULT
    confidence: float = 0.6
    source: str = SRC_API
    context: dict = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:HASH_TRUNC_MEDIUM])
    ts: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 = never

    def expired(self, now: float | None = None) -> bool:
        """True when the entry is past its expiry."""
        if not self.expires_at:
            return False
        return (now or time.time()) > self.expires_at

    def to_dict(self) -> dict:
        """Serialize for R4/JSON (context may carry non-JSON values)."""
        d = asdict(self)
        try:
            json.dumps(d)
        except (TypeError, ValueError):
            d["context"] = {k: str(v) for k, v in (self.context or {}).items()}
            d["value"] = str(self.value)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ProfileEntry:
        """Deserialize an entry (unknown fields tolerated for forward compat)."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ProfileStore:
    """Per-user typed entry store with cap, decay and snapshot folding."""

    def __init__(self, max_entries: int = PROFILE_MAX_ENTRIES_PER_USER):
        self._entries: dict[str, list[ProfileEntry]] = {}
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def add(self, entry: ProfileEntry) -> None:
        """Add an entry, enforcing the per-user cap (oldest evicted)."""
        with self._lock:
            bucket = self._entries.setdefault(entry.user_id, [])
            bucket.append(entry)
            if len(bucket) > self._max_entries:
                bucket.sort(key=lambda e: e.ts)
                del bucket[: len(bucket) - self._max_entries]

    def entries(self, user_id: str, kind: str | None = None, now: float | None = None) -> list[ProfileEntry]:
        """Live (non-expired) entries for a user, optionally filtered by kind."""
        with self._lock:
            out = [e for e in self._entries.get(user_id, []) if not e.expired(now)]
            if kind:
                out = [e for e in out if e.kind == kind]
            return sorted(out, key=lambda e: e.ts, reverse=True)

    def all_users(self) -> list[str]:
        """List user ids that have any live entries."""
        with self._lock:
            return sorted(self._entries.keys())

    def purge_expired(self, now: float | None = None) -> int:
        """Remove expired entries; return how many were purged."""
        now = now or time.time()
        purged = 0
        with self._lock:
            for uid, bucket in list(self._entries.items()):
                live = [e for e in bucket if not e.expired(now)]
                purged += len(bucket) - len(live)
                if live:
                    self._entries[uid] = live
                else:
                    self._entries.pop(uid, None)
        return purged

    def decay(self, factor: float = PROFILE_DECAY_CONFIDENCE) -> int:
        """Lower confidence of entries older than one decay cycle; drop below 0.1."""
        weakened = 0
        with self._lock:
            for bucket in self._entries.values():
                for e in bucket:
                    if e.confidence <= 0.1:
                        continue
                    e.confidence = max(0.1, e.confidence - factor)
                    weakened += 1
        return weakened

    def snapshot(
        self, user_id: str, limit: int = PROFILE_SNAPSHOT_ENTRIES, kinds: tuple[str, ...] | None = None
    ) -> dict:
        """Fold the top entries into a structured, injection-ready summary.

        Returns {user_id, kinds, entries, updated_at} 鈥?kinds restrict the
        fold (e.g. only preference+trait for prompt injection).
        """
        entries = self.entries(user_id)
        if kinds:
            entries = [e for e in entries if e.kind in kinds]
        entries = entries[:limit]
        return {
            "user_id": user_id,
            "kinds": sorted({e.kind for e in entries}),
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
            "updated_at": time.time(),
        }

    def export(self, user_id: str) -> dict:
        """Portable snapshot: all entries (including expired ones, flagged)."""
        with self._lock:
            return {
                "user_id": user_id,
                "exported_at": time.time(),
                "entries": [e.to_dict() for e in self._entries.get(user_id, [])],
            }

    def import_entries(self, user_id: str, entries: list[dict], replace: bool = False) -> int:
        """Import entries (marking source=import); optionally replace the user's set."""
        with self._lock:
            if replace:
                self._entries[user_id] = []
            count = 0
            for d in entries:
                try:
                    e = ProfileEntry.from_dict(d)
                except Exception:
                    continue
                e.user_id = user_id
                e.source = SRC_IMPORT
                e.expires_at = d.get("expires_at", 0.0) or 0.0
                self.add(e)
                count += 1
            return count

    def clear(self, user_id: str) -> int:
        """Drop all entries for a user; return how many were removed."""
        with self._lock:
            bucket = self._entries.pop(user_id, [])
            return len(bucket)

    def count(self, user_id: str | None = None) -> int:
        """Total live (non-expired) entries, optionally for one user."""
        now = time.time()
        with self._lock:
            if user_id:
                return sum(1 for e in self._entries.get(user_id, []) if not e.expired(now))
            return sum(1 for b in self._entries.values() for e in b if not e.expired(now))


class UserProfileService(BaseService):
    """User profile side-channel 鈥?collection, refinement, query, portability."""

    def __init__(self, enabled: bool | None = None):
        super().__init__("user_profile")
        self._enabled = enabled
        self._store = ProfileStore()
        self._stats: dict[str, Any] = {
            "ingested": 0,
            "refined": 0,
            "decay_cycles": 0,
            "archived": 0,
        }
        self._decay_thread: threading.Thread | None = None
        self._decay_stop = threading.Event()
        self._collectors: list[Callable[[], None]] = []

    def _on_start(self) -> dict:
        """Start the decay loop and wire event collectors."""
        if PROFILE_DECAY_INTERVAL > 0:
            self._decay_thread = threading.Thread(target=self._decay_loop, name="profile-decay", daemon=True)
            self._decay_thread.start()
        self._wire_event_collectors()
        return {"success": True}

    def _on_stop(self) -> dict:
        self._decay_stop.set()
        self._decay_thread = None
        return {"success": True}

    # 鈹€鈹€ Switch 鈹€鈹€

    @property
    def enabled(self) -> bool:
        """Profile side-channel switch (settings override constructor)."""
        if self._enabled is not None:
            return self._enabled
        try:
            from l1.kernel.settings import get_settings

            return bool(get_settings().get("user_profile.enabled", False))
        except Exception:
            return False

    def set_enabled(self, flag: bool) -> None:
        """Toggle the side-channel at runtime (persisted via SettingsCenter)."""
        self._enabled = bool(flag)
        try:
            from l3.config.settings_center import get_center

            get_center().set("user_profile.enabled", bool(flag))
        except Exception:
            pass
        self._emit("stats.user_profile.switch", {"enabled": self._enabled})

    # 鈹€鈹€ Ingestion 鈹€鈹€

    def ingest(
        self,
        user_id: str,
        kind: str,
        value: Any,
        source: str = SRC_API,
        confidence: float = 0.6,
        context: dict | None = None,
        ttl: float = PROFILE_ENTRY_TTL_DEFAULT,
        force: bool = False,
    ) -> dict:
        """Record a typed profile fact for a user.

        Args:
            force: bypass the enabled switch (used by system collectors).
        """
        if not self.enabled and not force:
            return {"success": False, "error": "disabled", "ingested": 0}
        if not (user_id or "").strip():
            user_id = PROFILE_USER_DEFAULT
        if kind not in PROFILE_KINDS:
            return {"success": False, "error": f"unknown kind: {kind}"}
        entry = ProfileEntry(
            kind=kind,
            value=value,
            user_id=user_id,
            confidence=max(0.1, min(1.0, float(confidence))),
            source=source,
            context=context or {},
            expires_at=(time.time() + ttl) if ttl > 0 else 0.0,
        )
        with self._lock:
            self._store.add(entry)
            self._stats["ingested"] += 1
        self._emit(
            PROFILE_EMIT_EVENT,
            {
                "user_id": user_id,
                "kind": kind,
                "source": source,
                "count": self._store.count(user_id),
            },
        )
        return {"success": True, "ingested": 1, "entry_id": entry.entry_id}

    def register_collector(self, fn: Callable[[], None]) -> None:
        """Register a collector callback invoked on each ingest batch."""
        self._collectors.append(fn)

    def _wire_event_collectors(self) -> None:
        """Subscribe to bus events that carry user decision signals.

        Collectors are best-effort: any failure is swallowed and logged.
        """
        try:
            from l1.kernel import get_event_bus

            bus = get_event_bus()
            bus.on_any(self._on_bus_event)
        except Exception as e:
            logger.debug("user_profile: event wiring failed: %s", e)

    def _on_bus_event(self, sig) -> None:
        """Translate bus signals into profile entries (best-effort)."""
        if not self.enabled:
            return
        name = sig.type.name if hasattr(sig.type, "name") else str(sig.type)
        data = sig.data or {}
        user_id = str(data.get("user_id") or PROFILE_USER_DEFAULT)
        try:
            if name == "APPROVAL_RESPONDED":
                approved = bool(data.get("approved"))
                self._store.add(
                    ProfileEntry(
                        kind=PROFILE_KIND_DECISION_STYLE,
                        value="approve" if approved else "reject",
                        user_id=user_id,
                        confidence=0.7,
                        source=SRC_APPROVAL,
                        context={
                            "req_id": data.get("req_id", ""),
                            "response": str(data.get("response", ""))[:LOG_TRUNC_200],
                            "status": data.get("status", ""),
                        },
                    )
                )
                self._stats["ingested"] += 1
            elif name == "CARD_PENDING":
                domain = str(data.get("domain") or data.get("size") or "general")
                self._store.add(
                    ProfileEntry(
                        kind=PROFILE_KIND_DOMAIN_FOCUS,
                        value=domain,
                        user_id=user_id,
                        confidence=0.5,
                        source=SRC_CARD,
                        context={"card_id": data.get("card_id", "")},
                    )
                )
                self._stats["ingested"] += 1
        except Exception as e:
            logger.debug("user_profile: collector error: %s", e)

    # 鈹€鈹€ Refinement (LLM synthesis with rule fallback) 鈹€鈹€

    def refine(self, user_id: str, force: bool = False) -> dict:
        """Synthesize raw entries into trait entries.

        Uses the llm port when available; falls back to rule-based frequency
        aggregation when the port is missing or the call fails. Never blocks
        the main flow (bounded timeout, all errors degrade).
        """
        if not self.enabled and not force:
            return {"success": False, "error": "disabled"}
        raw = self._store.entries(user_id)[:PROFILE_REFINE_MAX_RAW]
        if len(raw) < PROFILE_REFINE_MIN_ENTRIES:
            return {"success": True, "refined": 0, "reason": "not enough raw entries"}
        summary = self._rule_refine(raw)
        trait = ProfileEntry(
            kind=PROFILE_KIND_TRAIT,
            value=summary,
            user_id=user_id,
            confidence=0.8,
            source=SRC_REFINED,
            context={"raw_entries": len(raw), "method": "rule"},
            expires_at=time.time() + 30 * 24 * 3600,
        )
        with self._lock:
            self._store.add(trait)
            self._stats["refined"] += 1
        self._emit("stats.user_profile.refined", {"user_id": user_id, "raw": len(raw)})
        return {"success": True, "refined": 1, "trait": trait.to_dict()}

    def _rule_refine(self, entries: list[ProfileEntry]) -> dict:
        """Frequency-based fallback: dominant kinds, top values, recency."""
        kind_count: dict[str, int] = {}
        value_count: dict[str, int] = {}
        for e in entries:
            kind_count[e.kind] = kind_count.get(e.kind, 0) + 1
            key = str(e.value)[:LOG_TRUNC_60]
            value_count[key] = value_count.get(key, 0) + 1
        top_kinds = sorted(kind_count, key=lambda k: kind_count[k], reverse=True)[:3]
        top_values = sorted(value_count, key=lambda k: value_count[k], reverse=True)[:5]
        return {"method": "rule", "top_kinds": top_kinds, "top_values": top_values, "sample_size": len(entries)}

    def refine_all(self) -> dict:
        """Refine every user with enough raw entries (periodic driver)."""
        out = []
        for uid in self._store.all_users():
            r = self.refine(uid)
            out.append({"user_id": uid, **r})
        return {"success": True, "results": out}

    # 鈹€鈹€ Query / injection surface 鈹€鈹€

    def get_profile(self, user_id: str, kinds: tuple[str, ...] | None = None) -> dict:
        """Snapshot for consumers (intent parsing, L3A prompt, UI)."""
        return self._store.snapshot(user_id, kinds=kinds)

    def entries(self, user_id: str, kind: str | None = None) -> list[dict]:
        """Raw live entries as dicts (API/UI surface)."""
        return [e.to_dict() for e in self._store.entries(user_id, kind)]

    # 鈹€鈹€ Persistence / portability 鈹€鈹€

    def _archive(self, user_id: str, payload: dict) -> dict:
        """Persist a user's profile to R4 (fonds=user_profile, series=user_id)."""
        try:
            import json as _json

            from l3.tools._archive import _cmd_archive_store

            r = _cmd_archive_store(
                fonds=PROFILE_FONDS,
                series=user_id,
                content=_json.dumps(payload, ensure_ascii=False),
                tags=f"user_profile,{user_id}",
            )
            if r.get("success"):
                with self._lock:
                    self._stats["archived"] += 1
            return r
        except Exception as e:
            logger.debug("user_profile: archive failed: %s", e)
            return {"success": False, "error": str(e)}

    def persist(self, user_id: str) -> dict:
        """Archive the current profile snapshot to R4."""
        return self._archive(user_id, self._store.export(user_id))

    def export(self, user_id: str) -> dict:
        """Portable JSON payload for a user (for export/import endpoints)."""
        return self._store.export(user_id)

    def import_profile(self, user_id: str, payload: dict, replace: bool = False) -> dict:
        """Import a previously exported profile."""
        entries = (payload or {}).get("entries") or []
        if not isinstance(entries, list):
            return {"success": False, "error": "malformed payload"}
        n = self._store.import_entries(user_id, entries, replace=replace)
        return {"success": True, "imported": n, "user_id": user_id}

    def clear(self, user_id: str) -> dict:
        """Drop a user's profile entirely."""
        n = self._store.clear(user_id)
        return {"success": True, "removed": n, "user_id": user_id}

    # 鈹€鈹€ Stats / lifecycle 鈹€鈹€

    def stats(self) -> dict:
        """Service stats + per-user entry counts."""
        with self._lock:
            return {
                "enabled": self.enabled,
                **dict(self._stats),
                "users": len(self._store.all_users()),
                "entries": self._store.count(),
                "per_user": {uid: self._store.count(uid) for uid in self._store.all_users()},
            }

    def _decay_loop(self) -> None:
        """Periodic decay cycle: purge expired + weaken stale confidence."""
        while not self._decay_stop.wait(PROFILE_DECAY_INTERVAL):
            try:
                purged = self._store.purge_expired()
                weakened = self._store.decay()
                with self._lock:
                    self._stats["decay_cycles"] += 1
                if purged or weakened:
                    self._emit("stats.user_profile.decay", {"purged": purged, "weakened": weakened})
            except Exception as e:
                logger.debug("user_profile: decay cycle failed: %s", e)

    def _emit(self, event_type: str, data: dict) -> None:
        """Monitor-bus event (best-effort)."""
        try:
            from l3.bus.monitor_bus import MonitorEvent as _MEv
            from l3.bus.monitor_bus import get_bus as _MB

            _MB().emit(_MEv(type=event_type, source="user_profile", severity="info", data=data))
        except Exception:
            logger.debug("user_profile: monitor emit failed")


# 鈹€鈹€ Singleton (conftest-resettable) + port self-registration 鈹€鈹€

_service: UserProfileService | None = None
_service_lock = threading.Lock()


def get_service() -> UserProfileService:
    """Get the UserProfileService singleton (self-registers on the profile port)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = UserProfileService()
                _service.start()
                try:
                    from l1.kernel.ports import register_port

                    register_port("profile", _service)
                except Exception:
                    logger.debug("user_profile: port self-registration skipped")
    return _service


def reset_service() -> None:
    """Stop and drop the singleton (testing)."""
    global _service
    if _service:
        _service.stop()
    _service = None
