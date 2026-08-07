"""ContextEpoch + ContextSource + ContextRegistry.

Each ContextSource has a stable key, codec, loader, and renderers.
The ContextRegistry collects all sources; ContextEpoch manages the
immutable baseline and change detection.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import TOKEN_CHARS_PER_TOKEN
from l3.error_bus import capture

from . import params as _p

logger = logging.getLogger(__name__)


@dataclass
class ContextSource:
    """ContextSource — context source record (key, loader, render_baseline, render_update, render_removal)."""

    key: str
    loader: Callable[[], Any]
    render_baseline: Callable[[Any], str]
    render_update: Callable[[Any, Any], str | None] | None = None
    render_removal: Callable[[], str] | None = None
    enabled: bool = True


@dataclass
class MidConversationMessage:
    """MidConversationMessage — mid conversation message record (key, text, created_at)."""

    key: str
    text: str
    created_at: float = field(default_factory=time.time)


class ContextRegistry:
    """Registry of context sources with loaders and renderers."""

    def __init__(self):
        self._sources: dict[str, ContextSource] = {}

    def register(self, source: ContextSource) -> None:
        """Register a context source under its key."""
        self._sources[source.key] = source

    def get(self, key: str) -> ContextSource | None:
        """Return the source registered under key, or None when absent."""
        return self._sources.get(key)

    def list_sources(self) -> list[str]:
        """Return the list of registered source keys."""
        return list(self._sources.keys())

    def load_all(self) -> dict[str, Any]:
        """Load values from all enabled sources, skipping failed loaders, and return a key-value dict."""
        values = {}
        for key, src in self._sources.items():
            if not src.enabled:
                continue
            try:
                values[key] = src.loader()
            except Exception as e:
                capture(
                    "l3a context: source loader failed",
                    error_code="E_L3A_CONTEXT",
                    component="l3a",
                    context={"source_key": key},
                )
                logger.debug("l3a context: %s loader failed: %s", key, e)
        return values

    def render_baseline(self, values: dict[str, Any]) -> str:
        """Render the full baseline text from all enabled sources."""
        parts = []
        for key, src in self._sources.items():
            if not src.enabled:
                continue
            val = values.get(key)
            if val is not None:
                parts.append(src.render_baseline(val))
            elif src.render_removal:
                parts.append(src.render_removal())
        return "\n\n".join(parts)

    def diff(self, snapshot: dict[str, Any], values: dict[str, Any]) -> list[MidConversationMessage]:
        """Compare a snapshot with current values and return messages for changed sources."""
        changes = []
        for key, src in self._sources.items():
            if not src.enabled:
                continue
            old = snapshot.get(key)
            new = values.get(key)
            if old == new:
                continue
            if new is None and src.render_removal:
                text = src.render_removal() or ""
            elif src.render_update and old is not None and new is not None:
                text = src.render_update(old, new) or ""
            elif src.render_update and old is None and new is not None:
                text = src.render_baseline(new) or ""
            else:
                continue
            if text:
                changes.append(MidConversationMessage(key=key, text=text))
        return changes


class ContextEpoch:
    """Epoch-scoped context snapshot with turn tracking."""

    def __init__(self, eid: str, baseline: str, snapshot: dict, created_at: float, turn_count: int = 0):
        self.id = eid
        self.baseline = baseline
        self.snapshot = snapshot
        self.created_at = created_at
        self.turn_count = turn_count
        self._persisted = False

    @classmethod
    def create(cls, registry: ContextRegistry) -> ContextEpoch:
        """Create and persist a new epoch with a fresh baseline and snapshot; return it."""
        values = registry.load_all()
        baseline = registry.render_baseline(values)
        snap = {k: v for k, v in values.items() if v is not None}
        inst = cls(
            eid=uuid.uuid4().hex[: _p.SID_LENGTH],
            baseline=baseline,
            snapshot=snap,
            created_at=time.time(),
        )
        inst.persist()
        logger.debug("l3a epoch: created %s (%d chars baseline)", inst.id, len(baseline))
        return inst

    @classmethod
    def restore(cls) -> ContextEpoch | None:
        """Restore the persisted epoch snapshot, or None when unavailable."""
        try:
            from l3.agent.agent_persist import load_snapshot as _ls

            snap = _ls(_p.AGENT_ID)
            if snap and _p.EPOCH_SNAPSHOT_KEY in snap:
                data = snap[_p.EPOCH_SNAPSHOT_KEY]
                return cls(
                    eid=data["id"],
                    baseline=data["baseline"],
                    snapshot=data["snapshot"],
                    created_at=data["created_at"],
                    turn_count=data.get("turn_count", 0),
                )
        except Exception:
            capture("l3a epoch: restore failed", error_code="E_L3A_CONTEXT", component="l3a")
            logger.debug("l3a epoch: restore failed")
        return None

    def persist(self) -> None:
        """Persist this epoch's snapshot through the agent persist layer."""
        try:
            from l3.agent.agent_persist import save_snapshot as _ss

            _ss(
                _p.AGENT_ID,
                {
                    _p.EPOCH_SNAPSHOT_KEY: {
                        "id": self.id,
                        "baseline": self.baseline,
                        "snapshot": self.snapshot,
                        "created_at": self.created_at,
                        "turn_count": self.turn_count,
                    }
                },
            )
            self._persisted = True
        except Exception:
            capture("l3a epoch: persist failed", error_code="E_L3A_CONTEXT", component="l3a")
            logger.debug("l3a epoch: persist failed")

    def sync(self, registry: ContextRegistry) -> list[MidConversationMessage]:
        """Load current context, diff with snapshot, update snapshot, increment turn."""
        values = registry.load_all()
        changes = registry.diff(self.snapshot, values)
        self.snapshot = {}
        for k, v in values.items():
            if v is not None:
                self.snapshot[k] = v
        self.turn_count += 1
        self.persist()
        return changes

    def estimate_tokens(self) -> int:
        """Estimate the baseline token count from characters per token."""
        return len(self.baseline) // TOKEN_CHARS_PER_TOKEN
