"""Language Server Protocol — code intelligence for agents.

Agents can call LSP tools instead of relying on grep/read:
  - lsp_symbol_search: find classes, functions, variables
  - lsp_go_to_definition: where a symbol is defined
  - lsp_find_references: all usages of a symbol
  - lsp_type_check: run type checking
  - lsp_hover_info: type/doc info for a symbol
  - lsp_diagnostics: get file errors/warnings

Backend: AST-based for Python (no external server needed).
Pyright integration: attempted if `pyright` is on PATH.
Multi-language: basic file-type detection for JS/TS/Go/Rust.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass

from l1.kernel.params.api import LSP_DIAG_TIMEOUT, SUBPROCESS_SHORT_TIMEOUT
from l1.kernel.params.system import LOG_TRUNC_50, LOG_TRUNC_100, LOG_TRUNC_300, LSP_PYTHON_EXT

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    name: str
    kind: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    parent: str = ""
    docstring: str = ""


class LocalAnalyzer:
    """Code intelligence — AST-based with optional external backend."""

    def __init__(self, root: str = "."):
        self.root = os.path.abspath(root)
        self._lock = threading.Lock()
        self._pyright_ok = self._check_pyright()

    def _check_pyright(self) -> bool:
        try:
            r = subprocess.run(["pyright", "--version"], capture_output=True, text=True, timeout=SUBPROCESS_SHORT_TIMEOUT)
            return r.returncode == 0
        except Exception:
            return False

    def _parse(self, path: str) -> ast.AST | None:
        full = os.path.join(self.root, path) if not os.path.isabs(path) else path
        if not os.path.exists(full) or not full.endswith(LSP_PYTHON_EXT):
            return None
        try:
            with open(full, encoding="utf-8") as f:
                return ast.parse(f.read())
        except SyntaxError:
            return None

    def _walk_python(self, file_path: str = "") -> list[tuple[str, ast.AST]]:
        """Walk Python files under root, return (rel_path, tree) pairs."""
        results = []
        search_dir = os.path.join(self.root, file_path) if file_path else self.root
        for root_dir, dirs, files in os.walk(search_dir):
            for f in files:
                if not f.endswith(LSP_PYTHON_EXT):
                    continue
                fp = os.path.join(root_dir, f)
                rel = os.path.relpath(fp, self.root)
                tree = self._parse(fp)
                if tree:
                    results.append((rel, tree))
        return results

    def symbol_search(self, query: str, file_path: str = "") -> list[Symbol]:
        results: list[Symbol] = []
        for rel, tree in self._walk_python(file_path):
            for node in ast.walk(tree):
                sym = self._node_to_symbol(node, rel)
                if sym and (query == "*" or query.lower() in sym.name.lower() or
                            re.search(query, sym.name, re.I)):
                    results.append(sym)
        return results[:LOG_TRUNC_100]

    def go_to_definition(self, name: str, file_path: str = "") -> Symbol | None:
        for rel, tree in self._walk_python(file_path):
            for node in ast.walk(tree):
                sym = self._node_to_symbol(node, rel)
                if sym and sym.name == name:
                    return sym
        return None

    def find_references(self, name: str, file_path: str = "") -> list[dict]:
        refs: list[dict] = []
        for rel, tree in self._walk_python(file_path):
            src = ""
            full = os.path.join(self.root, rel)
            try:
                with open(full, encoding="utf-8") as f:
                    src = f.read()
            except Exception:
                continue
            for i, line in enumerate(src.splitlines(), 1):
                if name in line:
                    refs.append({"file": rel, "line": i,
                                  "column": line.index(name) + 1,
                                  "content": line.strip()[:LOG_TRUNC_100]})
        return refs[:LOG_TRUNC_50]

    def hover_info(self, name: str, file_path: str = "") -> dict:
        sym = self.go_to_definition(name, file_path)
        if not sym:
            return {"symbol": name, "found": False}
        return {"symbol": sym.name, "kind": sym.kind, "file": sym.file,
                "line": sym.line, "docstring": sym.docstring[:LOG_TRUNC_300] if sym.docstring else "",
                "parent": sym.parent, "found": True}

    def workspace_symbols(self, query: str = "") -> list[Symbol]:
        return self.symbol_search(query or "*")

    def diagnostics(self, file_path: str = "") -> list[dict]:
        """File diagnostics: pyright first, then AST fallback."""
        issues: list[dict] = []

        # Pyright backend
        if self._pyright:
            full = os.path.join(self.root, file_path) if not os.path.isabs(file_path) else file_path
            try:
                r = subprocess.run(["pyright", full, "--outputjson"],
                                   capture_output=True, text=True, timeout=LSP_DIAG_TIMEOUT)
                if r.returncode in (0, 1) and r.stdout:
                    data = json.loads(r.stdout)
                    for d in data.get("diagnostics", []):
                        issues.append({
                            "file": d.get("file", file_path),
                            "line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                            "message": d.get("message", ""),
                            "severity": d.get("severity", "warning"),
                        })
                    return issues[:LOG_TRUNC_50]
            except Exception:
                logger.debug("lsp: pyright parse failed")

        # AST fallback
        full = os.path.join(self.root, file_path) if not os.path.isabs(file_path) else file_path
        tree = self._parse(full)
        if not tree:
            return [{"file": file_path, "line": 1, "message": "parse error", "severity": "error"}]
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not node.returns and node.name != "__init__":
                    issues.append({"file": file_path, "line": node.lineno,
                                    "message": f"missing return type on '{node.name}'",
                                    "severity": "warning"})
        return issues

    def file_type(self, file_path: str) -> str:
        """Detect language by extension."""
        ext = os.path.splitext(file_path)[1].lower()
        return {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".jsx": "javascript", ".rs": "rust",
            ".go": "go", ".java": "java", ".cpp": "cpp", ".c": "c",
            ".h": "c", ".hpp": "cpp", ".rb": "ruby",
            ".swift": "swift", ".kt": "kotlin",
        }.get(ext, "unknown")

    def _node_to_symbol(self, node: ast.AST, file_rel: str) -> Symbol | None:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            return Symbol(name=node.name, kind="class", file=file_rel,
                          line=node.lineno, docstring=doc)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            parent = ""
            for p in ast.walk(node):
                if isinstance(p, ast.ClassDef) and p != node:
                    for n in ast.walk(p):
                        if n is node:
                            parent = p.name
                            break
            return Symbol(name=node.name, kind="method" if parent else "function",
                          file=file_rel, line=node.lineno, parent=parent, docstring=doc)
        return None


_lsp_instance: LocalAnalyzer | None = None
_lsp_lock = threading.Lock()


def get_lsp(root: str = "") -> LocalAnalyzer:
    global _lsp_instance
    if _lsp_instance is None:
        with _lsp_lock:
            if _lsp_instance is None:
                _lsp_instance = LocalAnalyzer(root or os.getcwd())
    return _lsp_instance


def reset_lsp() -> None:
    global _lsp_instance
    _lsp_instance = None


# ── Tool handlers for agent consumption ──

def register_lsp_tools() -> None:
    """Register all LSP operations as agent-callable tools."""
    from .tool_system.tool_spec import ParamSpec, ToolRing, ToolSpec, register

    lsp = get_lsp()

    register(ToolSpec(
        name="lsp_symbol_search", description="Find symbols by name in workspace",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("query", "string", required=True),
                    ParamSpec("file_path", "string", default="")],
        handler=lambda args, aid: {"symbols": [
            {"name": s.name, "kind": s.kind, "file": s.file, "line": s.line}
            for s in lsp.symbol_search(args.get("query", ""), args.get("file_path", ""))
        ]},
    ))
    register(ToolSpec(
        name="lsp_go_to_definition", description="Find where a symbol is defined",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("name", "string", required=True),
                    ParamSpec("file_path", "string", default="")],
        handler=lambda args, aid: (lambda s: {"found": bool(s), "symbol": {
            "name": s.name, "kind": s.kind, "file": s.file, "line": s.line,
        } if s else None})(lsp.go_to_definition(args.get("name", ""), args.get("file_path", ""))),
    ))
    register(ToolSpec(
        name="lsp_find_references", description="Find all usages of a symbol",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("name", "string", required=True),
                    ParamSpec("file_path", "string", default="")],
        handler=lambda args, aid: {"references": lsp.find_references(
            args.get("name", ""), args.get("file_path", ""))},
    ))
    register(ToolSpec(
        name="lsp_hover_info", description="Get type/doc info for a symbol",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("name", "string", required=True),
                    ParamSpec("file_path", "string", default="")],
        handler=lambda args, aid: lsp.hover_info(args.get("name", ""), args.get("file_path", "")),
    ))
    register(ToolSpec(
        name="lsp_diagnostics", description="Get file errors and warnings",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("file_path", "string", required=True)],
        handler=lambda args, aid: {"diagnostics": lsp.diagnostics(args.get("file_path", ""))},
    ))
    register(ToolSpec(
        name="lsp_file_type", description="Detect programming language of a file",
        category="lsp", ring=ToolRing.RING_1, danger=0,
        parameters=[ParamSpec("file_path", "string", required=True)],
        handler=lambda args, aid: {"file": args.get("file_path", ""),
                                    "language": lsp.file_type(args.get("file_path", ""))},
    ))

    logger.info("lsp: registered 6 tools")
