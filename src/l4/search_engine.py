"""Search Engine — Semantic Search + Symbol Search + API Documentation Search

Three-layer search:
  1. SemanticSearch  — keyword + TF-IDF ranking (lightweight, no external dependencies)
  2. SymbolSearch    — AST-level code symbol query (cross-project classes/functions/variables)
  3. DocSearch       — API documentation indexing + search

API:
  POST /api/search/semantic — semantic code search
  POST /api/search/symbol   — search code symbols
  POST /api/search/docs     — search API documentation
  POST /api/search          — unified search entry (automatically picks the best approach)
"""

from __future__ import annotations

import ast
import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 1. Data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """单个搜索结果。"""
    path: str
    line: int = 0
    column: int = 0
    content: str = ""
    score: float = 0.0
    kind: str = "text"          # text | symbol | doc
    symbol_name: str = ""       # 符号名（符号搜索时）
    symbol_type: str = ""       # function | class | variable | method

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "content": self.content[:200],
            "score": round(self.score, 3),
            "kind": self.kind,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
        }


@dataclass
class DocEntry:
    """API 文档条目。"""
    package: str
    module: str
    name: str
    signature: str = ""
    docstring: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "module": self.module,
            "name": self.name,
            "signature": self.signature[:100],
            "docstring": self.docstring[:200],
            "url": self.url,
        }


# ══════════════════════════════════════════════════════════════════════
# 2. Semantic Search (TF-IDF lightweight)
# ══════════════════════════════════════════════════════════════════════


class SemanticSearch:
    """轻量级语义搜索 — TF-IDF 关键词排序，无需外部依赖。"""

    def __init__(self):
        self._lock = threading.Lock()

    def search(self, query: str, root_dir: str = ".",
               file_pattern: str = "*.py", max_results: int = 20,
               include_content: bool = True) -> dict:
        """按关键词搜索代码内容，TF-IDF 排序。"""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        query_terms = query.lower().split()
        if not query_terms:
            return {"success": False, "error": "empty query"}

        # 1. 收集匹配文件
        matches: list[SearchResult] = []
        files = list(root.rglob(file_pattern))

        for file_path in files:
            if self._is_ignored(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                for i, line in enumerate(lines, 1):
                    line_lower = line.lower()
                    # 计算 TF-IDF 分数
                    score = sum(1 for t in query_terms
                                if t in line_lower)
                    if score > 0:
                        # IDF 加权：稀有词权重更高
                        idf_score = sum(
                            1.0 / (1.0 + self._term_frequency(t, content))
                            for t in query_terms if t in line_lower
                        )
                        score = score * idf_score
                        matches.append(SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=i,
                            content=line.strip() if include_content else "",
                            score=score,
                            kind="text",
                        ))
            except Exception:
                continue

        # 2. 按分数降序排列
        matches.sort(key=lambda r: -r.score)
        results = matches[:max_results]

        return {
            "success": True,
            "query": query,
            "total_matches": len(matches),
            "results": [r.to_dict() for r in results],
            "truncated": len(matches) > max_results,
        }

    def _is_ignored(self, path: Path) -> bool:
        """跳过 .git, node_modules, __pycache__, .venv 等。"""
        ignored_parts = {".git", "node_modules", "__pycache__",
                         ".venv", "venv", ".tox", ".egg-info"}
        return any(p in ignored_parts for p in path.parts)

    def _term_frequency(self, term: str, content: str) -> float:
        return content.lower().count(term) / max(len(content), 1)


# ══════════════════════════════════════════════════════════════════════
# 3. Symbol Search (AST-based)
# ══════════════════════════════════════════════════════════════════════


