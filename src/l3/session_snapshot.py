"""Session snapshot — versioned, serializable conversation state for resume/replay.

AtomCode-inspired design: a snapshot carries messages, counters, and a version
field so future schema changes can migrate old snapshots rather than break them.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict

SNAPSHOT_VERSION = 1

logger = logging.getLogger(__name__)


@dataclass
class SessionSnapshot:
    """Immutable snapshot of a conversation session. Can be resumed."""
    version: int = SNAPSHOT_VERSION
    session_id: str = ""
    agent_id: str = ""
    messages: list[dict] = field(default_factory=list)
    turn_counter: int = 0
    request_counter: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> SessionSnapshot:
        data = json.loads(raw)
        version = data.get("version", 0)
        if version > SNAPSHOT_VERSION:
            raise ValueError(f"snapshot version {version} > current {SNAPSHOT_VERSION}")
        if version < SNAPSHOT_VERSION:
            data = cls._migrate(data, version)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @staticmethod
    def _migrate(data: dict, from_version: int) -> dict:
        """Migrate from old version to current. Currently a no-op (v1 only)."""
        logger.info("snapshot migration v%d -> v%d", from_version, SNAPSHOT_VERSION)
        data["version"] = SNAPSHOT_VERSION
        return data


# ── Truncation continuation ──

from l1.kernel.prompts import get_prompt as _gp
TRUNCATION_RESUME_NUDGE = _gp("session_snapshot.truncation_resume_nudge", "")


# ── Pre-send compression guard ──

def should_compress(used_tokens: int, ctx_window: int,
                    threshold: float = 0.85) -> bool:
    """Check if the current context is near the window limit.

    AtomCode-style: when used_tokens / ctx_window >= threshold, trigger
    compression before the next LLM send to avoid silent truncation.
    """
    if ctx_window <= 0:
        return False
    return (used_tokens / ctx_window) >= threshold
