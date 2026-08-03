"""Boot sequence tests — constitution loading, service init, boot step registry."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestBoot:
    def test_boot_status_before_boot(self):
        from l3.boot.boot import boot_status
        r = boot_status()
        assert not r.get("success")

    def test_boot_summary_before_boot(self):
        from l3.boot.boot import boot_summary
        s = boot_summary()
        assert "not booted" in s

    def test_load_constitution(self):
        from l3.boot.boot import _load_constitution
        r = _load_constitution()
        assert r.get("success")

    def test_load_config(self):
        from l3.boot.boot import _load_config
        r = _load_config()
        assert r.get("success")

    def test_init_services(self):
        from l3.boot.boot import _init_services
        r = _init_services()
        assert r.get("success")
        svc = r.get("services", [])
        assert isinstance(svc, list), f"expected list of services, got {type(svc)}"
        assert len(svc) >= 1, f"expected at least 1 service, got: {svc}"

    def test_boot_steps_list(self):
        from l3.boot.boot import _BOOT_STEPS
        assert isinstance(_BOOT_STEPS, list)

    def test_boot_result_structure(self):
        from l3.boot.boot import _BOOT_RESULT
        # Before boot, result is None
        assert _BOOT_RESULT is None


class TestBootExecWithTimeout:
    """_exec_with_timeout ThreadPoolExecutor 回归测试"""

    def _get_fn(self):
        """Lazy import to avoid boot side-effects at module level."""
        from l3.boot.boot_registry import exec_step_with_timeout, _get_executor
        return exec_step_with_timeout, _get_executor

    def test_exec_normal(self):
        """Normal execution returns the function result."""
        exec_ft, _ = self._get_fn()
        r = exec_ft(lambda: {"success": True, "data": 42}, timeout=5.0)
        assert r.get("success")
        assert r.get("data") == 42

    def test_exec_dict_result(self):
        """Function returning a dict is passed through directly."""
        exec_ft, _ = self._get_fn()
        r = exec_ft(lambda: {"success": True, "key": "value"}, timeout=5.0)
        assert r.get("success")
        assert r.get("key") == "value"

    def test_exec_wraps_non_dict(self):
        """Function returning a non-dict is wrapped in {'result': ...}."""
        exec_ft, _ = self._get_fn()
        r = exec_ft(lambda: "hello", timeout=5.0)
        assert r.get("success")
        assert r.get("result") == "hello"

    def test_exec_raises_exception(self):
        """Function that raises should return {'success': False, 'error': ...}."""
        exec_ft, _ = self._get_fn()

        def _raise():
            raise ValueError("test error")
        r = exec_ft(_raise, timeout=5.0)
        assert not r.get("success")
        assert "test error" in r.get("error", "")

    def test_exec_timeout(self):
        """Function that exceeds timeout should return timeout error."""
        exec_ft, _ = self._get_fn()

        def _slow():
            import time
            time.sleep(10)  # longer than timeout
            return {"success": True}

        r = exec_ft(_slow, timeout=0.1)
        assert not r.get("success")
        assert "timed out" in r.get("error", "").lower()

    def test_executor_is_reused(self):
        """Multiple calls reuse the same ThreadPoolExecutor instance."""
        _, get_exec = self._get_fn()
        e1 = get_exec()
        e2 = get_exec()
        assert e1 is e2, "_get_executor should return the same singleton"

    def test_executor_max_workers_one(self):
        """Executor pool should have a bounded worker count (4)."""
        _, get_exec = self._get_fn()
        exec_ft, _ = self._get_fn()
        pool = get_exec()
        assert pool._max_workers == 4