class SymbolSearch:
    """AST 级代码符号搜索 — 跨项目查找类/函数/变量。"""

    LANGUAGES: dict[str, tuple[str, list[str]]] = {
        "python": ("python", [".py"]),
        "javascript": ("javascript", [".js", ".jsx", ".mjs"]),
        "typescript": ("typescript", [".ts", ".tsx"]),
    }

    def __init__(self):
        self._lock = threading.Lock()

    def search(self, name: str, kind: str = "",
               root_dir: str = ".", max_results: int = 30) -> dict:
        """搜索代码符号。"""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        term = name.lower()
        results: list[SearchResult] = []

        # Python AST 搜索
        for file_path in root.rglob("*.py"):
            if self._is_ignored(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    match = None
                    if isinstance(node, ast.FunctionDef) and term in node.name.lower():
                        if kind and kind not in ("function", "method", ""):
                            continue
                        match = SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=node.lineno or 1,
                            content=ast.unparse(node).splitlines()[0][:200]
                            if hasattr(ast, 'unparse') else f"def {node.name}(...):",
                            score=1.0 if node.name.lower() == term else 0.5,
                            kind="symbol",
                            symbol_name=node.name,
                            symbol_type="method" if self._is_method(node) else "function",
                        )
                    elif isinstance(node, ast.ClassDef) and term in node.name.lower():
                        if kind and kind != "class":
                            continue
                        match = SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=node.lineno or 1,
                            content=f"class {node.name}:",
                            score=1.0 if node.name.lower() == term else 0.5,
                            kind="symbol",
                            symbol_name=node.name,
                            symbol_type="class",
                        )
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and term in target.id.lower():
                                match = SearchResult(
                                    path=str(file_path.relative_to(root)),
                                    line=node.lineno or 1,
                                    content=f"{target.id} = ...",
                                    score=0.3,
                                    kind="symbol",
                                    symbol_name=target.id,
                                    symbol_type="variable",
                                )
                                break

                    if match:
                        results.append(match)

            except SyntaxError:
                continue
            except Exception:
                continue

        # 去重 + 排序
        seen: set[tuple[str, int, str]] = set()
        unique: list[SearchResult] = []
        for r in results:
            key = (r.path, r.line, r.symbol_name)
            if key not in seen:
                seen.add(key)
                unique.append(r)

        unique.sort(key=lambda r: -r.score)
        top = unique[:max_results]

        return {
            "success": True,
            "query": name,
            "kind": kind or "any",
            "total_matches": len(unique),
            "results": [r.to_dict() for r in top],
        }

    def _is_method(self, node: ast.FunctionDef) -> bool:
        """判断函数是否类内方法（检查父节点）。"""
        for n in ast.walk(node):
            if isinstance(n, ast.ClassDef):
                for item in n.body:
                    if item is node:
                        return True
        return False

    def _is_ignored(self, path: Path) -> bool:
        return SemanticSearch()._is_ignored(path)


# ══════════════════════════════════════════════════════════════════════
# 4. Doc Search (Built-in API docs index)
# ══════════════════════════════════════════════════════════════════════


