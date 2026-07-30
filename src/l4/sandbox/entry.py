"""SandboxEntry — single file change record with structured diff support."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxEntry:
    """Single file change record in the sandbox."""
    path: str
    sandbox_path: str
    agent_id: str
    tool_name: str = ""
    status: str = "pending"
    original_hash: str = ""
    modified_at: float = field(default_factory=float)
    hunks: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"additions": 0, "deletions": 0, "hunks": 0})
    task_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    conflict_level: str = "none"
    _summary_cache: dict | None = None

    def __post_init__(self):
        if not self.modified_at:
            import time
            self.modified_at = time.time()

    def to_serializable(self) -> dict:
        return {"path": self.path, "sandbox_path": self.sandbox_path, "agent_id": self.agent_id,
                "tool_name": self.tool_name, "status": self.status, "original_hash": self.original_hash,
                "modified_at": self.modified_at, "hunks": self.hunks, "stats": self.stats,
                "task_id": self.task_id, "depends_on": self.depends_on, "conflict_level": self.conflict_level}

    @classmethod
    def from_dict(cls, d: dict) -> "SandboxEntry":
        return cls(path=d["path"], sandbox_path=d["sandbox_path"], agent_id=d["agent_id"],
                   tool_name=d.get("tool_name", ""), status=d.get("status", "pending"),
                   original_hash=d.get("original_hash", ""), modified_at=d.get("modified_at", 0.0),
                   hunks=d.get("hunks", []), stats=d.get("stats", {"additions": 0, "deletions": 0, "hunks": 0}),
                   task_id=d.get("task_id", ""), depends_on=d.get("depends_on", []),
                   conflict_level=d.get("conflict_level", "none"))

    def to_human_readable(self) -> dict:
        if not self.hunks:
            return {"success": True, "path": self.path, "diff": "",
                    "summary": f"no changes in {self.path}", "stats": self.stats, "semantic": ""}
        lines, start_line = [], 1
        for h in self.hunks:
            orig_s, orig_e = h.get("original_start", 1), h.get("original_end", 0) or h.get("original_start", 1)
            mod_s, mod_e = h.get("modified_start", 1), h.get("modified_end", 0) or h.get("modified_start", 1)
            oc = orig_e - orig_s + 1 if h["type"] != "insert" else 0
            mc = mod_e - mod_s + 1 if h["type"] != "delete" else 0
            lines.append(f"@@ -{orig_s},{oc} +{mod_s},{mc} @@")
            for l in h.get("context_before", []): lines.append(" " + l.rstrip("\n"))
            for l in h.get("removed_lines", []): lines.append("-" + l.rstrip("\n"))
            for l in h.get("added_lines", []): lines.append("+" + l.rstrip("\n"))
            for l in h.get("context_after", []): lines.append(" " + l.rstrip("\n"))
        semantic = ""
        for h in self.hunks:
            s = h.get("semantic", "")
            if s and s not in ("", "structural"): semantic = s; break
        if not semantic:
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")
        a, d = self.stats.get("additions", 0), self.stats.get("deletions", 0)
        summary = f"+{a}/-{d} in {self.path}" + (f" ({semantic})" if semantic else "")
        return {"success": True, "path": self.path, "diff": "\n".join(lines),
                "summary": summary, "stats": self.stats, "semantic": semantic}

    def to_summary(self) -> dict:
        if self._summary_cache:
            return self._summary_cache
        if not self.hunks:
            result = {"success": True, "path": self.path, "agent_id": self.agent_id,
                      "tool_name": self.tool_name, "task_id": self.task_id, "stats": self.stats,
                      "semantic": "", "ranges": [], "by_type": {}, "modified_at": self.modified_at}
            self._summary_cache = result
            return result
        ranges, by_type, semantic = [], {}, ""
        for h in self.hunks:
            t = h.get("type", "replace"); by_type[t] = by_type.get(t, 0) + 1
            s = h.get("semantic", "")
            if s and s not in ("", "structural"): semantic = s
            start = h.get("original_start", 1) or h.get("modified_start", 1)
            end = (h.get("original_end") or h.get("modified_end") or start)
            ranges.append({"start": start, "end": end})
        if not semantic:
            has_add = any(h["type"] == "insert" for h in self.hunks)
            has_del = any(h["type"] == "delete" for h in self.hunks)
            semantic = "mixed" if (has_add and has_del) else ("added" if has_add else "removed")
        result = {"success": True, "path": self.path, "agent_id": self.agent_id,
                  "tool_name": self.tool_name, "task_id": self.task_id, "stats": self.stats,
                  "semantic": semantic, "ranges": ranges, "by_type": by_type, "modified_at": self.modified_at}
        self._summary_cache = result
        return result

    def to_colored_diff(self, scheme: dict[str, str] | None = None) -> dict:
        _DEFAULT = {"logic_change": "\033[31m", "reformat": "\033[34m", "comment_only": "\033[32m",
                     "import_change": "\033[33m", "rename": "\033[36m", "mixed": "\033[35m",
                     "added": "\033[32m", "removed": "\033[31m"}
        _RESET = "\033[0m"
        cs = dict(_DEFAULT)
        if scheme: cs.update(scheme)
        result = self.to_human_readable()
        if not result.get("diff"): return result
        colored = []
        for line in result["diff"].split("\n"):
            if line.startswith("+"): colored.append(cs.get("added", "\033[32m") + line + _RESET)
            elif line.startswith("-"): colored.append(cs.get("removed", "\033[31m") + line + _RESET)
            elif line.startswith("@@"): colored.append(cs.get("logic_change", "\033[31m") + line + _RESET)
            else: colored.append(line)
        result["diff"] = "\n".join(colored)
        return result
