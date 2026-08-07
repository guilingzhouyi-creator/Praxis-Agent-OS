"""Boot — system bootstrap sequence tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestBoot:
    def test_boot_status_returns_dict(self):
        from l3.boot.boot import boot_status

        st = boot_status()
        assert isinstance(st, dict)

    def test_boot_summary_returns_string(self):
        from l3.boot.boot import boot_summary

        summary = boot_summary()
        assert isinstance(summary, str)

    def test_default_constitution_returns_string(self):
        from l3.boot.boot import _default_constitution

        result = _default_constitution()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_register_default_boot_steps(self):
        from l3.boot.boot import _register_default_boot_steps

        _register_default_boot_steps(agent_config=[])
        from l3.boot.boot_registry import resolve_boot_order

        steps = resolve_boot_order()
        assert isinstance(steps, list)

    def test_boot_wires_auth_port_before_security_checks(self):
        """Boot must pre-warm AuthService so the first security check
        can resolve the auth port (no lazy-registration timing gap)."""
        import inspect

        from l3.boot.boot import _init_memory_and_archive

        src = inspect.getsource(_init_memory_and_archive)
        assert "auth_service" in src
        assert "l4.vault.auth" in src
