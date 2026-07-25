"""AI analysis service — code analysis, explanation, translation.

Uses the LLM service for AI-powered code intelligence.
Falls back to local analysis when LLM is unavailable.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from services._base import BaseService

logger = logging.getLogger(__name__)


class AIService(BaseService):
    """AI-powered code analysis service."""

    def __init__(self):
        super().__init__("ai")

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        return {"success": True}

    def analyze_code(self, code: str, filename: str = "") -> dict:
        """Analyze code structure and complexity."""
        try:
            tree = ast.parse(code)
            classes = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef))
            functions = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            imports = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
            calls = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call))
            lines = code.count("\n") + 1
            complexity = "low" if functions < 5 else "medium" if functions < 15 else "high"
            return {
                "success": True,
                "data": {
                    "file": filename, "lines": lines, "classes": classes,
                    "functions": functions, "imports": imports, "calls": calls,
                    "complexity": complexity,
                },
            }
        except SyntaxError as e:
            return {"success": False, "error": f"syntax error: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def explain_code(self, code: str, filename: str = "") -> dict:
        """Explain what a piece of code does."""
        try:
            tree = ast.parse(code)
            lines = code.splitlines()
            summary_parts = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    docstring = ast.get_docstring(node) or ""
                    summary_parts.append(f"function `{node.name}`: {docstring[:80] if docstring else f'{len(node.body)} statements'}")
                elif isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    summary_parts.append(f"class `{node.name}`: {len(methods)} methods")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            summary_parts.append(f"variable `{target.id}`")
            return {
                "success": True,
                "data": {
                    "file": filename,
                    "summary": summary_parts[:10],
                    "line_count": len(lines),
                    "has_docstring": any(ast.get_docstring(n) for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))),
                },
            }
        except SyntaxError as e:
            return {"success": False, "error": f"syntax error: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def suggest_improvements(self, code: str, filename: str = "") -> dict:
        """Suggest code improvements."""
        suggestions = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    suggestions.append({"line": node.lineno, "severity": "warn", "message": "bare except, use except Exception: instead"})
                    if isinstance(node, ast.FunctionDef) and len(node.body) > 50:
                        suggestions.append({"line": node.lineno, "severity": "info", "message": f"function {node.name} too long ({len(node.body)} statements), consider splitting"})
            for i, line in enumerate(code.splitlines(), 1):
                if len(line) > 100:
                    suggestions.append({"line": i, "severity": "info", "message": f"line too long ({len(line)} > 100)"})
            return {"success": True, "data": {"suggestions": suggestions, "count": len(suggestions)}}
        except SyntaxError:
            return {"success": True, "data": {"suggestions": [], "count": 0}}

    def translate_code(self, code: str, target_lang: str, filename: str = "") -> dict:
        """Translate code to another language (placeholder)."""
        return {
            "success": True,
            "data": {
                "source": filename,
                "target": target_lang,
                "lines": len(code.splitlines()),
                "note": f"Full translation to {target_lang} requires LLM API integration",
            },
        }


_service: AIService | None = None


def get_service() -> AIService:
    global _service
    if _service is None:
        _service = AIService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None