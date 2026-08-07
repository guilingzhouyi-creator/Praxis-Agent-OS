#!/usr/bin/env python3
"""Atomic contract version bump for Praxis.

Per AGENTS.md "Contract versioning": version bumps are atomic — pyproject.toml
version + AGENTS.md header + docs/ SOC references must change in one commit.
This script performs that three-way update in one pass.

Usage:
    python scripts/bump-version.py 0.4.2           # bump to 0.4.2
    python scripts/bump-version.py 0.4.2 --dry-run # show changes, write nothing

The new version must be a plain X.Y.Z semantic version (patch for contract-safe
additions, minor for API/behavior changes — see AGENTS.md).

Exit codes:
    0 — applied (or dry-run preview)
    1 — validation/IO error
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files updated by the atomic bump.
PYPROJECT = ROOT / "pyproject.toml"
AGENTS = ROOT / "AGENTS.md"
DOCS = ROOT / "docs"

# SOC header lines in docs carry the project version. Pattern tolerates both
# `**项目版本:**` and `**项目版本**:` spellings seen in the tree.
DOC_VERSION_RE = re.compile(
    r"^(\s*>\s*\*\*项目版本(?:[:：]?\*\*|\*\*[:：]?)\s*)v(\d+\.\d+\.\d+)",
    re.MULTILINE,
)
AGENTS_VERSION_RE = re.compile(r"^(# Praxis — Agent OS \(v)\d+\.\d+\.\d+", re.MULTILINE)
PYPROJECT_VERSION_RE = re.compile(r'^(version = ")\d+\.\d+\.\d+(")', re.MULTILINE)


def current_version() -> str:
    """Read the current version from pyproject.toml."""
    m = PYPROJECT_VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError("cannot find version in pyproject.toml")
    return m.group(0).split('"')[1]


def bump(version: str, dry_run: bool) -> list[str]:
    """Apply the atomic bump, returning a list of change descriptions."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"invalid version '{version}' — expected X.Y.Z")

    old = current_version()
    if old == version:
        raise ValueError(f"version is already {version}")

    changes: list[str] = []

    # 1. pyproject.toml
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = PYPROJECT_VERSION_RE.subn(rf'\g<1>{version}\g<2>', text)
    if n != 1:
        raise RuntimeError("unexpected pyproject.toml version match count")
    if not dry_run:
        PYPROJECT.write_text(new_text, encoding="utf-8")
    changes.append(f"pyproject.toml: version {old} -> {version}")

    # 2. AGENTS.md header
    text = AGENTS.read_text(encoding="utf-8")
    new_text, n = AGENTS_VERSION_RE.subn(rf"\g<1>{version}", text)
    if n != 1:
        raise RuntimeError("unexpected AGENTS.md version match count")
    if not dry_run:
        AGENTS.write_text(new_text, encoding="utf-8")
    changes.append(f"AGENTS.md: header v{old} -> v{version}")

    # 3. docs/ SOC references (all *.md under docs/)
    hit = 0
    for path in sorted(DOCS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        new_text, n = DOC_VERSION_RE.subn(rf"\g<1>v{version}", text)
        if n:
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")
            changes.append(f"{path.relative_to(ROOT)}: SOC version -> v{version}")
            hit += n
    if hit == 0:
        changes.append("docs/: (no SOC version references found)")

    return changes


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    if len(args) != 1:
        print(__doc__)
        return 1
    try:
        changes = bump(args[0], dry_run)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    mode = "DRY-RUN (nothing written)" if dry_run else "applied"
    print(f"[bump-version] {mode}")
    for line in changes:
        print(f"  - {line}")
    if not dry_run:
        print("[bump-version] commit these together (atomic per AGENTS.md):")
        print("  git add pyproject.toml AGENTS.md docs/ && git commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
