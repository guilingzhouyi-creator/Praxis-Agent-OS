"""Search service — global text search and replace.

Uses concurrent grep for performance on large codebases.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.params.system import SEARCH_EXCLUDE_DIRS, SEARCH_EXCLUDE_EXTS, SEARCH_MAX_RESULTS


def search(root: str, query: str, include: list[str] | None = None,
           exclude: list[str] | None = None, max_results: int = SEARCH_MAX_RESULTS) -> dict[str, Any]:
    """Search for query in root directory.

    Args:
        root: Search root path
        query: Text to search (plain text or regex)
        include: Glob patterns to include (e.g. ["*.py", "*.js"])
        exclude: Glob patterns to exclude
        max_results: Maximum matches to return
    """
    try:
        p = Path(root).resolve()
        if not p.is_dir():
            return {"success": False, "error": "directory not found"}

        results: list[dict] = []
        files_to_search: list[Path] = []

        # Use os.walk (lazy generator) instead of rglob for memory efficiency
        for dirpath, dirnames, filenames in os.walk(p):
            # Skip excluded directories (modify dirnames in-place to prune the walk)
            rel = os.path.relpath(dirpath, p)
            if rel != ".":
                parts = Path(rel).parts
                if any(part in SEARCH_EXCLUDE_DIRS for part in parts):
                    dirnames.clear()
                    continue
            for filename in filenames:
                fp = Path(dirpath) / filename
                if fp.suffix in SEARCH_EXCLUDE_EXTS:
                    continue
                if include and not any(fp.match(pat) for pat in include):
                    continue
                if exclude and any(fp.match(pat) for pat in exclude):
                    continue
                files_to_search.append(fp)

        # Parallel search
        compiled = re.compile(query, re.IGNORECASE)

        def _search_file(fp: Path) -> list[dict]:
            try:
                text = fp.read_text("utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                return []
            matches: list[dict] = []
            for lineno, line in enumerate(text.splitlines(), 1):
                for m in compiled.finditer(line):
                    matches.append({
                        "path": str(fp),
                        "line": lineno,
                        "column": m.start() + 1,
                        "content": line.strip(),
                        "match": m.group(),
                    })
                    if len(matches) > 20:
                        return matches
            return matches

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_search_file, f): f for f in files_to_search}
            for future in as_completed(futures):
                for match in future.result():
                    results.append(match)
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break

        return {"success": True, "results": results, "count": len(results), "files_searched": len(files_to_search)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def replace(root: str, query: str, replacement: str,
            include: list[str] | None = None) -> dict[str, Any]:
    """Find and replace text across files."""
    try:
        r = search(root, query, include=include)
        if not r["success"]:
            return r

        changed_files: set[str] = set()
        replaced_count = 0
        compiled = re.compile(query, re.IGNORECASE)

        # Group results by file
        by_file: dict[str, list[dict]] = {}
        for match in r["results"]:
            by_file.setdefault(match["path"], []).append(match)

        for fp, matches in by_file.items():
            try:
                text = Path(fp).read_text("utf-8", errors="replace")
                new_text, n = compiled.subn(replacement, text)
                if n > 0:
                    Path(fp).write_text(new_text, encoding="utf-8")
                    replaced_count += n
                    changed_files.add(fp)
            except (OSError, UnicodeDecodeError):
                continue

        return {"success": True, "replaced": replaced_count, "files_changed": list(changed_files), "file_count": len(changed_files)}
    except Exception as e:
        return {"success": False, "error": str(e)}
