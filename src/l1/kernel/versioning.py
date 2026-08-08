"""Schema versioning & migration infrastructure for all persistence backends.

Every persisted file/DB carries a version marker. Migration functions
transform data from old versions to new. Zero migration = boot failure.

Protocol:
  _VERSION   — current schema version (integer)
  _migrate_v1_to_v2(data) -> data
  _mIGRATION_MAP = {1: ("1.0", _migrate_v1_to_v2)}
  check_version(data, kind)  — validates version, runs migrations
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ── Current schema versions ──

SNAPSHOT_VERSION: int = 3
CHECKPOINT_VERSION: int = 2
SETTINGS_VERSION: int = 2
WORKSPACE_VERSION: int = 2
LOG_VERSION: int = 2
CARD_REGISTRY_VERSION: int = 1
TODO_TABLE_VERSION: int = 1
TRANSACTION_AREA_VERSION: int = 1
DIALOGUE_SESSION_VERSION: int = 1
EXECUTION_RESULT_VERSION: int = 1
CAPABILITY_GATE_VERSION: int = 1

# ── Migration entries: target_version -> (label, migrator_fn) ──
# Migrators are registered here. Each takes data dict, returns data dict.

_SNAPSHOT_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_CHECKPOINT_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_CARD_REGISTRY_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_TODO_TABLE_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_TRANSACTION_AREA_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_CAPABILITY_GATE_MIGRATIONS: dict[int, tuple[str, Callable]] = {}

_REGISTRY: dict[str, dict] = {
    "snapshot": {"version": SNAPSHOT_VERSION, "migrations": _SNAPSHOT_MIGRATIONS},
    "checkpoint": {"version": CHECKPOINT_VERSION, "migrations": _CHECKPOINT_MIGRATIONS},
    "card_registry": {"version": CARD_REGISTRY_VERSION, "migrations": _CARD_REGISTRY_MIGRATIONS},
    "todo_table": {"version": TODO_TABLE_VERSION, "migrations": _TODO_TABLE_MIGRATIONS},
    "transaction_area": {"version": TRANSACTION_AREA_VERSION, "migrations": _TRANSACTION_AREA_MIGRATIONS},
    "capability_gate": {"version": CAPABILITY_GATE_VERSION, "migrations": _CAPABILITY_GATE_MIGRATIONS},
}


# Fill missing migration steps with no-op identity migrations
def _noop(d):
    return d


for _entry in _REGISTRY.values():
    for _v in range(1, _entry["version"]):
        _entry["migrations"].setdefault(_v, ("identity", _noop))


def register_migration(kind: str, from_version: int, label: str, fn: Callable) -> None:
    """Register a migration step for *kind* from *from_version*; raises for unknown kinds."""
    entry = _REGISTRY.get(kind)
    if entry is None:
        raise ValueError(f"unknown kind: {kind}")
    entry["migrations"][from_version] = (label, fn)


def check_and_migrate(data: dict, kind: str) -> dict:
    """Check and apply pending persistence migrations."""
    entry = _REGISTRY.get(kind)
    if entry is None:
        logger.warning("versioning: unknown kind %s, skipping", kind)
        return data

    current_version = entry["version"]
    file_version = data.get("_version", 0)

    if file_version == current_version:
        return data

    if file_version > current_version:
        logger.error("versioning: %s file version %d > current %d — too new!", kind, file_version, current_version)
        raise ValueError(f"{kind} file version {file_version} > current {current_version}")

    migrations = entry["migrations"]
    migrated = dict(data)
    for v in range(file_version, current_version):
        mig = migrations.get(v)
        if mig is None:
            logger.error("versioning: no migration path %s v%d -> v%d", kind, v, v + 1)
            raise ValueError(f"no migration {kind} v{v} -> v{v + 1}")
        label, fn = mig
        logger.info("versioning: migrating %s v%d -> v%d (%s)", kind, v, v + 1, label)
        try:
            migrated = fn(migrated)
        except Exception as e:
            logger.error("versioning: migration %s v%d->v%d failed: %s", kind, v, v + 1, e)
            raise
        migrated["_version"] = v + 1

    return migrated


def stamp(data: dict, kind: str) -> dict:
    """Stamp a version marker into persistence."""
    entry = _REGISTRY.get(kind)
    if entry is None:
        return data
    data["_version"] = entry["version"]
    return data
