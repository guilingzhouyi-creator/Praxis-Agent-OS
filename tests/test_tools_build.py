"""Tests for tools._build — build_project() and test_project().

Since both functions call subprocess.run(), we mock that layer and focus on:
- Error handling (exceptions, non-zero return codes)
- Path fallback (default ``.``)
- TOOL_BUILD_TIMEOUT integration
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── helpers ──


def _mock_run(returncode: int = 0, stdout: str = "", side_effect=None):
    """Return a `subprocess.run` mock that returns *returncode* / *stdout*."""
    m = Mock(returncode=returncode, stdout=stdout, stderr="")
    return Mock(return_value=m) if side_effect is None else Mock(side_effect=side_effect)


# ── TOOL_BUILD_TIMEOUT integration ──


class TestBuildTimeoutConstant:
    """TOOL_BUILD_TIMEOUT is read from kernel.params and passed to subprocess."""

    def test_constant_value(self):
        from kernel.params import TOOL_BUILD_TIMEOUT
        assert TOOL_BUILD_TIMEOUT == 300

    def test_timeout_passed_to_subprocess(self):
        """Verify TOOL_BUILD_TIMEOUT is used as timeout= parameter."""
        import subprocess
        from tools._build import build_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            build_project({"path": "."}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        assert "timeout" in _call[1]
        from kernel.params import TOOL_BUILD_TIMEOUT
        assert _call[1]["timeout"] == TOOL_BUILD_TIMEOUT

    def test_timeout_passed_on_test(self):
        import subprocess
        from tools._build import test_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            test_project({"path": "."}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        from kernel.params import TOOL_BUILD_TIMEOUT
        assert _call[1]["timeout"] == TOOL_BUILD_TIMEOUT


# ── Path fallback ──


class TestPathFallback:
    """path defaults to ``.`` when not supplied."""

    def test_build_default_path(self):
        import subprocess
        from tools._build import build_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            build_project({}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        # cwd should default to "."
        assert _call[1].get("cwd") == "."

    def test_build_custom_path(self):
        import subprocess
        from tools._build import build_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            build_project({"path": "/tmp/my-project"}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        assert _call[1].get("cwd") == "/tmp/my-project"

    def test_test_default_path(self):
        import subprocess
        from tools._build import test_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            test_project({}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        assert _call[1].get("cwd") == "."

    def test_test_custom_path(self):
        import subprocess
        from tools._build import test_project

        mock = _mock_run()
        with patch.object(subprocess, "run", mock):
            test_project({"path": "/tmp/my-project"}, "agent-a")
        _call = mock.call_args
        assert _call is not None
        assert _call[1].get("cwd") == "/tmp/my-project"


# ── Successful execution ──


class TestBuildSuccess:
    """build_project returns success on first working command."""

    def test_python_build_success(self):
        import subprocess
        from tools._build import build_project

        mock = _mock_run(returncode=0, stdout="Successfully built")
        with patch.object(subprocess, "run", mock):
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "python -m build" in result["command"]
        assert "Successfully built" in result["stdout"]

    def test_cargo_build_fallback(self):
        """If python build fails, cargo build is tried next."""
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                Mock(returncode=0, stdout="Compiling ...", stderr=""),
            ]
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "cargo build" in result["command"]

    def test_npm_build_fallback(self):
        """If python and cargo both fail, npm run build is tried."""
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                FileNotFoundError("no cargo"),
                Mock(returncode=0, stdout="Build completed"),
            ]
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "npm run build" in result["command"]


class TestTestSuccess:
    """test_project returns success on first working command."""

    def test_python_test_success(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.return_value = Mock(returncode=0, stdout="3 passed", stderr="")
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "python -m pytest" in result["command"]
        assert "3 passed" in result["stdout"]

    def test_cargo_test_fallback(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                Mock(returncode=0, stdout="test result: ok", stderr=""),
            ]
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "cargo test" in result["command"]

    def test_npm_test_fallback(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                FileNotFoundError("no cargo"),
                Mock(returncode=0, stdout="Tests: 5", stderr=""),
            ]
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "npm test" in result["command"]


# ── Error handling ──


class TestBuildErrorHandling:
    """Errors during subprocess calls are caught and fall through."""

    def test_all_commands_fail(self):
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                FileNotFoundError("no cargo"),
                FileNotFoundError("no npm"),
            ]
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is False
        assert "no supported build system found" in result["error"]

    def test_nonzero_returncode_fallthrough(self):
        """A command returning non-zero is treated the same as an exception."""
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.return_value = Mock(returncode=1, stdout="error", stderr="build failed")
            result = build_project({"path": "."}, "agent-a")
        # returncode != 0 → continue to next command → all fail
        assert result["success"] is False
        assert "no supported build system found" in result["error"]

    def test_timeout_exception_caught(self):
        """subprocess.TimeoutExpired is caught like any Exception."""
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                subprocess.TimeoutExpired(cmd="python -m build", timeout=300),
                Mock(returncode=0, stdout="cargo succeeded"),
            ]
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "cargo build" in result["command"]

    def test_permission_error_caught(self):
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                PermissionError("permission denied"),
                Mock(returncode=0, stdout="cargo ok", stderr=""),
            ]
            result = build_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "cargo build" in result["command"]


class TestTestErrorHandling:
    """Errors during test_project subprocess calls."""

    def test_all_commands_fail(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                FileNotFoundError("no python"),
                FileNotFoundError("no cargo"),
                FileNotFoundError("no npm"),
            ]
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is False
        assert "no supported test framework found" in result["error"]

    def test_nonzero_returncode_fallthrough(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.return_value = Mock(returncode=1, stdout="FAILED", stderr="tests failed")
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is False
        assert "no supported test framework found" in result["error"]

    def test_timeout_exception_caught(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run") as run_mock:
            run_mock.side_effect = [
                subprocess.TimeoutExpired(cmd="python -m pytest", timeout=300),
                Mock(returncode=0, stdout="cargo test ok", stderr=""),
            ]
            result = test_project({"path": "."}, "agent-a")
        assert result["success"] is True
        assert "cargo test" in result["command"]


# ── Agent ID passthrough (interface contract) ──


class TestInterfaceContract:
    """Both functions accept (args, agent_id) and return a dict."""

    def test_build_returns_dict(self):
        import subprocess
        from tools._build import build_project

        with patch.object(subprocess, "run", _mock_run()):
            result = build_project({"path": "."}, "some-agent")
        assert isinstance(result, dict)

    def test_test_returns_dict(self):
        import subprocess
        from tools._build import test_project

        with patch.object(subprocess, "run", _mock_run()):
            result = test_project({"path": "."}, "some-agent")
        assert isinstance(result, dict)

    def test_stdout_truncated(self):
        """stdout is truncated to 2000 characters."""
        import subprocess
        from tools._build import build_project

        long_out = "x" * 5000
        with patch.object(subprocess, "run") as run_mock:
            run_mock.return_value = Mock(returncode=0, stdout=long_out, stderr="")
            result = build_project({"path": "."}, "agent-a")
        assert len(result["stdout"]) == 2000
