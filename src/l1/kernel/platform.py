"""Cross-platform abstraction layer — single source of truth for OS detection.

Consolidates all os.name, sys.platform, platform.system() checks
into one module so the rest of the codebase uses named constants instead
of scattered string comparisons.

Usage:
  from l1.kernel.platform import IS_WINDOWS, SHELL_PATH, grep_cmd, run_shell, get_config_dir
"""

from __future__ import annotations

import os as _os
import platform as _platform
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile
from pathlib import Path as _Path
from typing import Any

from .params.api import SUBPROCESS_SHORT_TIMEOUT


# ── OS family detection ──

IS_WINDOWS: bool = _platform.system() == "Windows"
IS_MAC: bool = _platform.system() == "Darwin"
IS_LINUX: bool = _platform.system() == "Linux"
IS_NT: bool = _os.name == "nt"
IS_POSIX: bool = _os.name == "posix"


# ── Shell detection ──

if IS_WINDOWS:
    SHELL_PATH: str = _os.environ.get("COMSPEC", "cmd.exe")
    SHELL_NAME: str = "powershell.exe" if "powershell" in SHELL_PATH.lower() else "cmd.exe"
    SHELL_PROMPT: str = "PS > " if "powershell" in SHELL_PATH.lower() else "C:\\> "
    DEFAULT_SHELL: str = "powershell.exe"
else:
    SHELL_PATH: str = _os.environ.get("SHELL", "/bin/bash")
    SHELL_NAME: str = "bash"
    SHELL_PROMPT: str = "$ "
    DEFAULT_SHELL: str = "/bin/bash"


# ── Command adapters ──

PING_PARAM: str = "-n" if IS_WINDOWS else "-c"
PYTHON_EXE: str = _sys.executable


# ── Path helpers ──

def which(name: str) -> str | None:
    path = _os.environ.get("PATH", "")
    for p in path.split(";" if IS_WINDOWS else ":"):
        candidate = _os.path.join(p, name)
        if IS_WINDOWS:
            for ext in (".exe", ".bat", ".cmd", ".ps1"):
                if _os.path.isfile(candidate + ext):
                    return candidate + ext
        elif _os.path.isfile(candidate):
            return candidate
    return None


def join_url(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts)


def get_config_dir() -> _Path:
    """Return config directory — delegates to PraxisPaths for deploy-mode awareness."""
    try:
        from .paths import get_paths
        return _Path(get_paths().config_dir)
    except Exception:
        if IS_WINDOWS:
            return _Path(_os.environ.get("APPDATA", _Path.home() / ".config")) / "nomos-praxis"
        return _Path.home() / ".config" / "nomos-praxis"


def get_temp_dir() -> str:
    """Return a stable temp directory for Praxis runtime files."""
    return _os.path.join(_tempfile.gettempdir(), "nomos-praxis")


# ── Shell command wrappers ──

def run_shell(cmd: str, timeout: float = 30.0, **kwargs: Any) -> _subprocess.CompletedProcess:
    """Run a command through the system shell, cross-platform."""
    if IS_WINDOWS:
        args = [DEFAULT_SHELL, "/c", cmd] if "powershell" in DEFAULT_SHELL.lower() else ["cmd.exe", "/c", cmd]
    else:
        args = ["bash", "-c", cmd]
    kwargs.setdefault("timeout", timeout)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return _subprocess.run(args, **kwargs)


def create_interactive_shell(cwd: str = "") -> _subprocess.Popen:
    """Create an interactive shell subprocess, cross-platform."""
    if IS_WINDOWS:
        cmd = ["cmd.exe"]
    else:
        cmd = [_os.environ.get("SHELL", "/bin/bash"), "-i"]
    kwargs: dict = {}
    if cwd:
        kwargs["cwd"] = cwd
    return _subprocess.Popen(cmd, stdin=_subprocess.PIPE, stdout=_subprocess.PIPE,
                              stderr=_subprocess.STDOUT, **kwargs)


def set_nonblocking(fd: Any) -> None:
    """Set a file descriptor to non-blocking mode. Noop on Windows."""
    if not IS_WINDOWS:
        import fcntl as _fcntl
        _fcntl.fcntl(fd, _fcntl.F_SETFL, _fcntl.fcntl(fd, _fcntl.F_GETFL) | _os.O_NONBLOCK)


# ── File system helpers ──

def safe_chmod(path: str, mode: int) -> None:
    """Change file permissions. Noop on Windows (chmod is not supported)."""
    if not IS_WINDOWS:
        _os.chmod(path, mode)


# ── Search / grep ──

def grep_cmd(pattern: str, path: str = ".", *,
             fixed: bool = False, ignore_case: bool = False,
             max_count: int = 0, glob_pattern: str = "",
             file_type: str = "") -> list[str]:
    """Return the OS-appropriate command list for grep.

    Uses ripgrep (rg) on all platforms when available,
    falls back to grep (Unix) or findstr (Windows).

    Returns a list suitable for subprocess.run().
    """
    if which("rg"):
        cmd = ["rg", "-n", "--no-heading"]
        if fixed:
            cmd.append("-F")
        if ignore_case:
            cmd.append("-i")
        if max_count:
            cmd.extend(["--max-count", str(max_count)])
        if glob_pattern:
            cmd.extend(["--glob", glob_pattern])
        if file_type:
            cmd.extend(["--type", file_type])
        cmd.extend([pattern, path])
        return cmd

    if IS_WINDOWS:
        cmd = ["findstr", "/n", "/s"]
        if ignore_case:
            cmd.append("/i")
        if fixed:
            cmd.append("/x")
            # Escape regex metacharacters so findstr treats the pattern as a literal string
            safe = pattern.replace("\\", "\\\\").replace(".", "\\.").replace("*", "\\*")\
                          .replace("^", "\\^").replace("$", "\\$").replace("|", "\\|")\
                          .replace("(", "\\(").replace(")", "\\)").replace("+", "\\+")\
                          .replace("?", "\\?").replace("[", "\\[").replace("]", "\\]")
            cmd.append(safe)
        else:
            cmd.append(pattern)
        if glob_pattern:
            cmd.append(f"{path}\\{glob_pattern}")
        elif path:
            cmd.append(f"{path}\\*")
        return cmd

    cmd = ["grep", "-rn"]
    if ignore_case:
        cmd.append("-i")
    if fixed:
        cmd.append("-F")
    if max_count:
        cmd.extend(["-m", str(max_count)])
    cmd.extend([pattern, path])
    return cmd


def tail_file(path: str, n_lines: int = 10) -> list[str]:
    """Return the last n_lines of a file, cross-platform."""
    if not IS_WINDOWS and which("tail"):
        try:
            r = _subprocess.run(["tail", "-n", str(n_lines), path],
                                capture_output=True, text=True, timeout=SUBPROCESS_SHORT_TIMEOUT)
            if r.returncode == 0:
                return r.stdout.splitlines()
        except Exception:
            pass
    lines = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    return [l.rstrip("\n\r") for l in lines[-n_lines:]]


# ── Signal / shutdown ──

def register_shutdown_handler(handler: Any) -> None:
    """Register a shutdown handler via atexit + signal, cross-platform."""
    import atexit as _atexit
    _atexit.register(handler)
    if not IS_WINDOWS:
        try:
            import signal as _signal
            _signal.signal(_signal.SIGTERM, handler)
            _signal.signal(_signal.SIGINT, handler)
        except (ValueError, AttributeError):
            pass
