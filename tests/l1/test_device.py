"""Tests for DeviceManager — register, rate-limit, health, lifecycle."""

from __future__ import annotations

from l1.kernel.device import (
    DeviceHealth,
    DeviceManager,
    DeviceType,
    register_device_type,
)


def _make_mgr() -> DeviceManager:
    return DeviceManager()


# ── register ──


def test_register_device() -> None:
    dm = _make_mgr()
    r = dm.register("test-llm", DeviceType.LLM, rate_limit=5)
    assert r["success"] is True
    assert r["device"] == "test-llm"


def test_register_duplicate() -> None:
    dm = _make_mgr()
    dm.register("dup", DeviceType.CUSTOM)
    r = dm.register("dup", DeviceType.CUSTOM)
    assert r["success"] is False
    assert "already registered" in r["error"]


def test_register_with_capabilities() -> None:
    dm = _make_mgr()
    dm.register("custom", DeviceType.CUSTOM, capabilities=["ping", "scan"])
    device = dm.get("custom")
    assert device is not None
    assert len(device.capabilities) == 2
    assert device.capabilities[0].name == "ping"


def test_register_default_capabilities() -> None:
    dm = _make_mgr()
    dm.register("my-llm", DeviceType.LLM)
    device = dm.get("my-llm")
    assert device is not None
    # LLM type should have 3 default capabilities
    assert len(device.capabilities) == 3
    assert device.capabilities[0].name == "text-generation"


# ── get / list / unregister ──


def test_get_nonexistent() -> None:
    dm = _make_mgr()
    assert dm.get("ghost") is None


def test_list_devices() -> None:
    dm = _make_mgr()
    dm.register("cpu", DeviceType.LLM)
    dm.register("db", DeviceType.DATABASE)
    all_devs = dm.list()
    assert len(all_devs) == 2


def test_list_by_type() -> None:
    dm = _make_mgr()
    dm.register("llm1", DeviceType.LLM)
    dm.register("db1", DeviceType.DATABASE)
    llms = dm.list(device_type=DeviceType.LLM)
    assert len(llms) == 1
    assert llms[0]["name"] == "llm1"


def test_unregister() -> None:
    dm = _make_mgr()
    dm.register("gone", DeviceType.CUSTOM)
    assert dm.unregister("gone") is True
    assert dm.get("gone") is None


def test_unregister_nonexistent() -> None:
    dm = _make_mgr()
    assert dm.unregister("ghost") is False


# ── record_call + health ──


def test_record_call_increments_count() -> None:
    dm = _make_mgr()
    dm.register("llm", DeviceType.LLM)
    dm.record_call("llm", success=True)
    device = dm.get("llm")
    assert device is not None
    assert device.call_count == 1
    assert device.error_count == 0


def test_record_call_failure_increments_error() -> None:
    dm = _make_mgr()
    dm.register("llm", DeviceType.LLM)
    dm.record_call("llm", success=False)
    device = dm.get("llm")
    assert device is not None
    assert device.call_count == 1
    assert device.error_count == 1


def test_record_call_unknown_device_is_noop() -> None:
    dm = _make_mgr()
    # Should not raise
    dm.record_call("unknown", success=True)


def test_set_health() -> None:
    dm = _make_mgr()
    dm.register("dev", DeviceType.CUSTOM)
    assert dm.set_health("dev", DeviceHealth.DOWN) is True
    dev = dm.get("dev")
    assert dev is not None
    assert dev.health == DeviceHealth.DOWN


def test_set_health_unknown_device() -> None:
    dm = _make_mgr()
    assert dm.set_health("ghost", DeviceHealth.DEGRADED) is False


# ── rate limiting ──


def test_check_rate_allows_within_limit() -> None:
    dm = _make_mgr()
    dm.register("r", DeviceType.CUSTOM, rate_limit=3, rate_window=10.0)
    r = dm.check_rate("r")
    assert r["allowed"] is True
    assert r["remaining"] == 3


def test_check_rate_exhausted() -> None:
    dm = _make_mgr()
    dm.register("r", DeviceType.CUSTOM, rate_limit=2, rate_window=60.0)
    dm.record_call("r")
    dm.record_call("r")
    r = dm.check_rate("r")
    assert r["allowed"] is False
    assert r["remaining"] == 0


def test_check_rate_unknown_device() -> None:
    dm = _make_mgr()
    r = dm.check_rate("unknown")
    assert r["allowed"] is False
    assert "unknown" in r["error"]


# ── stats ──


def test_stats_empty() -> None:
    dm = _make_mgr()
    s = dm.stats()
    assert s["total_devices"] == 0
    assert s["healthy"] == 0
    assert s["down"] == 0


def test_stats_with_devices() -> None:
    dm = _make_mgr()
    dm.register("llm", DeviceType.LLM)
    dm.register("db", DeviceType.DATABASE)
    s = dm.stats()
    assert s["total_devices"] == 2
    assert s["healthy"] == 2
    assert s["by_type"]["LLM"] == 1
    assert s["by_type"]["DATABASE"] == 1


# ── health check lifecycle ──


def test_check_all_health_downgrades() -> None:
    dm = _make_mgr()
    dm.register("bad", DeviceType.CUSTOM, rate_limit=100)
    # Make device fail often
    for _ in range(10):
        dm.record_call("bad", success=False)
    dm._check_all_health()
    dev = dm.get("bad")
    assert dev is not None
    assert dev.health in (DeviceHealth.DEGRADED, DeviceHealth.DOWN)


def test_check_all_health_noop_on_few_calls() -> None:
    dm = _make_mgr()
    dm.register("fine", DeviceType.CUSTOM)
    dm._check_all_health()
    dev = dm.get("fine")
    assert dev is not None
    assert dev.health == DeviceHealth.HEALTHY


def test_start_stop_health_checks() -> None:
    dm = _make_mgr()
    dm.start_health_checks(interval=0.05)
    assert dm._health_running is True
    dm.stop_health_checks()
    assert dm._health_running is False


# ── register_device_type ──


def test_register_custom_device_type() -> None:
    my_type = register_device_type("GPU")
    assert my_type.name == "GPU"


def test_register_custom_type_returns_cached() -> None:
    t1 = register_device_type("FPGA")
    t2 = register_device_type("FPGA")
    assert t1 is t2


def test_register_builtin_type_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        register_device_type("LLM")
