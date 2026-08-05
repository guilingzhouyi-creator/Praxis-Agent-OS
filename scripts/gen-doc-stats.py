"""Generate architecture-doc statistics from the live codebase.

Run before updating docs/architecture/README.md (the numbers snapshot):

    python scripts/gen-doc-stats.py

Prints the stats table used by README.md. Never hand-edit the numbers —
they drift; regenerate instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def _py_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.py") if "__pycache__" not in str(p))


def _count_lines(path: Path) -> int:
    total = 0
    for p in _py_files(path):
        try:
            total += sum(1 for _ in p.open(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            pass
    return total


def main() -> None:
    sys.path.insert(0, str(SRC))
    routes = 0
    try:
        from l4.api.api_routes import API_ROUTES

        routes = len(API_ROUTES)
    except Exception:
        pass

    layers = {
        "l1/kernel": "L1 Kernel",
        "l2": "L2 Shell",
        "l3": "L3 Cell",
        "l4": "L4 Bridge",
        "l5": "L5 User",
    }
    stats: dict[str, tuple[int, int]] = {}
    for rel, _name in layers.items():
        files = _py_files(SRC / rel)
        stats[rel] = (len(files), _count_lines(SRC / rel))

    sub = {
        "l3/cell/peers/l3a": "L3A (peers)",
        "l3/memory": "L3 Memory",
        "l3/card": "L3 Card",
        "l3/services": "L3 Services",
        "l3/bus": "L3 Bus",
        "l3/agent": "L3 Agent",
        "l4/api_handlers": "L4 Handlers",
    }
    substats: dict[str, tuple[int, int]] = {}
    for rel, _name in sub.items():
        files = _py_files(SRC / rel)
        substats[rel] = (len(files), _count_lines(SRC / rel))

    params = _py_files(SRC / "l1/kernel/params")
    consts = 0
    try:
        import ast

        for p in params:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            consts += sum(1 for n in tree.body
                          if isinstance(n, ast.AnnAssign)
                          and isinstance(n.target, ast.Name)
                          and n.target.id.isupper())
    except Exception:
        pass

    # Endpoint domains (from the manifest classification)
    domains: dict[str, int] = {}
    try:
        from l4.api.api_endpoints import _infer_domain

        for _m, p, _h, _d in API_ROUTES:
            d = _infer_domain(p)
            domains[d] = domains.get(d, 0) + 1
    except Exception:
        pass
    domain_str = ", ".join(f"{d}={n}" for d, n in
                           sorted(domains.items(), key=lambda x: -x[1]))

    print("=" * 62)
    print("Praxis architecture stats (generated - do not hand-edit)")
    print("=" * 62)
    for rel, name in layers.items():
        n, lines = stats[rel]
        print(f"  {name:<14} {n:>4} files  {lines:>7} lines")
    print("  ---")
    for rel, name in sub.items():
        n, lines = substats[rel]
        print(f"  {name:<14} {n:>4} files  {lines:>7} lines")
    print("  ---")
    print(f"  API routes:      {routes}")
    print(f"  Params modules:  {len(params)}")
    print(f"  Params constants:{consts}")
    print(f"  Route domains:   {domain_str}")
    print("=" * 62)


if __name__ == "__main__":
    main()
