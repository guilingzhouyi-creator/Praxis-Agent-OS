"""Tests for registry_base — RegisterableSpec, Registry ABC, MapRegistry."""

from __future__ import annotations

from typing import Callable

import pytest

from l1.kernel.registry_base import (
    RegisterableSpec,
    Registry,
    MapRegistry,
)


def test_registerable_spec_defaults() -> None:
    """RegisterableSpec sets sensible defaults."""
    spec = RegisterableSpec(name="test-tool")
    assert spec.name == "test-tool"
    assert spec.handler is None
    assert spec.description == ""
    assert spec.category == "other"
    assert spec.tags == []
    assert spec.metadata == {}
    assert spec.version == "1.0.0"


def test_registerable_spec_with_values() -> None:
    """RegisterableSpec accepts all fields."""
    def handler(args: dict) -> dict:
        return {"ok": True}

    spec = RegisterableSpec(
        name="my-cmd",
        handler=handler,
        description="A test command",
        category="utils",
        tags=["cli", "test"],
        metadata={"author": "test"},
        version="2.0.0",
    )
    assert spec.name == "my-cmd"
    assert spec.handler is handler
    assert spec.description == "A test command"
    assert spec.category == "utils"
    assert spec.tags == ["cli", "test"]
    assert spec.metadata == {"author": "test"}
    assert spec.version == "2.0.0"


def test_registerable_spec_to_dict() -> None:
    """to_dict returns a clean serializable dict."""
    spec = RegisterableSpec(
        name="x", description="desc", category="sys", tags=["a"], version="0.1",
    )
    d = spec.to_dict()
    assert d["name"] == "x"
    assert d["description"] == "desc"
    assert d["category"] == "sys"
    assert d["tags"] == ["a"]
    assert d["version"] == "0.1"
    # metadata and handler should NOT be in to_dict
    assert "metadata" not in d
    assert "handler" not in d


def test_registerable_spec_to_dict_truncates_long_description() -> None:
    """to_dict truncates description beyond LOG_TRUNC_200."""
    long_desc = "x" * 500
    spec = RegisterableSpec(name="x", description=long_desc)
    d = spec.to_dict()
    assert len(d["description"]) <= 200


# ── MapRegistry ──


def test_register_get() -> None:
    """register stores a spec; get retrieves it."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    spec = RegisterableSpec(name="tool-a")
    assert reg.register(spec) is True
    assert reg.get("tool-a") is spec


def test_register_duplicate_rejected() -> None:
    """register returns False when name already exists (no overwrite)."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="dup"))
    assert reg.register(RegisterableSpec(name="dup")) is False


def test_register_duplicate_allowed() -> None:
    """allow_overwrite=True lets register replace an existing spec."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry(allow_overwrite=True)
    s1 = RegisterableSpec(name="x", version="1.0")
    s2 = RegisterableSpec(name="x", version="2.0")
    assert reg.register(s1) is True
    assert reg.register(s2) is True  # allowed
    assert reg.get("x").version == "2.0"


def test_unregister_removes() -> None:
    """unregister removes a spec and returns True."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="bye"))
    assert reg.unregister("bye") is True
    assert reg.get("bye") is None


def test_unregister_unknown_returns_false() -> None:
    """unregister returns False for names that don't exist."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    assert reg.unregister("nobody") is False


def test_list_returns_all() -> None:
    """list() returns all registered specs."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="a", category="cat1"))
    reg.register(RegisterableSpec(name="b", category="cat2"))
    reg.register(RegisterableSpec(name="c", category="cat1"))
    all_specs = reg.list()
    assert len(all_specs) == 3
    assert {s.name for s in all_specs} == {"a", "b", "c"}


def test_list_filters_by_category() -> None:
    """list(category=...) returns only specs in that category."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="a", category="cat1"))
    reg.register(RegisterableSpec(name="b", category="cat2"))
    cat1 = reg.list(category="cat1")
    assert len(cat1) == 1
    assert cat1[0].name == "a"


def test_all_names() -> None:
    """all_names returns the list of registered names."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="x"))
    reg.register(RegisterableSpec(name="y"))
    assert sorted(reg.all_names()) == ["x", "y"]


def test_stats() -> None:
    """stats returns total + register/unregister counts + categories."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="a", category="cat1"))
    reg.register(RegisterableSpec(name="b", category="cat2"))
    reg.register(RegisterableSpec(name="c", category="cat1"))
    reg.unregister("c")
    s = reg.stats()
    assert s["total"] == 2
    assert s["registers"] == 3
    assert s["unregisters"] == 1
    assert s["categories"] == {"cat1": 1, "cat2": 1}


def test_clear_empties_registry() -> None:
    """clear removes all items and returns the count removed."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    reg.register(RegisterableSpec(name="a"))
    reg.register(RegisterableSpec(name="b"))
    n = reg.clear()
    assert n == 2
    assert reg.list() == []


def test_get_returns_none_for_missing() -> None:
    """get returns None when name is not registered."""
    reg: MapRegistry[RegisterableSpec] = MapRegistry()
    assert reg.get("absent") is None


# ── callbacks ──


def test_on_register_callback() -> None:
    """on_register callback is invoked after successful registration."""
    calls: list[tuple[str, RegisterableSpec]] = []
    reg: MapRegistry[RegisterableSpec] = MapRegistry()

    def cb(name: str, spec: RegisterableSpec) -> None:
        calls.append((name, spec))

    reg.set_on_register(cb)
    spec = RegisterableSpec(name="cb-test")
    reg.register(spec)
    assert len(calls) == 1
    assert calls[0][0] == "cb-test"
    assert calls[0][1] is spec


def test_on_unregister_callback() -> None:
    """on_unregister callback is invoked after successful unregistration."""
    call_names: list[str] = []
    reg: MapRegistry[RegisterableSpec] = MapRegistry()

    def cb(name: str) -> None:
        call_names.append(name)

    reg.set_on_unregister(cb)
    reg.register(RegisterableSpec(name="gone"))
    reg.unregister("gone")
    assert call_names == ["gone"]


def test_on_register_not_called_on_duplicate() -> None:
    """on_register should NOT fire when registration is rejected."""
    call_count = 0
    reg: MapRegistry[RegisterableSpec] = MapRegistry()

    def cb(name: str, spec: RegisterableSpec) -> None:
        nonlocal call_count
        call_count += 1

    reg.set_on_register(cb)
    reg.register(RegisterableSpec(name="dup"))
    reg.register(RegisterableSpec(name="dup"))  # rejected
    assert call_count == 1  # only the first call


# ── Registry ABC ──


def test_registry_is_abstract() -> None:
    """Registry ABC cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Registry()  # type: ignore[abstract]


def test_mapregistry_is_concrete() -> None:
    """MapRegistry can be instantiated and used."""
    reg = MapRegistry[RegisterableSpec]()
    assert isinstance(reg, Registry)
