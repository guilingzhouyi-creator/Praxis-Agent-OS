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
import threading
from dataclasses import dataclass
from pathlib import Path

from l1.kernel.discovery import get_service_limit
from l1.kernel.params.system import (
    DOC_SEARCH_RESULTS,
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    SEARCH_CACHE_MAX,
    SEARCH_DEFAULT_RESULTS,
    SEARCH_SCORE_DOCSTRING_MATCH,
    SEARCH_SCORE_FULL_MATCH,
    SEARCH_SCORE_MODULE_MATCH,
    SEARCH_SCORE_NAME_MATCH,
    SEARCH_SCORE_PACKAGE_MATCH,
    SEARCH_SYMBOL_ASSIGN_MATCH,
    SEARCH_SYMBOL_EXACT_MATCH,
    SEARCH_SYMBOL_PARTIAL_MATCH,
    SYMBOL_SEARCH_RESULTS,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 1. Data models
# ══════════════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """A single search result."""

    path: str
    line: int = 0
    column: int = 0
    content: str = ""
    score: float = 0.0
    kind: str = "text"  # text | symbol | doc
    symbol_name: str = ""  # symbol name (when symbol search)
    symbol_type: str = ""  # function | class | variable | method

    def to_dict(self) -> dict:
        """Convert the search result to a serializable dict."""
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "content": self.content[:LOG_TRUNC_200],
            "score": round(self.score, 3),
            "kind": self.kind,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
        }


@dataclass
class DocEntry:
    """An API documentation entry."""

    package: str
    module: str
    name: str
    signature: str = ""
    docstring: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        """Convert the doc entry to a serializable dict."""
        return {
            "package": self.package,
            "module": self.module,
            "name": self.name,
            "signature": self.signature[:LOG_TRUNC_100],
            "docstring": self.docstring[:LOG_TRUNC_200],
            "url": self.url,
        }


# ══════════════════════════════════════════════════════════════════════
# 2. Semantic Search (TF-IDF lightweight)
# ══════════════════════════════════════════════════════════════════════


class SemanticSearch:
    """Lightweight semantic search — TF-IDF keyword ranking, no external dependencies."""

    def __init__(self):
        self._lock = threading.Lock()

    def search(
        self,
        query: str,
        root_dir: str = ".",
        file_pattern: str = "*.py",
        max_results: int = SEARCH_DEFAULT_RESULTS,
        include_content: bool = True,
    ) -> dict:
        """Search code content by keyword, ranked by TF-IDF."""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        query_terms = query.lower().split()
        if not query_terms:
            return {"success": False, "error": "empty query"}

        # 1. Collect matching files
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
                    # Compute TF-IDF score
                    score: float = sum(1 for t in query_terms if t in line_lower)
                    if score > 0:
                        # IDF weighting: rare terms get higher weight
                        idf_score = sum(
                            1.0 / (1.0 + self._term_frequency(t, content)) for t in query_terms if t in line_lower
                        )
                        score = score * idf_score
                        matches.append(
                            SearchResult(
                                path=str(file_path.relative_to(root)),
                                line=i,
                                content=line.strip() if include_content else "",
                                score=score,
                                kind="text",
                            )
                        )
            except Exception:
                continue

        # 2. Sort by score descending
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
        """Skip .git, node_modules, __pycache__, .venv, etc."""
        ignored_parts = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".egg-info"}
        return any(p in ignored_parts for p in path.parts)

    def _term_frequency(self, term: str, content: str) -> float:
        return content.lower().count(term) / max(len(content), 1)


# ══════════════════════════════════════════════════════════════════════
# 3. Symbol Search (AST-based)
# ══════════════════════════════════════════════════════════════════════


