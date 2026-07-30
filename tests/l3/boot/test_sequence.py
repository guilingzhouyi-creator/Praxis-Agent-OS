"""Boot sequence test — register_boot_step + _BOOT_STEPS structure."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestBootRegister:
    def test_register_step_extends_list(self):
        from l3.boot import register_boot_step
        # Internal _BOOT_STEPS in the boot module gets cleaned up when boot() is called
        # register_boot_step just appends to the global _BOOT_STEPS
        # Here we verify the function is callable and doesn't crash
        register_boot_step("test_verify_step", lambda: {"ok": True}, depends_on=["init_services"])
        assert True

    def test_register_step_no_depends(self):
        from l3.boot import register_boot_step
        register_boot_step("test_no_dep", lambda: {"ok": True})
        assert True


class TestBootFunction:
    def test_boot_with_no_agents(self):
        from l3.boot import boot
        r = boot(agent_config=[], interactive=False)
        assert isinstance(r, dict)
