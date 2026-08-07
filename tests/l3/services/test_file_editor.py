"""File Editor integration test — Diff edit + atomic batch + Patch system + Undo/Redo + API endpoints"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pathlib import Path


class TestDiffEdit:
    """Diff semantic editing core functionality"""

    def test_simple_replace(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def old_function():\n    pass\n")
            tmp = f.name

        try:
            edit = DiffEdit(path=tmp, old_str="old_function", new_str="new_function")
            r = engine.diff_edit(edit)
            assert r["success"], f"diff_edit failed: {r}"
            content = Path(tmp).read_text(encoding="utf-8")
            assert "new_function" in content
            assert "old_function" not in content
        finally:
            os.unlink(tmp)

    def test_replace_not_found(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("existing content\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="nonexistent_string_xyz", new_str="")
            r = engine.diff_edit(edit)
            assert not r["success"]
            assert "not found" in r.get("error", "")
        finally:
            os.unlink(tmp)

    def test_file_not_found(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        edit = DiffEdit(path="/tmp/nonexistent_file_xyz.txt", old_str="a", new_str="b")
        r = engine.diff_edit(edit)
        assert not r["success"]

    def test_case_sensitive(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("Hello World\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="hello", new_str="Hi", case_sensitive=True)
            r = engine.diff_edit(edit)
            assert not r["success"], "case_sensitive should fail"
        finally:
            os.unlink(tmp)

    def test_case_insensitive(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("Hello World\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="hello", new_str="Hi", case_sensitive=False)
            r = engine.diff_edit(edit)
            assert r["success"]
            content = Path(tmp).read_text(encoding="utf-8")
            assert "Hi World" in content
        finally:
            os.unlink(tmp)


class TestBatchEdit:
    """Atomic batch editing"""

    def test_batch_success(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        files = []
        for i in range(3):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(f"file_{i}\n")
            files.append(f.name)

        try:
            edits = [
                DiffEdit(path=files[0], old_str="file_0", new_str="modified_0"),
                DiffEdit(path=files[1], old_str="file_1", new_str="modified_1"),
            ]
            r = engine.batch_edit(edits, description="batch test")
            assert r["success"], f"batch failed: {r}"
            assert r["files"] == 2

            c0 = Path(files[0]).read_text(encoding="utf-8")
            c1 = Path(files[1]).read_text(encoding="utf-8")
            assert "modified_0" in c0
            assert "modified_1" in c1
        finally:
            for p in files:
                os.unlink(p)

    def test_batch_rollback(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f1:
            f1.write("file_one\n")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f2:
            f2.write("file_two\n")

        try:
            edits = [
                DiffEdit(path=f1.name, old_str="file_one", new_str="changed"),
                DiffEdit(path=f2.name, old_str="NONEXISTENT", new_str="wont_work"),
            ]
            r = engine.batch_edit(edits, description="rollback test")
            assert not r["success"]
            # Verify both files were rolled back
            c1 = Path(f1.name).read_text(encoding="utf-8")
            assert "file_one" in c1, "file_one should be rolled back"
        finally:
            os.unlink(f1.name)
            os.unlink(f2.name)


class TestUndoRedo:
    """Undo / Redo"""

    def test_undo_redo(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("original\n")
            tmp = f.name
        try:
            # Edit
            edit = DiffEdit(path=tmp, old_str="original", new_str="modified")
            r = engine.diff_edit(edit)
            assert r["success"]
            assert Path(tmp).read_text(encoding="utf-8").strip() == "modified"

            # Undo
            r2 = engine.undo()
            assert r2["success"], f"undo failed: {r2}"
            assert Path(tmp).read_text(encoding="utf-8").strip() == "original"

            # Redo
            r3 = engine.redo()
            assert r3["success"], f"redo failed: {r3}"
            assert Path(tmp).read_text(encoding="utf-8").strip() == "modified"
        finally:
            os.unlink(tmp)

    def test_undo_nothing(self):
        from l3.services.file_editor import EditEngine

        engine = EditEngine()
        r = engine.undo()
        assert not r["success"]
        assert "nothing to undo" in r.get("error", "")

    def test_redo_nothing(self):
        from l3.services.file_editor import EditEngine

        engine = EditEngine()
        r = engine.redo()
        assert not r["success"]
        assert "nothing to redo" in r.get("error", "")

    def test_history(self):
        from l3.services.file_editor import DiffEdit, EditEngine

        engine = EditEngine()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("v1\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="v1", new_str="v2")
            engine.diff_edit(edit)
            h = engine.history()
            assert h["success"]
            assert h["count"] >= 1
        finally:
            os.unlink(tmp)


class TestPatchSystem:
    """Patch create/apply/rollback"""

    def test_patch_create_and_apply(self):
        from l3.services.file_editor import DiffEdit, EditEngine, PatchManager

        engine = EditEngine()
        mgr = PatchManager(engine)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("original\n")
            tmp = f.name
        try:
            edit = DiffEdit(path=tmp, old_str="original", new_str="patched")
            r = engine.diff_edit(edit)
            op_id = r["operation_id"]

            # Create patch
            pr = mgr.create_from_history(op_id, description="test patch")
            assert pr["success"]
            patch = pr["patch"]
            assert patch["description"] == "test patch"
            assert not patch["applied"]

            # Verify applied via history check
            h = engine.history()
            assert h["count"] >= 1
        finally:
            os.unlink(tmp)

    def test_patch_list(self):
        from l3.services.file_editor import EditEngine, PatchManager

        engine = EditEngine()
        mgr = PatchManager(engine)
        pr = mgr.list_patches()
        assert pr["success"]
        assert isinstance(pr["patches"], list)


class TestApiHandlers:
    """API Handler function-level test"""

    def test_handle_fs_edit_basic(self):
        from l3.services.file_editor import handle_fs_edit

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("api_content\n")
            tmp = f.name
        try:
            r = handle_fs_edit({"path": tmp, "old_str": "api_content", "new_str": "api_modified"})
            assert r["success"], f"api edit failed: {r}"
            assert r["path"] == tmp
        finally:
            os.unlink(tmp)

    def test_handle_fs_edit_missing_field(self):
        from l3.services.file_editor import handle_fs_edit

        r = handle_fs_edit({"path": ""})
        assert not r["success"]

    def test_handle_fs_history(self):
        from l3.services.file_editor import handle_fs_history

        r = handle_fs_history({"limit": 5})
        assert r["success"]

    def test_handle_fs_undo_redo(self):
        from l3.services.file_editor import get_engine, handle_fs_redo, handle_fs_undo

        # Ensure clean state
        eng = get_engine()
        while eng._history:
            eng._history.pop()

        r1 = handle_fs_undo({})
        assert not r1["success"]  # nothing to undo
        r2 = handle_fs_redo({})
        assert not r2["success"]  # nothing to redo
