"""Package Manager — OS-level package management for apt/pip/npm/cargo.

Provides unified interface for package operations across package managers.
Integrates with kernel settings for proxy configuration.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from services._base import BaseService

logger = logging.getLogger(__name__)


@dataclass
class Package:
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

    def _run(self, cmd: list[str], timeout: int = 60) -> dict:
        """Run a package manager command."""
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            with self._lock:
                self._total_operations += 1
                if r.returncode != 0:
                    self._failed_operations += 1
            return {
                "success": r.returncode == 0,
                "stdout": r.stdout[:2000],
                "stderr": r.stderr[:500],
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
        cmd = ["pip", "install"] + ([f"{package}=={version}"] if version else [package])
        return self._run(cmd, 120)

    def pip_list(self) -> dict:
        r = self._run(["pip", "list", "--format=columns"], 30)
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
        return self._run(["pip", "uninstall", "-y", package], 30)

    # ── Npm ──

    def npm_install(self, package: str, global_install: bool = False) -> dict:
        cmd = ["npm", "install"]
        if global_install:
            cmd.append("-g")
        cmd.append(package)
        return self._run(cmd, 120)

    def npm_list(self, depth: int = 0) -> dict:
        cmd = ["npm", "list", f"--depth={depth}"]
        return self._run(cmd, 30)

    # ── Apt ──

    def apt_install(self, package: str) -> dict:
        return self._run(["apt-get", "install", "-y", package], 120)

    def apt_update(self) -> dict:
        return self._run(["apt-get", "update"], 120)

    def apt_search(self, pattern: str) -> dict:
        return self._run(["apt-cache", "search", pattern], 30)

    # ── Cargo ──

    def cargo_install(self, package: str) -> dict:
        return self._run(["cargo", "install", package], 300)

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
        handlers = {
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
        with self._lock:
            return {
                "total_operations": self._total_operations,
                "failed_operations": self._failed_operations,
                "managers": ["pip", "npm", "apt", "cargo"],
            }


_service: PackageManager | None = None


def get_service() -> PackageManager:
    global _service
    if _service is None:
        _service = PackageManager()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None