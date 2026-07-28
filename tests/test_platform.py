"""Tests for l1.kernel.platform — cross-platform abstraction layer."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest

from l1.kernel.platform import (
    IS_WINDOWS, IS_MAC, IS_LINUX, IS_NT, IS_POSIX,
    SHELL_PATH, SHELL_NAME, PING_PARAM, PYTHON_EXE,
    IPC_USE_UNIX_SOCKET, IPC_TRANSPORT,
    which, join_url, get_config_dir, get_temp_dir,
    run_shell, create_interactive_shell,
    set_nonblocking, safe_chmod,
    grep_cmd, tail_file,
    register_shutdown_handler,
    create_ipc_server, remove_ipc_socket,
)


class TestOsDetection:
    """OS family constants are mutually exclusive and self-consistent."""

    def test_os_detection_mutual_exclusive(self):
        """At most one of WINDOWS/MAC/LINUX is True."""
        count = sum([IS_WINDOWS, IS_MAC, IS_LINUX])
        assert count == 1, f"Expected exactly 1 OS, got {count}"

    def test_nt_posix_consistency(self):
        """IS_NT and IS_POSIX are mutually exclusive."""
        assert IS_NT != IS_POSIX

    def test_is_windows_matches_platform(self):
        """IS_WINDOWS consistent with sys.platform / platform.system()."""
        import platform
        assert IS_WINDOWS == (platform.system() == "Windows")


class TestConstants:
    """Module-level constants are well-formed."""

    def test_shell_path_not_empty(self):
        assert isinstance(SHELL_PATH, str) and len(SHELL_PATH) > 0

    def test_shell_name_matches_path(self):
        if "powershell" in SHELL_PATH.lower():
            assert "powershell" in SHELL_NAME.lower()
        elif "bash" in SHELL_PATH or not IS_WINDOWS:
            assert SHELL_NAME == "bash"

    @pytest.mark.skipif(IS_WINDOWS, reason="ping -c is POSIX-only")
    def test_ping_param_posix(self):
        assert PING_PARAM == "-c"

    @pytest.mark.skipif(not IS_WINDOWS, reason="ping -n is Windows-only")
    def test_ping_param_windows(self):
        assert PING_PARAM == "-n"

    def test_python_exe_not_empty(self):
        assert isinstance(PYTHON_EXE, str) and len(PYTHON_EXE) > 0

    def test_ipc_transport_consistent(self):
        if IS_WINDOWS:
            assert IPC_TRANSPORT == "tcp"
            assert IPC_USE_UNIX_SOCKET is False
        else:
            assert IPC_TRANSPORT == "unix"
            assert IPC_USE_UNIX_SOCKET is True


class TestWhich:
    """Cross-platform executable lookup."""

    def test_which_finds_python(self):
        assert which("python") is not None

    def test_which_returns_none_for_missing(self):
        assert which("_nonexistent_cmd_xyz_") is None

    def test_which_returns_string(self):
        result = which("python")
        assert isinstance(result, str)


class TestJoinUrl:
    """URL path joining."""

    def test_join_simple(self):
        assert join_url("a", "b") == "a/b"

    def test_join_strips_slashes(self):
        assert join_url("/a/", "/b/") == "a/b"

    def test_join_empty(self):
        assert join_url() == ""

    def test_join_multi(self):
        assert join_url("a", "b", "c", "d") == "a/b/c/d"


class TestGetConfigDir:
    """Config directory resolution."""

    def test_get_config_dir_returns_path(self):
        result = get_config_dir()
        assert isinstance(result, str) or hasattr(result, "resolve")
        assert "nomos-praxis" in str(result) or "praxis" in str(result)


class TestGetTempDir:
    """Temp directory path."""

    def test_get_temp_dir(self):
        result = get_temp_dir()
        assert isinstance(result, str)
        assert "nomos-praxis" in result


class TestRunShell:
    """Shell command execution."""

    def test_run_shell_echo(self):
        r = run_shell("echo hello", timeout=5)
        assert r.returncode == 0
        assert "hello" in r.stdout

    def test_run_shell_fail(self):
        r = run_shell("exit 42", timeout=5)
        assert r.returncode == 42

    def test_run_shell_timeout(self):
        with pytest.raises(subprocess.TimeoutExpired):
            run_shell("sleep 10", timeout=0.1)


class TestGrepCmd:
    """Cross-platform grep command builder."""

    def test_grep_cmd_uses_rg_when_available(self):
        if which("rg"):
            cmd = grep_cmd("test", fixed=True)
            assert "rg" in cmd
            assert "-F" in cmd

    def test_grep_cmd_regex_mode(self):
        cmd = grep_cmd("test.*")
        assert cmd is not None

    def test_grep_cmd_with_ignore_case(self):
        cmd = grep_cmd("test", ignore_case=True)
        if which("rg"):
            assert "-i" in cmd

    def test_grep_cmd_with_max_count(self):
        cmd = grep_cmd("test", max_count=5)
        if which("rg"):
            assert "--max-count" in cmd

    def test_grep_cmd_with_glob(self):
        cmd = grep_cmd("test", glob_pattern="*.py")
        if which("rg"):
            assert "--glob" in cmd

    def test_grep_cmd_with_file_type(self):
        cmd = grep_cmd("test", file_type="py")
        if which("rg"):
            assert "--type" in cmd


class TestTailFile:
    """File tailing — cross-platform."""

    def test_tail_file_small_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            tmp = f.name
        try:
            lines = tail_file(tmp, n_lines=2)
            assert len(lines) == 2
            assert lines[-1] == "line3"
        finally:
            os.unlink(tmp)

    def test_tail_file_missing(self):
        lines = tail_file("/tmp/_nonexistent_file_xyz.txt")
        assert lines == []

    def test_tail_file_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            tmp = f.name
        try:
            lines = tail_file(tmp)
            assert lines == []
        finally:
            os.unlink(tmp)

    def test_tail_file_more_than_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("only\n")
            tmp = f.name
        try:
            lines = tail_file(tmp, n_lines=100)
            assert len(lines) == 1
        finally:
            os.unlink(tmp)


@pytest.mark.skipif(IS_WINDOWS, reason="set_nonblocking is noop on Windows")
class TestSetNonblocking:
    """Non-blocking FD (POSIX only)."""

    def test_set_nonblocking_on_pipe(self):
        r, w = os.pipe()
        try:
            set_nonblocking(r)
            # Should not raise
        finally:
            os.close(r)
            os.close(w)


@pytest.mark.skipif(IS_WINDOWS, reason="safe_chmod is noop on Windows")
class TestSafeChmod:
    """File permission change (POSIX only)."""

    def test_safe_chmod_readonly(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp = f.name
        try:
            safe_chmod(tmp, 0o444)
            assert os.stat(tmp).st_mode & 0o777 == 0o444
        finally:
            os.chmod(tmp, 0o644)
            os.unlink(tmp)


class TestRegisterShutdownHandler:
    """Shutdown handler registration."""

    def test_register_handler(self):
        calls = []
        def handler(): calls.append(1)
        register_shutdown_handler(handler)
        # atexit will call it on exit; we just verify no exception
        assert len(calls) == 0


@pytest.mark.skipif(not IS_WINDOWS, reason="create_interactive_shell path differs per OS")
class TestCreateInteractiveShellWindows:
    def test_create_shell(self):
        proc = create_interactive_shell()
        assert proc is not None
        proc.terminate()


@pytest.mark.skipif(IS_WINDOWS, reason="create_interactive_shell path differs per OS")
class TestCreateInteractiveShellPosix:
    def test_create_shell(self):
        proc = create_interactive_shell()
        assert proc is not None
        proc.terminate()
