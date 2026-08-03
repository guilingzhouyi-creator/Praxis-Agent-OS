"""FileEditor + TransactionArea 边界场景测试。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestFileEditorBoundary:
    def test_edit_engine_importable(self):
        from l3.services.file_editor import EditEngine
        assert EditEngine is not None

    def test_diff_edit_dataclass(self):
        from l3.services.file_editor import DiffEdit
        e = DiffEdit(path="/tmp/test.py", old_str="old", new_str="new")
        assert e.path == "/tmp/test.py"
        assert e.old_str == "old"

    def test_patch_create_no_crash(self):
        from l3.services.file_editor import Patch
        p = Patch()
        assert p is not None

    def test_empty_edit(self):
        from l3.services.file_editor import DiffEdit, EditEngine
        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("content\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="", new_str="")
            r = engine.diff_edit(edit)
            assert isinstance(r, dict)
        finally:
            os.unlink(tmp)

    def test_simple_replace(self):
        from l3.services.file_editor import DiffEdit, EditEngine
        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def old_func():\n    pass\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="old_func", new_str="new_func")
            r = engine.diff_edit(edit)
            assert isinstance(r, dict)
        finally:
            os.unlink(tmp)

    def test_api_handlers_importable(self):
        from l3.services.file_editor import handle_fs_batch_edit, handle_fs_edit
        assert callable(handle_fs_edit)
        assert callable(handle_fs_batch_edit)


class TestTransactionArea:
    def test_init(self):
        from l3.card.transaction_area import TransactionArea
        ta = TransactionArea(max_queue=10)
        assert ta is not None

    def test_on_start_returns_dict(self):
        from l3.card.transaction_area import TransactionArea
        ta = TransactionArea(max_queue=10)
        r = ta._on_start()
        assert isinstance(r, dict)
