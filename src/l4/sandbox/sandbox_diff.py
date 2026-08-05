"""Sandbox diff engine — stateless hunk computation + conflict detection.

Extracted from cell_sandbox.py (P2 split): ``compute_hunks`` and
``check_conflict`` are pure functions with no CellSandbox instance state;
``classify_hunk_semantic`` is the shared hunk-labeling heuristic.
"""

from __future__ import annotations

import difflib
import logging
import time
from typing import Any

from l1.kernel.params.system import (
    DIFF_CHAR_LEVEL_MAX_LINES,
    DIFF_CONTEXT_LINES,
    DIFF_PINGPONG_WINDOW_SECONDS,
    SANDBOX_DEFAULT_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Seconds to detect ping-pong file flipping between agents.
_PING_PONG_TIMEOUT = int(SANDBOX_DEFAULT_TIMEOUT)


def classify_hunk_semantic(hunk: dict) -> str:
    """Heuristic semantic classification for a diff hunk.

    Returns a short label: ``"logic_change"``, ``"reformat"``,
    ``"rename"``, ``"comment_only"``, or ``"mixed"``.
    """
    added = "".join(hunk.get("added_lines", [])).strip()
    removed = "".join(hunk.get("removed_lines", [])).strip()
    if not added or not removed:
        return "structural"

    # Comment-only changes
    all_lines = (added + "\n" + removed).splitlines()
    if all(l.strip().startswith(("#", "//", "/*", "*", "<!--")) for l in all_lines if l.strip()):
        return "comment_only"

    # Reformat (only whitespace/indentation differences)
    if added.replace(" ", "").replace("\t", "") == removed.replace(" ", "").replace("\t", ""):
        return "reformat"

    # Rename detection
    if "def " in added and "def " in removed:
        return "rename"
    if "class " in added and "class " in removed:
        return "rename"

    # Import change
    if "import " in added or "from " in added:
        if "import " in removed or "from " in removed:
            return "import_change"
        return "import_added"

    return "logic_change"


def compute_hunks(old_text: str, new_text: str,
                  agent_id: str = "", tool_name: str = "",
                  timestamp: float = 0.0) -> list[dict]:
    """Compute structured diff hunks from old/new text.

    Returns a list of hunk dicts::

        {"type": "modified"|"added"|"removed",
         "original_start": int, "original_end": int,
         "modified_start": int, "modified_end": int,
         "added_lines": [str], "removed_lines": [str],
         "context_before": [str], "context_after": [str],
         "changes": [  (VSCode ICharChange-equivalent per modified line)
             {"original_start": {"line":int,"col":int},
              "original_end":   {"line":int,"col":int},
              "modified_start": {"line":int,"col":int},
              "modified_end":   {"line":int,"col":int}}
         ],
         "semantic": str}
    """
    if old_text == new_text:
        return []

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    hunks: list[dict] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue

        hunk: dict[str, Any] = {
            "type": op,  # "replace" | "delete" | "insert"
            "original_start": i1 + 1,  # 1-based
            "original_end": i2 if op != "insert" else 0,
            "modified_start": j1 + 1,
            "modified_end": j2 if op != "delete" else 0,
            "added_lines": new_lines[j1:j2],
            "removed_lines": old_lines[i1:i2],
            "context_before": [],
            "context_after": [],
            "changes": [],
            "semantic": "",
            "agent_id": agent_id,
            "tool_name": tool_name,
            "timestamp": timestamp,
        }

        # Context lines (up to DIFF_CONTEXT_LINES before/after)
        ctx_before = max(0, i1 - DIFF_CONTEXT_LINES)
        hunk["context_before"] = [l.rstrip("\n") for l in old_lines[ctx_before:i1]]
        ctx_after = min(len(old_lines), i2 + DIFF_CONTEXT_LINES)
        hunk["context_after"] = [l.rstrip("\n") for l in old_lines[i2:ctx_after]]

        # Character-level changes for replace hunks (VSCode ICharChange style)
        if op == "replace" and (i2 - i1) <= DIFF_CHAR_LEVEL_MAX_LINES and (j2 - j1) <= DIFF_CHAR_LEVEL_MAX_LINES:
            removed_text = "".join(old_lines[i1:i2])
            added_text = "".join(new_lines[j1:j2])
            char_matcher = difflib.SequenceMatcher(None, removed_text, added_text)
            for cop, ci1, ci2, cj1, cj2 in char_matcher.get_opcodes():
                if cop == "equal":
                    continue
                # Map character offsets back to (line, col) positions
                rem_before = removed_text[:ci1]
                add_before = added_text[:cj1]
                rem_col = len(rem_before.rsplit("\n")[-1]) + 1
                add_col = len(add_before.rsplit("\n")[-1]) + 1
                rem_line = hunk["original_start"] + rem_before.count("\n")
                add_line = hunk["modified_start"] + add_before.count("\n")
                removed_chars = removed_text[ci1:ci2]
                added_chars = added_text[cj1:cj2]
                hunk["changes"].append({
                    "original_start": {"line": rem_line, "col": rem_col},
                    "original_end": {"line": rem_line + removed_chars.count("\n"),
                                     "col": rem_col + len(removed_chars.rsplit("\n")[-1])},
                    "modified_start": {"line": add_line, "col": add_col},
                    "modified_end": {"line": add_line + added_chars.count("\n"),
                                     "col": add_col + len(added_chars.rsplit("\n")[-1])},
                })

        hunks.append(hunk)

    # Collapse adjacent same-type hunks for readability
    if hunks:
        collapsed = [hunks[0]]
        for h in hunks[1:]:
            prev = collapsed[-1]
            if (h["type"] == prev["type"]
                    and h["original_start"] <= prev["original_end"] + 2
                    and h["modified_start"] <= prev["modified_end"] + 2):
                prev["original_end"] = h["original_end"]
                prev["modified_end"] = h["modified_end"]
                prev["added_lines"].extend(h["added_lines"])
                prev["removed_lines"].extend(h["removed_lines"])
                prev["context_after"] = h["context_after"]
                prev["changes"].extend(h["changes"])
            else:
                collapsed.append(h)
        hunks = collapsed

    # Add semantic labels via heuristics
    for h in hunks:
        h["semantic"] = classify_hunk_semantic(h)

    return hunks


def check_conflict(rel_path: str, agent_id: str,
                   path_index: dict[str, list[str]],
                   entries: dict) -> str:
    """Check if another agent has pending/staged changes to the same file.

    Uses ``path_index`` for O(1) lookup instead of O(N) scan.
    Returns: "none" | "warn" | "block" | "ping_pong"
    """
    other = None
    for key in path_index.get(rel_path, []):
        entry = entries.get(key)
        if entry and entry.agent_id != agent_id:
            other = entry
            break
    if not other:
        return "none"
    if other.agent_id == agent_id:
        # Same agent modifying again — only warn if rapid cycle
        age = time.time() - other.modified_at
        if age < DIFF_PINGPONG_WINDOW_SECONDS and other.status in ("pending", "staged"):
            return "warn"
        return "none"
    # Different agent
    if other.status in ("pending", "staged"):
        # Check for ping-pong: same file flipped back-and-forth
        age = time.time() - other.modified_at
        if age < _PING_PONG_TIMEOUT:
            return "block"
        return "warn"
    return "none"
