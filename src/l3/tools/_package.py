"""Package management tool — pip, npm, apt, cargo operations.

Wraps l3.services.package_manager.PackageManager.
All operations return structured dicts for tool pipeline consumption.
"""

from __future__ import annotations


def _get_mgr():
    from l3.services.package_manager import get_service

    return get_service()


def pip_install(args: dict, agent_id: str) -> dict:
    """Install a Python package via pip."""
    pkg = args.get("package", "")
    if not pkg:
        return {"success": False, "error": "package is required"}
    ver = args.get("version", "")
    return _get_mgr().pip_install(pkg, version=ver)


def pip_list(args: dict, agent_id: str) -> dict:
    """List installed Python packages."""
    return _get_mgr().pip_list()


def pip_uninstall(args: dict, agent_id: str) -> dict:
    """Uninstall a Python package."""
    pkg = args.get("package", "")
    if not pkg:
        return {"success": False, "error": "package is required"}
    return _get_mgr().pip_uninstall(pkg)


def npm_install(args: dict, agent_id: str) -> dict:
    """Install an npm package."""
    pkg = args.get("package", "")
    if not pkg:
        return {"success": False, "error": "package is required"}
    return _get_mgr().npm_install(pkg, global_install=args.get("global", False))


def npm_list(args: dict, agent_id: str) -> dict:
    """List installed npm packages."""
    return _get_mgr().npm_list(depth=args.get("depth", 0))


def apt_install(args: dict, agent_id: str) -> dict:
    """Install a system package via apt."""
    pkg = args.get("package", "")
    if not pkg:
        return {"success": False, "error": "package is required"}
    return _get_mgr().apt_install(pkg)


def apt_search(args: dict, agent_id: str) -> dict:
    """Search apt packages by pattern."""
    pattern = args.get("pattern", "")
    if not pattern:
        return {"success": False, "error": "pattern is required"}
    return _get_mgr().apt_search(pattern)


def install(args: dict, agent_id: str) -> dict:
    """Auto-detect manager and install a package."""
    pkg = args.get("package", "")
    if not pkg:
        return {"success": False, "error": "package is required"}
    mgr = args.get("manager", "pip")
    return _get_mgr().install(pkg, manager=mgr)
