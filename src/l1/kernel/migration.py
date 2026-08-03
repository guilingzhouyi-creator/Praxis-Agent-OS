"""Migration — schema version tracking and pending migration executor.

Zero upper-layer dependencies (kernel-level).
Migrations are registered at module import time and executed during install().
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

SCHEMA_VERSION: str = "20260730.1"
"""Current schema version. Bump when archive DB or other persistent schema changes."""

_MIGRATIONS: list[tuple[str, Callable[[], dict]]] = []


def register_migration(version: str, fn: Callable[[], dict]) -> None:
    """Register a migration function for a target schema version.

    Migrations are sorted by version string and applied in order
    when the current schema_version is older than the target.
    """
    _MIGRATIONS.append((version, fn))
    _MIGRATIONS.sort(key=lambda x: x[0])


def run_pending(current: str, target: str = SCHEMA_VERSION) -> dict:
    """Run all migrations from current to target (exclusive of current).

    Returns:
        {"applied": [version, ...], "errors": [{version, error}, ...]}
    """
    applied: list[str] = []
    errors: list[dict] = []
    for version, fn in _MIGRATIONS:
        if version <= current:
            continue
        if version > target:
            break
        try:
            fn()
            applied.append(version)
            logger.info("migration %s applied", version)
        except Exception as e:
            errors.append({"version": version, "error": str(e)})
            logger.warning("migration %s failed: %s", version, e)
            break
    return {"applied": applied, "errors": errors}
