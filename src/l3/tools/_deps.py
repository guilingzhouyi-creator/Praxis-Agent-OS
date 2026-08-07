"""Dependency tool handlers."""

try:
    from importlib.metadata import distribution as _get_dist
    from importlib.metadata import version as _get_version

    HAS_PKG = True
except ImportError:
    HAS_PKG = False


def check_version(args: dict, agent_id: str) -> dict:
    """Check whether a package is installed and return its version; returns dict."""
    package = args.get("package", "")
    if not package:
        return {"success": False, "error": "package is required"}
    if not HAS_PKG:
        return {"success": False, "error": "package metadata not available"}
    try:
        _get_dist(package)
        return {"success": True, "package": package, "version": _get_version(package)}
    except Exception:
        return {"success": True, "package": package, "installed": False}
