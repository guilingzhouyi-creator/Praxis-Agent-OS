"""Sandbox manager — SandboxProfile, SandboxResult, SandboxManager tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSandboxProfile:
    def test_profile_enum_values(self):
        from l4.sandbox.manager import SandboxProfile

        assert SandboxProfile.READ_ONLY.value
        assert SandboxProfile.SAFE_WRITE.value
        assert SandboxProfile.NETWORK.value
        assert SandboxProfile.FULL.value
        assert SandboxProfile.HOST.value


class TestSandboxResult:
    def test_result_fields(self):
        from l4.sandbox.manager import SandboxResult

        result = SandboxResult(success=True, stdout="hello", stderr="", elapsed=0.5)
        assert result.success
        assert result.stdout == "hello"

    def test_to_dict(self):
        from l4.sandbox.manager import SandboxResult

        result = SandboxResult(success=True, stdout="ok", stderr="", exit_code=0)
        d = result.to_dict()
        assert d["success"] is True


class TestSandboxManager:
    def test_create_manager(self):
        from l4.sandbox.manager import SandboxManager

        mgr = SandboxManager()
        assert mgr is not None
