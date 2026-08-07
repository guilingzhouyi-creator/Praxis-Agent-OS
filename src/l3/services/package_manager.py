"""Package Manager — OS-level package management for apt/pip/npm/cargo.

Provides unified interface for package operations across package managers.
Integrates with kernel settings for proxy configuration.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Any
from dataclasses import dataclass

from l1.kernel.params.system import LOG_TRUNC_500, LOG_TRUNC_2000
from l1.kernel.params.tool import (
    TOOL_APT_INSTALL_TIMEOUT,
    TOOL_APT_SEARCH_TIMEOUT,
    TOOL_CARGO_INSTALL_TIMEOUT,
    TOOL_NPM_INSTALL_TIMEOUT,
    TOOL_PACKAGE_LIST_TIMEOUT,
    TOOL_PACKAGE_MANAGER_TIMEOUT,
    TOOL_PIP_INSTALL_TIMEOUT,
)
from l3._base import BaseService

logger = logging.getLogger(__name__)


@dataclass
class Package:
    """Package — package record (name, version, manager, description, installed)."""
    name: str
    version: str = ""
    manager: str = ""
    description: str = ""
    installed: bool = False


class PackageManager(BaseService):
    """OS-level package manager — unified interface for apt/pip/npm/cargo."""

    def __init__(self):
        super().__init__("package_manager")
        self._lock = threading.RLock()
        self._total_operations = 0
        self._failed_operations = 0

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        return {"success": True}

    def _run(self, cmd: list[str], timeout: int = TOOL_PACKAGE_MANAGER_TIMEOUT) -> dict:
        """Run a package manager command."""
        from l1.kernel.platform import run_args
        try:
            r = run_args(cmd, timeout=timeout)
            with self._lock:
                self._total_operations += 1
                if r.returncode != 0:
                    self._failed_operations += 1
            return {
                "success": r.returncode == 0,
                "stdout": r.stdout[:LOG_TRUNC_2000],
                "stderr": r.stderr[:LOG_TRUNC_500],
                "exit_code": r.returncode,
            }
        except FileNotFoundError:
            return {"success": False, "error": f"command not found: {cmd[0]}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"command timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Pip ──

    def pip_install(self, package: str, version: str = "") -> dict:
        """Install a Python package with pip (optionally pinned to a version); returns the run result."""
        cmd = ["pip", "install"] + ([f"{package}=={version}"] if version else [package])
        return self._run(cmd, TOOL_PIP_INSTALL_TIMEOUT)

    def pip_list(self) -> dict:
        """List installed pip packages; returns a dict with the parsed packages."""
        r = self._run(["pip", "list", "--format=columns"], TOOL_PACKAGE_LIST_TIMEOUT)
        if r["success"]:
            lines = r["stdout"].splitlines()
            packages = []
            for line in lines[2:]:  # Skip header
                parts = line.split()
                if len(parts) >= 2:
                    packages.append({"name": parts[0], "version": parts[1]})
            return {"success": True, "packages": packages, "count": len(packages)}
        return r

    def pip_uninstall(self, package: str) -> dict:
        """Uninstall a Python package with pip; returns the run result."""
        return self._run(["pip", "uninstall", "-y", package], TOOL_PACKAGE_LIST_TIMEOUT)

    # ── Npm ──

    def npm_install(self, package: str, global_install: bool = False) -> dict:
        """Install an npm package (optionally globally); returns the run result."""
        cmd = ["npm", "install"]
        if global_install:
            cmd.append("-g")
        cmd.append(package)
        return self._run(cmd, TOOL_NPM_INSTALL_TIMEOUT)

    def npm_list(self, depth: int = 0) -> dict:
        """List npm packages up to the given dependency depth; returns the run result."""
        cmd = ["npm", "list", f"--depth={depth}"]
        return self._run(cmd, TOOL_PACKAGE_LIST_TIMEOUT)

    # ── Apt ──

    def apt_install(self, package: str) -> dict:
        """Install an apt package; returns the run result."""
        return self._run(["apt-get", "install", "-y", package], TOOL_APT_INSTALL_TIMEOUT)

    def apt_update(self) -> dict:
        """Update the apt package index; returns the run result."""
        return self._run(["apt-get", "update"], TOOL_APT_INSTALL_TIMEOUT)

    def apt_search(self, pattern: str) -> dict:
        """Search apt packages matching the pattern; returns the run result."""
        return self._run(["apt-cache", "search", pattern], TOOL_APT_SEARCH_TIMEOUT)

    # ── Cargo ──

    def cargo_install(self, package: str) -> dict:
        """Install a crate with cargo; returns the run result."""
        return self._run(["cargo", "install", package], TOOL_CARGO_INSTALL_TIMEOUT)

    # ── Unified ──

    def install(self, package: str, manager: str = "pip",
                version: str = "") -> dict:
        """Install a package using the specified package manager."""
        handlers = {
            "pip": lambda: self.pip_install(package, version),
            "npm": lambda: self.npm_install(package),
            "apt": lambda: self.apt_install(package),
            "cargo": lambda: self.cargo_install(package),
        }
        handler = handlers.get(manager)
        if not handler:
            return {"success": False, "error": f"unsupported manager: {manager}"}
        return handler()

    def list_packages(self, manager: str = "pip") -> dict:
        """List installed packages from the specified manager."""
        handlers: dict[str, Any] = {
            "pip": self.pip_list,
            "npm": self.npm_list,
        }
        handler = handlers.get(manager)
        if not handler:
            return {"success": False, "error": f"unsupported manager: {manager}"}
        return handler()

    def uninstall(self, package: str, manager: str = "pip") -> dict:
        """Uninstall a package using the specified package manager."""
        handlers = {
            "pip": lambda: self.pip_uninstall(package),
        }
        handler = handlers.get(manager)
        if not handler:
            return {"success": False, "error": f"unsupported manager: {manager}"}
        return handler()

    def stats(self) -> dict:
        """Return operation counters for the package manager."""
        with self._lock:
            return {
                "total_operations": self._total_operations,
                "failed_operations": self._failed_operations,
                "managers": ["pip", "npm", "apt", "cargo"],
            }


_service: PackageManager | None = None


def get_service() -> PackageManager:
    """Return the shared PackageManager singleton, creating it on first use."""
    global _service
    if _service is None:
        _service = PackageManager()
    return _service


def reset_service() -> None:
    """Stop and drop the PackageManager singleton (for testing / hot-reload)."""
    global _service
    if _service:
        _service.stop()
    _service = None
