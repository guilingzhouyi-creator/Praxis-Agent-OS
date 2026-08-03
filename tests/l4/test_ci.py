"""CI service tests."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCI:
    def test_importable(self):
        from l4.ci import get_service
        assert callable(get_service)

    def test_pipeline_uses_platform_shell_adapter(self, monkeypatch):
        import l4.ci as ci

        service = ci.CIService()
        run = ci.PipelineRun(run_id="run-1", name="test", steps=[{"action": "echo", "cmd": "echo hello"}])
        service._runs[run.run_id] = run
        received = {}

        def fake_shell_command(command):
            received["command"] = command
            return ["test-shell", "test-flag", command]

        def fake_run(args, **kwargs):
            received["args"] = args
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(ci, "shell_command", fake_shell_command)
        monkeypatch.setattr(ci.subprocess, "run", fake_run)

        service._execute(run.run_id, timeout=30.0)

        assert received["command"] == "echo hello"
        assert received["args"] == ["test-shell", "test-flag", "echo hello"]
        assert run.status == ci.PipelineStatus.PASSED
