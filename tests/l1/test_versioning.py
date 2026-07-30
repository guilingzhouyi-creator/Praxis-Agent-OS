"""Tests for versioning — schema migration infrastructure."""

from __future__ import annotations

import pytest
from l1.kernel.versioning import (
    SNAPSHOT_VERSION, CHECKPOINT_VERSION,
    register_migration, check_and_migrate, stamp,
)


def _v1_to_v2(data: dict) -> dict:
    data["migrated"] = True
    return data


# ── Simple round-trip ──


def test_stamp_adds_version() -> None:
    d = stamp({"key": "val"}, "snapshot")
    assert d["_version"] == SNAPSHOT_VERSION
    assert d["key"] == "val"


def test_stamp_unknown_kind_noop() -> None:
    d = stamp({"x": 1}, "unknown_kind")
    assert d == {"x": 1}
    assert "_version" not in d


# ── check_and_migrate ──


def test_check_same_version_noop() -> None:
    d = {"_version": SNAPSHOT_VERSION}
    r = check_and_migrate(d, "snapshot")
    assert r is d  # same object returned


def test_check_older_version_migrates() -> None:
    register_migration("checkpoint", 1, "v1→v2", _v1_to_v2)
    d = {"_version": 1}
    r = check_and_migrate(d, "checkpoint")
    assert r["_version"] == CHECKPOINT_VERSION
    assert r["migrated"] is True


def test_check_newer_version_raises() -> None:
    d = {"_version": 99}
    with pytest.raises(ValueError, match="file version 99 > current"):
        check_and_migrate(d, "snapshot")


def test_check_unknown_kind_returns_data() -> None:
    d = {"_version": 1}
    r = check_and_migrate(d, "no_such_kind")
    assert r is d


def test_migration_error_propagates() -> None:
    def bad_migrate(data: dict) -> dict:
        raise RuntimeError("boom")

    register_migration("snapshot", 1, "bad", bad_migrate)  # snapshot version is 3, so v1→v2 will be triggered
    d = {"_version": 1}
    with pytest.raises(RuntimeError, match="boom"):
        check_and_migrate(d, "snapshot")


# ── Multi-step migration ──


def test_multi_step_migration() -> None:
    from l1.kernel.versioning import TODO_TABLE_VERSION
    calls = []

    def step1(d: dict) -> dict:
        calls.append("step1")
        d["v"] = 1
        return d

    def step2(d: dict) -> dict:
        calls.append("step2")
        d["v"] = 2
        return d

    register_migration("todo_table", 1, "s1", step1)
    register_migration("todo_table", 2, "s2", step2)

    d = {"_version": 1}
    # todo_table version is 1 by default, so we need to make sure it's at least 2
    from l1.kernel.versioning import TODO_TABLE_VERSION
    # bump to 3 for 2-step migration
    import l1.kernel.versioning as vmod
    vmod.TODO_TABLE_VERSION = 3
    # re-run stamp so entry sees the new version
    from l1.kernel.versioning import _REGISTRY
    _REGISTRY["todo_table"]["version"] = 3

    r = check_and_migrate(d, "todo_table")
    assert r["_version"] == 3
    assert r["v"] == 2
    assert calls == ["step1", "step2"]


# ── register_migration ──


def test_register_migration_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        register_migration("ghost", 1, "label", lambda d: d)


def test_version_constants_are_positive() -> None:
    from l1.kernel.versioning import (
        SNAPSHOT_VERSION, CHECKPOINT_VERSION, SETTINGS_VERSION,
        LOG_VERSION,
    )
    for v in (SNAPSHOT_VERSION, CHECKPOINT_VERSION, SETTINGS_VERSION, LOG_VERSION):
        assert v >= 1
