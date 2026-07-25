"""Boot sequence tests — constitution loading, service init, boot step registry."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestBoot:
    def test_boot_status_before_boot(self):
        from services.boot import boot_status
        r = boot_status()
        assert not r.get("success")

    def test_boot_summary_before_boot(self):
        from services.boot import boot_summary
        s = boot_summary()
        assert "not booted" in s

    def test_load_constitution(self):
        from services.boot import _load_constitution
        r = _load_constitution()
        assert r.get("success")

    def test_load_config(self):
        from services.boot import _load_config
        r = _load_config()
        assert r.get("success")

    def test_init_services(self):
        from services.boot import _init_services
        r = _init_services()
        assert r.get("success")
        assert "constitution" in r.get("services", [])

    def test_boot_steps_list(self):
        from services.boot import _BOOT_STEPS
        assert isinstance(_BOOT_STEPS, list)

    def test_boot_result_structure(self):
        from services.boot import _BOOT_RESULT
        # Before boot, result is None
        assert _BOOT_RESULT is None