class DocSearch:
    """API 文档搜索 — 内建索引 + 动态扩展。"""

    # Python stdlib 常用模块的快速参考索引
    STDLIB_INDEX: dict[str, DocEntry] = {
        "pathlib.Path": DocEntry("stdlib", "pathlib", "Path",
                                 "Path(*pathsegments)",
                                 "PurePath subclass for concrete paths.",
                                 "https://docs.python.org/3/library/pathlib.html"),
        "os.path.join": DocEntry("stdlib", "os.path", "join",
                                 "os.path.join(path, *paths)",
                                 "Join path segments intelligently.",
                                 "https://docs.python.org/3/library/os.path.html"),
        "json.dumps": DocEntry("stdlib", "json", "dumps",
                               "json.dumps(obj, *, ...)",
                               "Serialize object to JSON string.",
                               "https://docs.python.org/3/library/json.html"),
        "json.loads": DocEntry("stdlib", "json", "loads",
                               "json.loads(s, *, ...)",
                               "Deserialize JSON string to object.",
                               "https://docs.python.org/3/library/json.html"),
        "re.search": DocEntry("stdlib", "re", "search",
                              "re.search(pattern, string, flags=0)",
                              "Search string for match to pattern.",
                              "https://docs.python.org/3/library/re.html"),
        "subprocess.run": DocEntry("stdlib", "subprocess", "run",
                                   "subprocess.run(args, *, ...)",
                                   "Run command with arguments.",
                                   "https://docs.python.org/3/library/subprocess.html"),
        "threading.Thread": DocEntry("stdlib", "threading", "Thread",
                                     "Thread(target=None, ...)",
                                     "Create a new thread.",
                                     "https://docs.python.org/3/library/threading.html"),
        "dataclasses.dataclass": DocEntry("stdlib", "dataclasses", "dataclass",
                                          "@dataclass(*, ...)",
                                          "Decorator for data class.",
                                          "https://docs.python.org/3/library/dataclasses.html"),
        "logging.getLogger": DocEntry("stdlib", "logging", "getLogger",
                                      "logging.getLogger(name=None)",
                                      "Return a logger with the given name.",
                                      "https://docs.python.org/3/library/logging.html"),
        "pathlib.Path.read_text": DocEntry("stdlib", "pathlib", "Path.read_text",
                                           "Path.read_text(encoding=None, ...)",
                                           "Read file contents as string.",
                                           "https://docs.python.org/3/library/pathlib.html"),
        "pathlib.Path.write_text": DocEntry("stdlib", "pathlib", "Path.write_text",
                                            "Path.write_text(data, encoding=None, ...)",
                                            "Write string to file.",
                                            "https://docs.python.org/3/library/pathlib.html"),
        "hashlib.sha256": DocEntry("stdlib", "hashlib", "sha256",
                                   "hashlib.sha256(data=b'', ...)",
                                   "Return SHA-256 hash object.",
                                   "https://docs.python.org/3/library/hashlib.html"),
        "os.environ.get": DocEntry("stdlib", "os", "environ.get",
                                   "os.environ.get(key, default=None)",
                                   "Get environment variable.",
                                   "https://docs.python.org/3/library/os.html"),
    }

    def __init__(self):
        self._custom_index: dict[str, DocEntry] = {}

    def search(self, query: str, max_results: int = 10) -> dict:
        """搜索 API 文档。"""
        q = query.lower()
        results: list[DocEntry] = []

        # 搜索内置索引
        all_entries = dict(self.STDLIB_INDEX)
        all_entries.update(self._custom_index)

        for key, entry in all_entries.items():
            score = 0
            if q in key.lower():
                score += 2
            if q in entry.name.lower():
                score += 1
            if q in entry.docstring.lower():
                score += 0.5
            if q in entry.module.lower():
                score += 0.3
            if q in entry.package.lower():
                score += 0.2
            if score > 0:
                results.append(entry)

        # 按分数排序
        results.sort(key=lambda e: -self._rank(e, q))
        top = results[:max_results]

        return {
            "success": True,
            "query": query,
            "total": len(results),
            "results": [e.to_dict() for e in top],
        }

    def _rank(self, entry: DocEntry, query: str) -> float:
        score = 0
        full = f"{entry.package}.{entry.module}.{entry.name}".lower()
        if query in full:
            score += 2
        if query in entry.name.lower():
            score += 1
        if query in entry.docstring.lower():
            score += 0.5
        return score

    def index(self, package: str, module: str, name: str,
              signature: str = "", docstring: str = "",
              url: str = "") -> dict:
        """注册自定义 API 文档。"""
        key = f"{package}.{module}.{name}"
        self._custom_index[key] = DocEntry(
            package=package,
            module=module,
            name=name,
            signature=signature,
            docstring=docstring,
            url=url,
        )
        return {"success": True, "key": key}


# ══════════════════════════════════════════════════════════════════════
# 5. Search Engine (facade)
# ══════════════════════════════════════════════════════════════════════


