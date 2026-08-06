"""LSP code intelligence tool — go-to-definition, find references, hover info.

Wraps l4.lsp.lsp_manager.LspManager (server-backed with AST fallback) for
agent-accessible code analysis. All operations are read-only (Ring 1).
"""

from __future__ import annotations

from l1.kernel.params.system import TOOL_LSP_SYMBOL_LIMIT


def _get_mgr():
    from l4.lsp.lsp_manager import get_manager

    return get_manager()


def go_to_definition(args: dict, agent_id: str) -> dict:
    """Navigate to the definition of the symbol at a position."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        mgr = _get_mgr()
        result = mgr.definition(path, int(args.get("line", 1)), int(args.get("column", 1)))
        inner = result.get("result")
        return {"success": True, "found": bool(inner), "result": inner}
    except Exception as e:
        return {"success": False, "error": str(e)}


def find_references(args: dict, agent_id: str) -> dict:
    """Find all references to the symbol at a position."""
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        mgr = _get_mgr()
        result = mgr.references(path, int(args.get("line", 1)), int(args.get("column", 1)))
        refs = result.get("results", [])
        return {"success": True, "results": refs, "total": len(refs)}
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
