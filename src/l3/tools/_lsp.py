"""LSP code intelligence tool — go-to-definition, find references, hover info.

Wraps l4.lsp.lsp.LocalAnalyzer (AST position queries) and
l4.lsp.lsp_manager.LspManager (hover, diagnostics). All operations are
read-only (Ring 1).
"""

from __future__ import annotations

import os
import re

from l1.kernel.params.system import TOOL_LSP_SYMBOL_LIMIT

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _get_mgr():
    from l4.lsp.lsp_manager import get_manager

    return get_manager()


def _symbol_at_position(path: str, line: int, column: int) -> str:
    """Extract the identifier token at a 1-based (line, column) position.

    Returns an empty string when the position is out of range or does not
    land on an identifier — callers treat that as "no symbol".
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    if line < 1 or line > len(lines):
        return ""
    if column < 1:
        column = 1
    for m in _IDENTIFIER_RE.finditer(lines[line - 1]):
        start, end = m.start() + 1, m.end()
        if start <= column <= end:
            return m.group()
    return ""


def _rel_to_lsp_root(path: str, lsp) -> str:
    """Convert a tool path to a path relative to the analyzer root."""
    try:
        return os.path.relpath(os.path.abspath(path), lsp.root)
    except ValueError:
        return os.path.abspath(path)


def go_to_definition(args: dict, agent_id: str) -> dict:
    """Navigate to the definition of the symbol at a position."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        name = _symbol_at_position(path, int(args.get("line", 1)), int(args.get("column", 1)))
        if not name:
            return {"success": True, "found": False, "result": None}
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        sym = lsp.go_to_definition(name, _rel_to_lsp_root(path, lsp))
        if sym is None:
            return {"success": True, "found": False, "result": None}
        return {
            "success": True,
            "found": True,
            "result": {
                "name": sym.name,
                "kind": sym.kind,
                "file": sym.file,
                "line": sym.line,
                "column": sym.column,
                "parent": sym.parent,
                "docstring": sym.docstring,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def find_references(args: dict, agent_id: str) -> dict:
    """Find all references to the symbol at a position."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        name = _symbol_at_position(path, int(args.get("line", 1)), int(args.get("column", 1)))
        if not name:
            return {"success": True, "results": [], "total": 0}
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        result = lsp.find_references(name, _rel_to_lsp_root(path, lsp))
        return {"success": True, "results": result, "total": len(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def hover_info(args: dict, agent_id: str) -> dict:
    """Get hover documentation for a symbol."""
    path = args.get("path", "")
    line = args.get("line", 1)
    column = args.get("column", 1)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        mgr = _get_mgr()
        result = mgr.hover(path, line=int(line), column=int(column))
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def diagnostics(args: dict, agent_id: str) -> dict:
    """Get diagnostics (errors/warnings) for a file."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        mgr = _get_mgr()
        result = mgr.get_diagnostics(path)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def workspace_symbols(args: dict, agent_id: str) -> dict:
    """Search for symbols across the workspace."""
    query = args.get("query", "")
    if not query:
        return {"success": False, "error": "query is required"}
    try:
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        result = lsp.symbol_search(query, limit=TOOL_LSP_SYMBOL_LIMIT)
        return {"success": True, "results": result, "total": len(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}
