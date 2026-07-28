"""Tests: l1.kernel.platform — cross-platform abstraction layer."""

from __future__ import annotations

import os
import tempfile

import pytest

from l1.kernel.platform import (
    IS_WINDOWS,
    IS_MAC,
    IS_LINUX,
    IS_NT,
    IS_POSIX,
    SHELL_PATH,
    SHELL_NAME,
    SHELL_PROMPT,
    DEFAULT_SHELL,
    PING_PARAM,
    PYTHON_EXE,
    IPC_USE_UNIX_SOCKET,
    IPC_TRANSPORT,
    which,
    join_url,
    get_config_dir,
    get_temp_dir,
    run_shell,
    create_interactive_shell,
    grep_cmd,
    tail_file,
    register_shutdown_handler,
)


class TestOsDetection:
    """Verify OS family boolean constants are self-consistent."""

    def test_os_bools_are_bool(self):
        assert isinstance(IS_WINDOWS, bool)
        assert isinstance(IS_MAC, bool)
        assert isinstance(IS_LINUX, bool)
        assert isinstance(IS_NT, bool)
        assert isinstance(IS_POSIX, bool)

    def test_exactly_one_os_family(self):
        """IS_WINDOWS / IS_MAC / IS_LINUX are mutually exclusive."""
        count = sum([IS_WINDOWS, IS_MAC, IS_LINUX])
        assert count == 1, f"expected exactly 1 OS family, got {count}"

    def test_nt_matches_windows(self):
        assert IS_NT == IS_WINDOWS

    def test_posix_matches_non_windows(self):
        assert IS_POSIX == (not IS_WINDOWS)


class TestShellDetection:
    """Shell constants are sane strings for the current OS."""

    def test_shell_path_is_str(self):
        assert isinstance(SHELL_PATH, str) and len(SHELL_PATH) > 0

    def test_shell_name_is_str(self):
        assert isinstance(SHELL_NAME, str) and len(SHELL_NAME) > 0

    def test_shell_prompt_is_str(self):
        assert isinstance(SHELL_PROMPT, str) and len(SHELL_PROMPT) > 0

    def test_default_shell_is_str(self):
        assert isinstance(DEFAULT_SHELL, str) and len(DEFAULT_SHELL) > 0

    def test_ping_param(self):
        assert PING_PARAM in ("-n", "-c")

    def test_python_exe_is_str(self):
        assert isinstance(PYTHON_EXE, str)
        assert "python" in PYTHON_EXE.lower()


class TestIpcDetection:
    """IPC transport constants match current platform."""

    def test_ipc_use_unix_socket(self):
        assert IPC_USE_UNIX_SOCKET is (not IS_WINDOWS)

    def test_ipc_transport(self):
        if IS_WINDOWS:
            assert IPC_TRANSPORT == "tcp"
        else:
            assert IPC_TRANSPORT == "unix"


class TestWhich:
    def test_which_found(self):
        """Python executable should always be findable."""
        exe = which(PYTHON_EXE.split(os.sep)[-1] if os.sep in PYTHON_EXE else "python")
        assert exe is not None
        assert os.path.exists(exe)

    def test_which_not_found(self):
        assert which("__this_exe_does_not_exist_9999__") is None


class TestJoinUrl:
    def test_simple(self):
        assert join_url("foo", "bar") == "foo/bar"

    def test_strip_slashes(self):
        assert join_url("/foo/", "/bar/") == "foo/bar"

    def test_single_part(self):
        assert join_url("hello") == "hello"

    def test_empty_parts(self):
        assert join_url() == ""


class TestGetConfigDir:
    def test_returns_path(self):
        p = get_config_dir()
        assert isinstance(p, os.PathLike)


class TestGetTempDir:
    def test_returns_string(self):
        d = get_temp_dir()
        assert isinstance(d, str)
        assert "nomos-praxis" in d


class TestRunShell:
    def test_echo(self):
        r = run_shell("echo hello_world")
        assert r.returncode == 0
        assert "hello_world" in r.stdout

    def test_failure(self):
        r = run_shell("exit 42")
        assert r.returncode == 42


class TestCreateInteractiveShell:
    def test_creates_popen(self):
        proc = create_interactive_shell()
        assert proc is not None
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.terminate()
        proc.wait(timeout=5)


class TestGrepCmd:
    """Verify grep_cmd builds the right command for the right flags."""

    def test_basic(self):
        cmd = grep_cmd("pattern")
        assert len(cmd) >= 3
        assert "pattern" in cmd

    def test_fixed_flag(self):
        cmd = grep_cmd("exact", fixed=True)
        # Should include -F (rg) or /x (findstr) or -F (grep fallback)
        flags = " ".join(cmd)
        if which("rg"):
            assert "-F" in flags
        elif IS_WINDOWS:
            assert "/x" in flags or "/c:" in flags

    def test_ignore_case(self):
        cmd = grep_cmd("pattern", ignore_case=True)
        flags = " ".join(cmd)
        if which("rg"):
            assert "-i" in flags
        elif IS_WINDOWS:
            assert "/i" in flags

    def test_max_count(self):
        cmd = grep_cmd("pattern", max_count=5)
        if which("rg"):
            assert "--max-count" in cmd
        elif not IS_WINDOWS:
            assert "-m" in cmd


class TestTailFile:
    def test_tail_new_file(self, tmp_path):
        f = tmp_path / "test.log"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")
        lines = tail_file(str(f), n_lines=3)
        assert lines == ["line3", "line4", "line5"]

    def test_tail_empty_file(self, tmp_path):
        f = tmp_path / "empty.log"
        f.write_text("")
        assert tail_file(str(f), n_lines=10) == []

    def test_tail_nonexistent(self):
        assert tail_file("/nonexistent/path.log") == []


class TestRegisterShutdownHandler:
    """Verify register_shutdown_handler accepts a callable."""

    def test_registeration(self):
        called = False

        def handler():
            nonlocal called
            called = True

        # Should not raise
        register_shutdown_handler(handler)
