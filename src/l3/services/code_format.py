"""Code auto-format engine — detect/run formatters and hook onto the write path.

L3 service powering the ``format_file`` / ``format_project`` tools and the
automatic post-write formatting hook. Formatters run as subprocesses (stdin →
stdout) via ``l1.kernel.platform.run_args``; the formatted content is staged
through the resource buffer so per-hunk attribution is preserved. Constants
live in ``params/tool.py`` — no hardcoded formatter names or timeouts here.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from l1.kernel.params.system import LOG_TRUNC_200
from l1.kernel.params.tool import (
    FORMAT_DETECTORS,
    FORMAT_EXTENSION_TOOL,
    FORMAT_IGNORE_DIRS,
    FORMAT_MAX_FILES,
    TOOL_FORMAT_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Content-write tools whose successful results trigger the auto-format hook.
_FORMAT_TRIGGER_TOOLS: frozenset[str] = frozenset(
    {
        "create_file",
        "file_patch",
        "file_append",
    }
)


def detect_formatter(path: str) -> str:
    """Return the preferred formatter name for a file path, or "".

    Uses the ``FORMAT_EXTENSION_TOOL`` map keyed on the lowercased
    extension; unknown extensions yield an empty string.
    """
    ext = os.path.splitext(path)[1].lower()
    return FORMAT_EXTENSION_TOOL.get(ext, "")


def _resolve_detector(tool: str = "") -> tuple[str, ...] | None:
    """Resolve the first available formatter command tuple.

    When ``tool`` is non-empty it must name a candidate in
    ``FORMAT_DETECTORS``; otherwise the first detector whose executable
    exists on PATH is chosen. Returns None when nothing is available.
    """
    for det in FORMAT_DETECTORS:
        if tool and det[0] != tool:
            continue
        if shutil.which(det[0]):
            return det
    return None


def _read_text(path: str) -> str:
    """Read file content as UTF-8 text (best-effort)."""
    return Path(path).read_text(encoding="utf-8")


def format_file(path: str, tool: str = "") -> dict:
    """Format a single file with the configured formatter.

    Reads the current content, pipes it through the formatter (stdin →
    stdout), and stages the formatted result via the resource buffer
    (op="format") so the normal flush path persists it with attribution.
    Returns ``{"success", "tool", "changed", "path"}`` — never raises.
    """
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        return {"success": False, "error": "file not found", "path": full}
    preferred = tool or detect_formatter(full)
    if not preferred:
        return {
            "success": False,
            "error": "formatter unavailable for extension",
            "path": full,
        }
    det = _resolve_detector(preferred)
    if det is None:
        return {
            "success": False,
            "error": f"formatter unavailable for {preferred or 'extension'}",
            "path": full,
        }
    try:
        content = _read_text(full)
    except (OSError, UnicodeDecodeError) as e:
        return {"success": False, "error": f"read failed: {e}", "path": full}

    from l1.kernel.platform import run_args

    try:
        r = run_args(list(det) + ["-"], timeout=TOOL_FORMAT_TIMEOUT, input=content)
    except Exception as e:
        logger.debug("code_format: %s failed: %s", det[0], e)
        return {"success": False, "error": f"format failed: {e}", "path": full}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"{det[0]} exited {r.returncode}"
        return {"success": False, "error": err[:LOG_TRUNC_200], "path": full}

    formatted = (r.stdout or "").rstrip("\n") + "\n" if r.stdout else content
    changed = formatted != content
    if changed:
        try:
            from l3.resource_buffer.manager import get_manager

            get_manager().stage(full, formatted, op="format")
        except Exception as e:
            logger.debug("code_format: buffer stage failed: %s", e)
    return {"success": True, "tool": det[0], "changed": changed, "path": full}


def format_project(root: str = "", tool: str = "") -> dict:
    """Format all formattable source files under a directory (batch).

    Walks ``root`` (default cwd), skipping ``FORMAT_IGNORE_DIRS``, capped at
    ``FORMAT_MAX_FILES``. Aggregates per-file results. Never raises.
    """
    base = os.path.abspath(root or os.getcwd())
    if not os.path.isdir(base):
        return {"success": False, "error": "directory not found", "root": base}
    targets: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in FORMAT_IGNORE_DIRS]
        for name in filenames:
            if detect_formatter(name):
                targets.append(os.path.join(dirpath, name))
            if len(targets) >= FORMAT_MAX_FILES:
                break
        if len(targets) >= FORMAT_MAX_FILES:
            break
    results = [format_file(p, tool) for p in targets]
    changed = sum(1 for r in results if r.get("changed"))
    return {
        "success": True,
        "root": base,
        "total": len(targets),
        "changed": changed,
        "results": results,
    }


def auto_format_hook(tool_name: str, agent_id: str, args: dict, result: dict) -> dict:
    """Post-execute hook: auto-format after content-write tools succeed.

    Triggered only for ``_FORMAT_TRIGGER_TOOLS`` with a successful result
    and a formattable path; gated by the ``format_auto`` tool config. Never
    raises and never replaces the original result — on success it appends
    ``"formatted": {"tool", "changed"}`` to the result dict.
    """
    if tool_name not in _FORMAT_TRIGGER_TOOLS:
        return result
    if not result.get("success"):
        return result
    from l1.kernel.discovery import get_tool_config

    if not bool(get_tool_config("format_auto", True)):
        return result
    path = (args or {}).get("path", "")
    if not path or not detect_formatter(path):
        return result
    try:
        r = format_file(path)
    except Exception as e:
        logger.debug("auto_format hook failed: %s", e)
        return result
    if r.get("success"):
        result["formatted"] = {"tool": r.get("tool"), "changed": r.get("changed", False)}
    return result