class SymbolSearch:
    """AST-level code symbol search — find classes/functions/variables across projects.

    Caches parsed AST trees per file, invalidated by mtime change,
    to avoid O(N) re-parsing on repeated searches.
    """

    _ast_cache: dict[tuple[str, float], ast.Module] = {}  # (path, mtime) → AST
    _CACHE_MAX = SEARCH_CACHE_MAX

    LANGUAGES: dict[str, tuple[str, list[str]]] = {
        "python": ("python", [".py"]),
        "javascript": ("javascript", [".js", ".jsx", ".mjs"]),
        "typescript": ("typescript", [".ts", ".tsx"]),
    }

    def __init__(self):
        self._lock = threading.Lock()
        # Declarative override via config/discovery/service_limits.yaml,
        # params constant as fallback (AGENTS.md three-layer config).
        self._cache_max = get_service_limit("search_cache_max", SEARCH_CACHE_MAX)

    def search(self, name: str, kind: str = "", root_dir: str = ".", max_results: int = SYMBOL_SEARCH_RESULTS) -> dict:
        """Search for code symbols."""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        term = name.lower()
        results: list[SearchResult] = []

        # Python AST search — use cached AST with mtime invalidation
        for file_path in root.rglob("*.py"):
            if self._is_ignored(file_path):
                continue
            try:
                mtime = file_path.stat().st_mtime
                cache_key = (str(file_path), mtime)
                cached = self._ast_cache.get(cache_key)
                if cached is not None:
                    tree = cached
                else:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(content)
                    # LRU eviction: keep cache bounded
                    if len(self._ast_cache) >= self._cache_max:
                        # Remove oldest entry (dict preserves insertion order in 3.7+)
                        self._ast_cache.pop(next(iter(self._ast_cache)))
                    self._ast_cache[cache_key] = tree
                for node in ast.walk(tree):
                    match = None
                    if isinstance(node, ast.FunctionDef) and term in node.name.lower():
                        if kind and kind not in ("function", "method", ""):
                            continue
                        match = SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=node.lineno or 1,
                            content=ast.unparse(node).splitlines()[0][:LOG_TRUNC_200]
                            if hasattr(ast, "unparse")
                            else f"def {node.name}(...):",
                            score=SEARCH_SYMBOL_EXACT_MATCH
                            if node.name.lower() == term
                            else SEARCH_SYMBOL_PARTIAL_MATCH,
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
                            score=SEARCH_SYMBOL_EXACT_MATCH
                            if node.name.lower() == term
                            else SEARCH_SYMBOL_PARTIAL_MATCH,
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
                                    score=SEARCH_SYMBOL_ASSIGN_MATCH,
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

        # Deduplicate + sort
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
        """Determine if a function is a method inside a class (check parent node)."""
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
    """API documentation search — built-in index + dynamic extension."""

    # Fast reference index for common Python stdlib modules
    STDLIB_INDEX: dict[str, DocEntry] = {
        "pathlib.Path": DocEntry(
            "stdlib",
            "pathlib",
            "Path",
            "Path(*pathsegments)",
            "PurePath subclass for concrete paths.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "os.path.join": DocEntry(
            "stdlib",
            "os.path",
            "join",
            "os.path.join(path, *paths)",
            "Join path segments intelligently.",
            "https://docs.python.org/3/library/os.path.html",
        ),
        "json.dumps": DocEntry(
            "stdlib",
            "json",
            "dumps",
            "json.dumps(obj, *, ...)",
            "Serialize object to JSON string.",
            "https://docs.python.org/3/library/json.html",
        ),
        "json.loads": DocEntry(
            "stdlib",
            "json",
            "loads",
            "json.loads(s, *, ...)",
            "Deserialize JSON string to object.",
            "https://docs.python.org/3/library/json.html",
        ),
        "re.search": DocEntry(
            "stdlib",
            "re",
            "search",
            "re.search(pattern, string, flags=0)",
            "Search string for match to pattern.",
            "https://docs.python.org/3/library/re.html",
        ),
        "subprocess.run": DocEntry(
            "stdlib",
            "subprocess",
            "run",
            "subprocess.run(args, *, ...)",
            "Run command with arguments.",
            "https://docs.python.org/3/library/subprocess.html",
        ),
        "threading.Thread": DocEntry(
            "stdlib",
            "threading",
            "Thread",
            "Thread(target=None, ...)",
            "Create a new thread.",
            "https://docs.python.org/3/library/threading.html",
        ),
        "dataclasses.dataclass": DocEntry(
            "stdlib",
            "dataclasses",
            "dataclass",
            "@dataclass(*, ...)",
            "Decorator for data class.",
            "https://docs.python.org/3/library/dataclasses.html",
        ),
        "logging.getLogger": DocEntry(
            "stdlib",
            "logging",
            "getLogger",
            "logging.getLogger(name=None)",
            "Return a logger with the given name.",
            "https://docs.python.org/3/library/logging.html",
        ),
        "pathlib.Path.read_text": DocEntry(
            "stdlib",
            "pathlib",
            "Path.read_text",
            "Path.read_text(encoding=None, ...)",
            "Read file contents as string.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "pathlib.Path.write_text": DocEntry(
            "stdlib",
            "pathlib",
            "Path.write_text",
            "Path.write_text(data, encoding=None, ...)",
            "Write string to file.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "hashlib.sha256": DocEntry(
            "stdlib",
            "hashlib",
            "sha256",
            "hashlib.sha256(data=b'', ...)",
            "Return SHA-256 hash object.",
            "https://docs.python.org/3/library/hashlib.html",
        ),
        "os.environ.get": DocEntry(
            "stdlib",
            "os",
            "environ.get",
            "os.environ.get(key, default=None)",
            "Get environment variable.",
            "https://docs.python.org/3/library/os.html",
        ),
    }

    def __init__(self):
        self._custom_index: dict[str, DocEntry] = {}

    def search(self, query: str, max_results: int = DOC_SEARCH_RESULTS) -> dict:
        """Search API documentation."""
        q = query.lower()
        results: list[DocEntry] = []

        # Search built-in index
        all_entries = dict(self.STDLIB_INDEX)
        all_entries.update(self._custom_index)

        for key, entry in all_entries.items():
            score = 0
            if q in key.lower():
                score += SEARCH_SCORE_FULL_MATCH
            if q in entry.name.lower():
                score += SEARCH_SCORE_NAME_MATCH
            if q in entry.docstring.lower():
                score += SEARCH_SCORE_DOCSTRING_MATCH
            if q in entry.module.lower():
                score += SEARCH_SCORE_MODULE_MATCH
            if q in entry.package.lower():
                score += SEARCH_SCORE_PACKAGE_MATCH
            if score > 0:
                results.append(entry)

        # Sort by score
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
            score += SEARCH_SCORE_FULL_MATCH
        if query in entry.name.lower():
            score += SEARCH_SCORE_NAME_MATCH
        if query in entry.docstring.lower():
            score += SEARCH_SCORE_DOCSTRING_MATCH
        return score

    def index(
        self, package: str, module: str, name: str, signature: str = "", docstring: str = "", url: str = ""
    ) -> dict:
        """Register a custom API documentation entry."""
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
    """Unified search entry — automatically selects the best search method."""

    def __init__(self):
        self._semantic = SemanticSearch()
        self._symbol = SymbolSearch()
        self._docs = DocSearch()
        self._lock = threading.Lock()

    def search(
        self, query: str, mode: str = "auto", root_dir: str = ".", max_results: int = SEARCH_DEFAULT_RESULTS
    ) -> dict:
        """Unified search entry.

        mode:
          "auto"     — smart selection (uppercase/dot → symbol search; import/lib → doc search; otherwise semantic search)
          "semantic" — semantic search
          "symbol"   — symbol search
          "docs"     — doc search
        """
        if mode == "semantic":
            return self._semantic.search(query, root_dir, max_results=max_results)
        if mode == "symbol":
            return self._symbol.search(query, root_dir=root_dir, max_results=max_results)
        if mode == "docs":
            return self._docs.search(query, max_results=max_results)
        # auto: smart selection
        if "." in query or query[0].isupper():
            sym_r = self._symbol.search(query, root_dir=root_dir, max_results=max_results)
            if sym_r.get("total_matches", 0) > 0:
                return sym_r
            doc_r = self._docs.search(query, max_results=max_results)
            if doc_r.get("total", 0) > 0:
                return doc_r
        elif any(kw in query.lower() for kw in ("import ", "lib.", "api.")):
            return self._docs.search(query, max_results=max_results)

        return self._semantic.search(query, root_dir, max_results=max_results)

    def semantic_search(
        self, query: str, root_dir: str = ".", file_pattern: str = "*.py", max_results: int = SEARCH_DEFAULT_RESULTS
    ) -> dict:
        """Run a semantic (TF-IDF) keyword search over the directory."""
        return self._semantic.search(query, root_dir, file_pattern, max_results)

    def symbol_search(
        self, name: str, kind: str = "", root_dir: str = ".", max_results: int = SYMBOL_SEARCH_RESULTS
    ) -> dict:
        """Search for code symbols by name, optionally filtered by kind."""
        return self._symbol.search(name, kind, root_dir, max_results)

    def doc_search(self, query: str, max_results: int = DOC_SEARCH_RESULTS) -> dict:
        """Search the indexed API documentation entries."""
        return self._docs.search(query, max_results)

    def index_doc(
        self, package: str, module: str, name: str, signature: str = "", docstring: str = "", url: str = ""
    ) -> dict:
        """Index an API documentation entry for doc search."""
        return self._docs.index(package, module, name, signature, docstring, url)


