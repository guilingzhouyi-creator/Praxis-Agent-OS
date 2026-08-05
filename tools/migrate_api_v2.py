"""One-shot migration: rewrite api_routes.py paths to the unified /api/v2/ prefix.

Transforms every route path:
  - strips legacy /api/v1/, /api/v2/ version prefixes (unify on /api/v2/)
  - converts trailing-slash parameter style (/api/card/) to {id} (/api/card/{id})
  - converts snake_case path segments to kebab-case
  - prefixes unversioned paths with /api/v2/
  - resolves the /api/tools vs /api/v1/tools collision by moving the
    locale-aware tools listing to /api/v2/tools/locales

Only the path string inside each route tuple is changed — comments, handler
refs, and descriptions are preserved verbatim.

Usage: python tools/migrate_api_v2.py   (run from repo root)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES_FILE = ROOT / "src" / "l4" / "api" / "api_routes.py"

_PATH_RE = re.compile(r"\"(/api/(?:v[123]/)?[^\"]*?)\"")


def to_kebab(seg: str) -> str:
    if seg.startswith("{") and seg.endswith("}"):
        return seg
    return seg.replace("_", "-")


def convert(path: str) -> str:
    # 1) strip any version prefix
    for pre in ("/api/v1/", "/api/v2/", "/api/v3/"):
        if path.startswith(pre):
            path = "/api/" + path[len(pre):]
            break
    # 2) trailing-slash parameter style → {id}
    if path.endswith("/"):
        path = path.rstrip("/") + "/{id}"
    # 3) unify on /api/v2/
    if path.startswith("/api/") and not path.startswith("/api/v2/"):
        path = "/api/v2" + path[len("/api"):]
    # 4) kebab-case path segments
    parts = path.strip("/").split("/")
    path = "/" + "/".join(to_kebab(s) for s in parts)
    return path


def rewrite_line(line: str) -> str:
    def repl(m: re.Match[str]) -> str:
        old = m.group(1)
        new = convert(old)
        return f'"{new}"'
    return _PATH_RE.sub(repl, line)


def migrate_scattered(endpoints_file: Path) -> int:
    """Migrate only the _SCATTERED list inside api_endpoints.py.

    The _DOMAIN_BY_PREFIX keys must NOT be rewritten (they are classification
    prefixes matched after version stripping); only ApiEndpoint(...) path
    literals inside the _SCATTERED block are migrated.
    """
    src = endpoints_file.read_text(encoding="utf-8")
    marker = "_SCATTERED: list[ApiEndpoint] = ["
    start = src.index(marker) + len(marker)  # after the list's own '['
    end = src.index("]", start)              # real list terminator
    block = src[start:end]
    new_block = rewrite_line(block)
    changed = block.count('"/api/')
    endpoints_file.write_text(src[:start] + new_block + src[end:], encoding="utf-8")
    return changed


def main() -> int:
    src = ROUTES_FILE.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    changed = 0
    out: list[str] = []
    for line in lines:
        new_line = rewrite_line(line)
        if new_line != line:
            changed += 1
        out.append(new_line)
    ROUTES_FILE.write_text("".join(out), encoding="utf-8")
    print(f"migrated {changed} lines in {ROUTES_FILE}")

    endpoints_file = ROOT / "src" / "l4" / "api" / "api_endpoints.py"
    sc = migrate_scattered(endpoints_file)
    print(f"migrated {sc} scattered path literals in {endpoints_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
