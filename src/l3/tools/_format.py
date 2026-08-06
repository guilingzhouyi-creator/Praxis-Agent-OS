"""Code format tool handlers — format_file / format_project (Ring 2).

Thin wrappers over ``l3.services.code_format`` for agent consumption.
Registered in ``config/tools.yaml`` layer_2 (write layer, danger=1).
"""

from __future__ import annotations

from l3.services.code_format import format_file as _format_file
from l3.services.code_format import format_project as _format_project


def format_file(args: dict, agent_id: str) -> dict:
    """Format a source file with the configured formatter.

    Args:
        args: dict with ``path`` (required) and optional ``tool`` override.
        agent_id: calling agent (recorded by the pipeline for attribution).

    Returns:
        The engine result dict (``success`` / ``tool`` / ``changed`` / ``path``).
    """
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    return _format_file(path, tool=args.get("tool", ""))


def format_project(args: dict, agent_id: str) -> dict:
    """Format all formattable source files under a directory.

    Args:
        args: dict with optional ``path`` (default ".") and ``tool`` override.
        agent_id: calling agent (recorded by the pipeline for attribution).

    Returns:
        The engine result dict (``success`` / ``total`` / ``changed`` / ``results``).
    """
    return _format_project(root=args.get("path", "."), tool=args.get("tool", ""))