# ══════════════════════════════════════════════════════════════════════
# 6. Global singleton
# ══════════════════════════════════════════════════════════════════════

_engine: SearchEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> SearchEngine:
    """Return the process-wide SearchEngine singleton."""
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
    """POST /api/search — unified search entry"""
    b = body or {}
    query = b.get("query", "")
    mode = b.get("mode", "auto")
    root = b.get("root", ".")
    max_results = b.get("max_results", SEARCH_DEFAULT_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().search(query, mode=mode, root_dir=root, max_results=max_results)


def handle_search_semantic(body: dict | None = None) -> dict:
    """POST /api/search/semantic — semantic search"""
    b = body or {}
    query = b.get("query", "")
    root = b.get("root", ".")
    pattern = b.get("pattern", "*.py")
    max_results = b.get("max_results", SEARCH_DEFAULT_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().semantic_search(query, root, pattern, max_results)


def handle_search_symbol(body: dict | None = None) -> dict:
    """POST /api/search/symbol — symbol search"""
    b = body or {}
    name = b.get("name", "")
    kind = b.get("kind", "")
    root = b.get("root", ".")
    max_results = b.get("max_results", SYMBOL_SEARCH_RESULTS)
    if not name:
        return {"success": False, "error": "name required"}
    return get_engine().symbol_search(name, kind, root, max_results)


def handle_search_docs(body: dict | None = None) -> dict:
    """POST /api/search/docs — API documentation search"""
    b = body or {}
    query = b.get("query", "")
    max_results = b.get("max_results", DOC_SEARCH_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().doc_search(query, max_results)


def handle_search_index_doc(body: dict | None = None) -> dict:
    """POST /api/search/docs/index — register custom API documentation"""
    b = body or {}
    return get_engine().index_doc(
        package=b.get("package", ""),
        module=b.get("module", ""),
        name=b.get("name", ""),
        signature=b.get("signature", ""),
        docstring=b.get("docstring", ""),
        url=b.get("url", ""),
    )


# ── Route registration ──
# Routes are consolidated in l4/api/api_endpoints.py (ENDPOINT_MANIFEST); no duplicate list maintained here.
