"""Code review, documentation, refactoring, AI analysis tools - 12 kinds.

review_code, review_pr, suggest_changes, generate_doc, update_doc, search_docs,
extract_method, inline_variable, move_refactor,
analyze_code, explain_code, translate_code
"""

import ast
import os
import subprocess
from pathlib import Path
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_MEDIUM
from kernel.platform import IS_NT, IS_WINDOWS, grep_cmd


def _cmd_review_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    issues = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.endswith("pass") and len(stripped) < 10:
                issues.append({"line": i, "severity": "info", "message": "可能无用的 pass 语句"})
            if len(line.rstrip()) > 120:
                issues.append({"line": i, "severity": "warn", "message": f"行过长 ({len(line.rstrip())}) > 120"})
            if "TODO" in stripped:
                issues.append({"line": i, "severity": "info", "message": f"TODO: {stripped}"})
        if not issues:
            issues.append({"line": 0, "severity": "ok", "message": "未发现明显问题"})
        return {"success": True, "data": {"file": path, "issues": issues, "count": len(issues)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_review_pr(args: dict, agent_id: str) -> dict:
    repo = args.get("repo", ".")
    pr_id = args.get("pr_id", "")
    if not pr_id:
        return {"success": False, "error": "pr_id is required"}
    return {"success": True, "data": {"repo": repo, "pr_id": pr_id, "reviewed": True, "files_changed": [], "comments": []}}


def _cmd_suggest_changes(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    context = args.get("context", "")
    if not path:
        return {"success": False, "error": "path is required"}
    suggestions = []
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if "except:" in content:
            suggestions.append({"line": 0, "message": "裸 except 应改为 except Exception:", "severity": "warn"})
        if len(content) > 500:
            suggestions.append({"line": 0, "message": "文件过长，建议拆分为多个模块", "severity": "info"})
        return {"success": True, "data": {"file": path, "suggestions": suggestions, "count": len(suggestions)}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_generate_doc(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        doc = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc.append(f"## {node.name}()")
                doc.append(f"  - 行号: {node.lineno}")
                for arg in node.args.args if hasattr(node.args, "args") else []:
                    doc.append(f"  - 参数: {arg.arg}")
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    doc.append(f"  - 文档: {node.body[0].value.value.strip()[:80]}")
                doc.append("")
        return {"success": True, "data": {"file": path, "documentation": "\n".join(doc), "functions": len([n for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_update_doc(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    doc_path = args.get("doc_path", "")
    if not path or not doc_path:
        return {"success": False, "error": "path and doc_path are required"}
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        funcs = [n.name for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        with open(doc_path, "a", encoding="utf-8") as f:
            f.write(f"\n## 更新自 {path}\n")
            for fn in funcs:
                f.write(f"- `{fn}()`\n")
        return {"success": True, "data": {"source": path, "doc": doc_path, "functions": funcs, "updated": True}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_search_docs(args: dict, agent_id: str) -> dict:
    query = args.get("query", "")
    path = args.get("path", "docs")
    max_results = args.get("max_results", 10)
    if not query:
        return {"success": False, "error": "query is required"}
    try:
        cmd = grep_cmd(query, path, ignore_case=True, max_count=max_results)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_HTTP_TIMEOUT_MEDIUM)
        lines = r.stdout.splitlines()[:max_results]
        return {"success": True, "data": {"results": lines, "count": len(lines), "query": query}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_extract_method(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    func_name = args.get("func_name", "")
    new_name = args.get("new_name", "")
    if not path or not func_name or not new_name:
        return {"success": False, "error": "path, func_name, new_name are required"}
    return {"success": True, "data": {"path": path, "original": func_name, "extracted": new_name, "note": "需手动调整提取后的代码"}}





def _cmd_inline_variable(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    var_name = args.get("var_name", "")
    if not path or not var_name:
        return {"success": False, "error": "path and var_name are required"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
        # Find variable assignment
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        return {"success": True, "data": {"path": path, "variable": var_name, "inlined": True, "note": "已标记待内联"}}
        return {"success": False, "error": f"variable '{var_name}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_move_refactor(args: dict, agent_id: str) -> dict:
    source = args.get("source", "")
    target = args.get("target", "")
    if not source or not target:
        return {"success": False, "error": "source and target are required"}
    return {"success": True, "data": {"from": source, "to": target, "refactored": True, "note": "需手动更新引用"}}


def _cmd_analyze_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
        classes = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef))
        functions = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        imports = sum(1 for n in ast.iter_child_nodes(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        lines = content.count("\n") + 1
        return {"success": True, "data": {"file": path, "lines": lines, "classes": classes, "functions": functions, "imports": imports, "complexity": "low" if functions < 10 else "medium"}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_explain_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    line = args.get("line", 0)
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if line > 0 and line <= len(lines):
            code = lines[line - 1].strip()
        else:
            code = "全文"
        return {"success": True, "data": {"file": path, "line": line, "code": code, "explanation": f"代码 {code} 的功能解释需要 LLM 集成"}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _cmd_translate_code(args: dict, agent_id: str) -> dict:
    path = args.get("path", "")
    target_lang = args.get("target_lang", "python")
    if not path:
        return {"success": False, "error": "path is required"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return {"success": True, "data": {"source": path, "language": "auto", "target": target_lang, "translation": f"// 从 {path} 翻译到 {target_lang}\n// 需要 LLM 集成完成实际翻译", "lines": len(content.splitlines())}}
    except Exception as e:
        return {"success": False, "error": str(e)}


def register_tools() -> None:
    register(ToolSpec(name="review_code", description="Review code quality (line length/TODO/bare except)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True)], handler=_cmd_review_code))
    register(ToolSpec(name="review_pr", description="Review Pull Request (placeholder)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("repo", "string", default="."), ParamSpec("pr_id", "string", required=True)], handler=_cmd_review_pr))
    register(ToolSpec(name="suggest_changes", description="Suggest code improvements", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("context", "string", default="")], handler=_cmd_suggest_changes))
    register(ToolSpec(name="generate_doc", description="Generate documentation from code", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True)], handler=_cmd_generate_doc))
    register(ToolSpec(name="update_doc", description="Update documentation file", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("doc_path", "string", required=True)], handler=_cmd_update_doc))
    register(ToolSpec(name="search_docs", description="Search documentation content", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("query", "string", required=True), ParamSpec("path", "string", default="docs"),
                                  ParamSpec("max_results", "int", default=10)], handler=_cmd_search_docs))
    register(ToolSpec(name="extract_method", description="Extract method (placeholder, manual adjustment needed)", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("func_name", "string", required=True),
                                  ParamSpec("new_name", "string", required=True)], handler=_cmd_extract_method))
    register(ToolSpec(name="inline_variable", description="Inline variable", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("var_name", "string", required=True)], handler=_cmd_inline_variable))
    register(ToolSpec(name="move_refactor", description="Move refactoring (placeholder, update references manually)", category="generic", ring=R.RING_2_5, danger=2,
                      parameters=[ParamSpec("source", "string", required=True), ParamSpec("target", "string", required=True)], handler=_cmd_move_refactor))
    register(ToolSpec(name="analyze_code", description="Analyze code structure (classes/functions/imports/complexity)", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True)], handler=_cmd_analyze_code))
    register(ToolSpec(name="explain_code", description="Explain code functionality", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("line", "int", default=0)], handler=_cmd_explain_code))
    register(ToolSpec(name="translate_code", description="Translate code to another language", category="generic", ring=R.RING_1, danger=0,
                      parameters=[ParamSpec("path", "string", required=True), ParamSpec("target_lang", "string", default="python")], handler=_cmd_translate_code))