"""Diff system integration tests — compute_hunks + file_diff_structured + cross-review payload."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestComputeHunksIntegration:
    """compute_hunks — structured diff computation"""

    def test_detects_deletion(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("line1\nline2\n", "line1\n")
        assert len(hunks) >= 1
        assert any(h["type"] == "delete" for h in hunks)

    def test_detects_insertion(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("line1\n", "line1\nline2\nline3\n")
        assert len(hunks) >= 1
        assert any(h["type"] == "insert" for h in hunks)

    def test_detects_modification(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("old line\n", "new line\n")
        assert len(hunks) >= 1
        assert any(h["type"] in ("replace", "insert", "delete") for h in hunks)

    def test_identical_text_returns_empty(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("same\nsame\n", "same\nsame\n")
        assert hunks == []

    def test_hunk_has_all_required_fields(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("a\nb\nc\n", "a\nmodified\nc\n")
        assert len(hunks) >= 1
        h = hunks[0]
        for key in ("type", "original_start", "original_end", "modified_start",
                    "modified_end", "added_lines", "removed_lines",
                    "changes", "semantic"):
            assert key in h, f"Hunk missing field: {key}"

    def test_hunk_char_level_changes(self):
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("old_func(x):\n    return x + 1\n",
                              "new_func(x):\n    return x * 2\n")
        if hunks:
            h = hunks[0]
            assert "changes" in h
            assert "semantic" in h
            assert h["semantic"] in ("rename", "logic_change", "structural", "")


class TestFileDiffStructuredTool:
    """file_diff_structured 工具处理函数"""

    def test_handler_importable(self):
        from l3.tools._files import file_diff_structured
        assert callable(file_diff_structured)

    def test_handler_returns_error_for_missing_path(self):
        from l3.tools._files import file_diff_structured
        r = file_diff_structured({"path": "", "mode": "agent"}, "test-agent")
        assert not r["success"]
        assert "path required" in r["error"]

    def test_handler_returns_error_for_invalid_mode(self):
        from l3.tools._files import file_diff_structured
        r = file_diff_structured({"path": "f.py", "mode": "invalid"}, "test-agent")
        assert not r["success"]
        assert "invalid mode" in r["error"]

    def test_handler_agent_mode_returns_hunks(self):
        from l3.tools._files import file_diff_structured
        # No sandbox entry exists → returns "no staged changes"
        r = file_diff_structured({"path": "nonexistent.py", "mode": "agent"}, "tester")
        assert not r["success"]
        assert "no staged changes" in r["error"]


class TestCrossReviewDiffPayload:
    """cross-review 消息携带结构化 diff 数据"""

    def test_get_sandbox_entries_function_exists(self):
        from l3.cell.components.cell_cross_review import _get_sandbox_entries
        assert callable(_get_sandbox_entries)


class TestSandboxEntryHumanReadable:
    """SandboxEntry.to_human_readable — 从结构化 hunks 重建 diff 文本"""

    def test_human_readable_empty_hunks(self):
        from l4.sandbox.cell_sandbox import SandboxEntry
        e = SandboxEntry(path="f.py", sandbox_path="/tmp/f.py", agent_id="a")
        hr = e.to_human_readable()
        assert hr["success"]
        assert hr["diff"] == ""

    def test_human_readable_with_hunks(self):
        from l4.sandbox.cell_sandbox import SandboxEntry
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("old\n", "new\n")
        e = SandboxEntry(path="f.py", sandbox_path="/tmp/f.py", agent_id="a",
                         hunks=hunks,
                         stats={"additions": 1, "deletions": 1, "hunks": len(hunks)})
        hr = e.to_human_readable()
        assert hr["success"]
        assert len(hr["diff"]) > 0
        assert len(hr["summary"]) > 0

    def test_human_readable_semantic_label_present(self):
        from l4.sandbox.cell_sandbox import SandboxEntry
        from l4.sandbox.sandbox_diff import compute_hunks
        hunks = compute_hunks("old\n", "new\n")
        e = SandboxEntry(path="f.py", sandbox_path="/tmp/f.py", agent_id="a",
                         hunks=hunks,
                         stats={"additions": 1, "deletions": 1, "hunks": len(hunks)})
        hr = e.to_human_readable()
        assert hr["semantic"] is not None


class TestFileChangedSignal:
    """FILE_CHANGED 信号类型定义"""

    def test_file_changed_signal_type_exists(self):
        from l1.kernel.event import SignalType
        assert hasattr(SignalType, "FILE_CHANGED")
        assert SignalType.FILE_CHANGED is not None


class TestApiDiffHandlers:
    """API diff handler 函数的可导入性"""

    def test_diff_structured_handler_importable(self):
        from l4.api.api_handlers_diff import diff_colors, diff_history, diff_structured
        assert callable(diff_structured)
        assert callable(diff_history)
        assert callable(diff_colors)

    def test_diff_structured_gated_off_by_default(self):
        from l4.api.api_handlers_diff import diff_structured
        r = diff_structured({"path": "test.py"})
        assert not r["success"]
        assert "disabled" in r["error"]
