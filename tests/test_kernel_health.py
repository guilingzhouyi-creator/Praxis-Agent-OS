"""Health tests — kernel health checking, module probing."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestHealth:
    def test_kernel_modules_list(self):
        from kernel.health import _KERNEL_MODULES
        assert len(_KERNEL_MODULES) >= 15
        assert "kernel.constitution" in _KERNEL_MODULES

    def test_module_exists(self):
        import kernel.health
        assert hasattr(kernel.health, "_KERNEL_MODULES")

    def test_health_imports(self):
        import kernel.health
        assert hasattr(kernel.health, "_KERNEL_MODULES")
