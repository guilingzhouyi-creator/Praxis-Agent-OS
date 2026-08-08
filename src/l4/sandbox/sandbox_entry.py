"""Sandbox entry model + diff color scheme — extracted from cell_sandbox.py.

``SandboxEntry`` is the per-file change record (structured hunks, stats,
serialization, human/colored diff rendering); the color scheme helpers drive
``to_colored_diff``. ``CellSandbox`` (in cell_sandbox.py) stores and manages
these entries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Diff color scheme — customizable via API ──

_DEFAULT_COLOR_SCHEME: dict[str, str] = {
    "logic_change": "\033[31m",  # red
    "reformat": "\033[34m",  # blue
    "comment_only": "\033[32m",  # green
    "import_change": "\033[33m",  # yellow
    "import_added": "\033[33m",  # yellow
    "rename": "\033[36m",  # cyan
    "structural": "\033[90m",  # bright black
    "mixed": "\033[35m",  # magenta
    "added": "\033[32m",  # green
    "removed": "\033[31m",  # red
}
_RESET = "\033[0m"

_COLOR_SCHEME: dict[str, str] = dict(_DEFAULT_COLOR_SCHEME)


def get_color_scheme() -> dict[str, str]:
    """Get current color scheme.

    Precedence (highest first):
      1. Runtime overrides (via API)
      2. YAML config ``diff.colors``
      3. Built-in defaults
    """
    result = dict(_DEFAULT_COLOR_SCHEME)
    try:
        from l3.config.settings_center import get_center

        cfg_colors = get_center().get("diff.colors", {})
        if cfg_colors and isinstance(cfg_colors, dict):
            result.update(cfg_colors)
    except Exception:
        logger.debug("sandbox_entry: diff colors config load failed, using defaults", exc_info=True)
    result.update(_COLOR_SCHEME)  # runtime overrides on top
    return result


def set_color_scheme(scheme: dict[str, str]) -> None:
    """Update color scheme for semantic categories."""
    _COLOR_SCHEME.update(scheme)


def reset_color_scheme() -> None:
    """Reset the sandbox diff color scheme to defaults."""
    _COLOR_SCHEME.clear()
    _COLOR_SCHEME.update(_DEFAULT_COLOR_SCHEME)


@dataclass
class SandboxEntry:
    """Single file change record in the sandbox.

    ``hunks`` is a list of structured diff hunks (line-level).
    Each hunk::

        {"type": "modified",           # "added" | "removed" | "modified"
         "original_start": int, "original_end": int,
         "modified_start": int, "modified_end": int,
         "added_lines": [str], "removed_lines": [str],
         "context_before": [str], "context_after": [str],
         "changes": [                  # character-level (VSCode ICharChange-equivalent)
           {"original_start": {"line":int,"col":int}, "original_end": {"line":int,"col":int},
            "modified_start": {"line":int,"col":int}, "modified_end": {"line":int,"col":int}}
         ],
         "semantic": str}              # e.g. "logic_change: change return x+1 to x*2"
    """

    path: str  # relative path in project
    sandbox_path: str  # absolute path in sandbox
    agent_id: str
    tool_name: str = ""  # tool that created this entry (e.g. "write_file", "replace_string")
    status: str = "pending"  # pending | staged | flushed | discarded
    original_hash: str = ""
    modified_at: float = field(default_factory=time.time)
    # Structured diff (populated by write())
    hunks: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"additions": 0, "deletions": 0, "hunks": 0})
    # HTN task context
    task_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    # Conflict detection
    conflict_level: str = "none"  # "none" | "warn" | "block" | "ping_pong"

    def to_serializable(self) -> dict:
        """Serialize to a JSON-safe dict for _persist_state."""
        return {
            "path": self.path,
            "sandbox_path": self.sandbox_path,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "original_hash": self.original_hash,
            "modified_at": self.modified_at,
            "hunks": self.hunks,
            "stats": self.stats,
            "task_id": self.task_id,
            "depends_on": self.depends_on,
            "conflict_level": self.conflict_level,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SandboxEntry:
        """Restore from a serialized dict (for _restore_state)."""
        return cls(
            path=d["path"],
            sandbox_path=d["sandbox_path"],
            agent_id=d["agent_id"],
            tool_name=d.get("tool_name", ""),
            status=d.get("status", "pending"),
            original_hash=d.get("original_hash", ""),
            modified_at=d.get("modified_at", 0.0),
            hunks=d.get("hunks", []),
            stats=d.get("stats", {"additions": 0, "deletions": 0, "hunks": 0}),
            task_id=d.get("task_id", ""),
            depends_on=d.get("depends_on", []),
            conflict_level=d.get("conflict_level", "none"),
        )

    def to_human_readable(self) -> dict:
        """Reconstruct unified-diff text + summary from structured hunks.

        Returns::

            {"success": True,
             "path": self.path,
             "diff": "@@ -1,3 +1,4 @@...",     # unified diff text
             "summary": "+2/-1 in foo.py",
             "stats": {"additions": 2, "deletions": 1, "hunks": 1},
             "semantic": "logic_change"}
        """
        if not self.hunks:
            return {
                "success": True,
                "path": self.path,
                "diff": "",
                "summary": f"no changes in {self.path}",
                "stats": self.stats,
                "semantic": "",
            }

        lines: list[str] = []

        for h in self.hunks:
            orig_start = h.get("original_start", 1)
            orig_end = h.get("original_end", 0) or orig_start
            mod_start = h.get("modified_start", 1)
            mod_end = h.get("modified_end", 0) or mod_start
            orig_count = orig_end - orig_start + 1 if h["type"] != "insert" else 0
            mod_count = mod_end - mod_start + 1 if h["type"] != "delete" else 0

            lines.append(f"@@ -{orig_start},{orig_count} +{mod_start},{mod_count} @@")

            ctx_lines = [(" " + ln.rstrip("\n")) for ln in h.get("context_before", [])]
            for cl in ctx_lines:
                lines.append(cl)

            for ln in h.get("removed_lines", []):
                lines.append("-" + ln.rstrip("\n"))
            for ln in h.get("added_lines", []):
                lines.append("+" + ln.rstrip("\n"))

            ctx_after = [(" " + ln.rstrip("\n")) for ln in h.get("context_after", [])]
            for cl in ctx_after:
                lines.append(cl)

        diff_text = "\n".join(lines)

        # Pick a semantic label — prefer the most meaningful
        semantic = ""
        for h in self.hunks:
            s = h.get("semantic", "")
            if s and s not in ("", "structural"):
                semantic = s
                break
        if not semantic:
            for h in self.hunks:
                s = h.get("semantic", "")
                if s:
                    semantic = s
                    break
        if not semantic:
            # Fallback: derive from hunk types
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")

        a = self.stats.get("additions", 0)
        d = self.stats.get("deletions", 0)
        summary = f"+{a}/-{d} in {self.path}"
        if semantic:
            summary += f" ({semantic})"

        return {
            "success": True,
            "path": self.path,
            "diff": diff_text,
            "summary": summary,
            "stats": self.stats,
            "semantic": semantic,
        }

    _summary_cache: dict | None = None

    def to_summary(self) -> dict:
        """Lightweight structured summary, cached on first call.

        Returns::

            {"success": True,
             "path": self.path,
             "agent_id": self.agent_id,
             "tool_name": self.tool_name,
             "task_id": self.task_id,
             "stats": {"additions": N, "deletions": N, "hunks": N},
             "semantic": "logic_change",
             "ranges": [{"start": 10, "end": 15}, ...],
             "by_type": {"replace": 2, "insert": 0, "delete": 1},
             "modified_at": self.modified_at}
        """
        if self._summary_cache is not None:
            return self._summary_cache

        if not self.hunks:
            result = {
                "success": True,
                "path": self.path,
                "agent_id": self.agent_id,
                "tool_name": self.tool_name,
                "task_id": self.task_id,
                "stats": self.stats,
                "semantic": "",
                "ranges": [],
                "by_type": {},
                "modified_at": self.modified_at,
            }
            self._summary_cache = result
            return result

        ranges: list[dict[str, int]] = []
        by_type: dict[str, int] = {}
        semantic = ""

        for h in self.hunks:
            t = h.get("type", "replace")
            by_type[t] = by_type.get(t, 0) + 1
            start = h.get("original_start", 1) or h.get("modified_start", 1)
            end = h.get("original_end") or h.get("modified_end") or start
            ranges.append({"start": start, "end": end})
            s = h.get("semantic", "")
            if s and s not in ("", "structural"):
                semantic = s

        if not semantic:
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")

        result = {
            "success": True,
            "path": self.path,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "task_id": self.task_id,
            "stats": self.stats,
            "semantic": semantic,
            "ranges": ranges,
            "by_type": by_type,
            "modified_at": self.modified_at,
        }
        self._summary_cache = result
        return result

    def to_colored_diff(self, scheme: dict[str, str] | None = None) -> dict:
        """Unified diff text with ANSI color codes applied per semantic type.

        Args:
            scheme: Optional override color scheme.
                    Falls back to module-level ``_COLOR_SCHEME``.

        Returns::

            {"success": True, "path": "...", "diff": "...",
             "stats": {...}, "semantic": "..."}
        """
        if scheme is None:
            scheme = _COLOR_SCHEME
        hr = self.to_human_readable()
        if not hr.get("success") or not hr.get("diff"):
            return hr
        s = hr["semantic"]
        color = scheme.get(s, "")
        colored_lines: list[str] = []
        for line in hr["diff"].split("\n"):
            if line.startswith("+") or line.startswith("-"):
                colored_lines.append(f"{color}{line}{_RESET}")
            else:
                colored_lines.append(line)
        hr["diff"] = "\n".join(colored_lines)
        hr["colored"] = True
        return hr