class SearchEngine:
    """统一搜索入口 — 自动选择最佳搜索方式。"""

    def __init__(self):
        self._semantic = SemanticSearch()
        self._symbol = SymbolSearch()
        self._docs = DocSearch()
        self._lock = threading.Lock()

    def search(self, query: str, mode: str = "auto",
               root_dir: str = ".", max_results: int = 20) -> dict:
        """统一搜索入口。

        mode:
          "auto"     — 智能选择（含大写字母/点 → 符号搜索；含 import/lib → 文档搜索；否则语义搜索）
          "semantic" — 语义搜索
          "symbol"   — 符号搜索
          "docs"     — 文档搜索
        """
        if mode == "semantic":
            return self._semantic.search(query, root_dir, max_results=max_results)
        elif mode == "symbol":
            return self._symbol.search(query, root_dir=root_dir, max_results=max_results)
        elif mode == "docs":
            return self._docs.search(query, max_results=max_results)
        else:
            # auto: 智能选择
            if "." in query or query[0].isupper():
                sym_r = self._symbol.search(query, root_dir=root_dir,
                                            max_results=max_results)
                if sym_r.get("total_matches", 0) > 0:
                    return sym_r
                doc_r = self._docs.search(query, max_results=max_results)
                if doc_r.get("total", 0) > 0:
                    return doc_r
            elif any(kw in query.lower() for kw in ("import ", "lib.", "api.")):
                return self._docs.search(query, max_results=max_results)

            return self._semantic.search(query, root_dir, max_results=max_results)

    def semantic_search(self, query: str, root_dir: str = ".",
                        file_pattern: str = "*.py",
                        max_results: int = 20) -> dict:
        return self._semantic.search(query, root_dir, file_pattern, max_results)

    def symbol_search(self, name: str, kind: str = "",
                      root_dir: str = ".", max_results: int = 30) -> dict:
        return self._symbol.search(name, kind, root_dir, max_results)

    def doc_search(self, query: str, max_results: int = 10) -> dict:
        return self._docs.search(query, max_results)

    def index_doc(self, package: str, module: str, name: str,
                  signature: str = "", docstring: str = "", url: str = "") -> dict:
        return self._docs.index(package, module, name, signature, docstring, url)


# ══════════════════════════════════════════════════════════════════════
# 6. 全局单例
# ══════════════════════════════════════════════════════════════════════

_engine: SearchEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> SearchEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SearchEngine()
    return _engine


# ══════════════════════════════════════════════════════════════════════
# 7. API Handlers
# ══════════════════════════════════════════════════════════════════════


def handle_search(body: dict | None = None) -> dict:
    """POST /api/search — 统一搜索入口"""
    b = body or {}
    query = b.get("query", "")
    mode = b.get("mode", "auto")
    root = b.get("root", ".")
    max_results = b.get("max_results", 20)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().search(query, mode=mode, root_dir=root,
                               max_results=max_results)


def handle_search_semantic(body: dict | None = None) -> dict:
    """POST /api/search/semantic — 语义搜索"""
    b = body or {}
    query = b.get("query", "")
    root = b.get("root", ".")
    pattern = b.get("pattern", "*.py")
    max_results = b.get("max_results", 20)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().semantic_search(query, root, pattern, max_results)


def handle_search_symbol(body: dict | None = None) -> dict:
    """POST /api/search/symbol — 符号搜索"""
    b = body or {}
    name = b.get("name", "")
    kind = b.get("kind", "")
    root = b.get("root", ".")
    max_results = b.get("max_results", 30)
    if not name:
        return {"success": False, "error": "name required"}
    return get_engine().symbol_search(name, kind, root, max_results)


def handle_search_docs(body: dict | None = None) -> dict:
    """POST /api/search/docs — API 文档搜索"""
    b = body or {}
    query = b.get("query", "")
    max_results = b.get("max_results", 10)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().doc_search(query, max_results)


def handle_search_index_doc(body: dict | None = None) -> dict:
    """POST /api/search/docs/index — 注册自定义 API 文档"""
    b = body or {}
    return get_engine().index_doc(
        package=b.get("package", ""),
        module=b.get("module", ""),
        name=b.get("name", ""),
        signature=b.get("signature", ""),
        docstring=b.get("docstring", ""),
        url=b.get("url", ""),
    )


# ── 路由注册 ──

SEARCH_ROUTES: list[tuple[str, str, Any, str]] = [
    ("POST", "/api/search", handle_search, "Unified search (auto-select mode)"),
    ("POST", "/api/search/semantic", handle_search_semantic, "Semantic code search"),
    ("POST", "/api/search/symbol", handle_search_symbol, "Symbol search (AST-based)"),
    ("POST", "/api/search/docs", handle_search_docs, "API documentation search"),
    ("POST", "/api/search/docs/index", handle_search_index_doc, "Index custom API doc"),
]
