"""Code auto-format engine tests — detect / format_file / format_project / auto hook."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pathlib import Path


def _skip_if_no_formatter() -> None:
    """Skip the test when no configured formatter binary is on PATH."""
    import shutil

    from l1.kernel.params.tool import FORMAT_DETECTORS

    if not any(shutil.which(det[0]) for det in FORMAT_DETECTORS):
        import pytest

        pytest.skip("no formatter binary available (ruff/black/autopep8)")


class TestDetectFormatter:
    """Extension → formatter mapping."""

    def test_python_extension(self):
        from l3.services.code_format import detect_formatter

        assert detect_formatter("foo.py") == "ruff"
        assert detect_formatter("foo.pyi") == "ruff"

    def test_unknown_extension(self):
        from l3.services.code_format import detect_formatter

        assert detect_formatter("foo.txt") == ""
        assert detect_formatter("no_ext") == ""


class TestFormatFile:
    """Single-file formatting."""

    def test_format_file_happy_path(self):
        _skip_if_no_formatter()
        from l3.services.code_format import format_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def f( ):return 1\n")
            tmp = f.name
        try:
            r = format_file(tmp)
            assert r["success"], f"format_file failed: {r}"
            assert r.get("tool") in ("ruff", "black", "autopep8")
            content = Path(tmp).read_text(encoding="utf-8")
            assert "return 1" in content
        finally:
            os.unlink(tmp)

    def test_format_file_graceful_degradation(self, monkeypatch):
        from l3.services.code_format import format_file

        monkeypatch.setattr("l3.services.code_format.shutil.which", lambda name: None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("x = 1\n")
            tmp = f.name
        try:
            r = format_file(tmp)
            assert not r["success"]
            assert "unavailable" in r.get("error", "")
        finally:
            os.unlink(tmp)

    def test_format_file_missing_path(self):
        from l3.services.code_format import format_file

        r = format_file("/tmp/nonexistent_file_xyz_123.py")
        assert not r["success"]
        assert "not found" in r.get("error", "")

    def test_format_file_unsupported_extension(self):
        _skip_if_no_formatter()
        from l3.services.code_format import format_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("plain text\n")
            tmp = f.name
        try:
            r = format_file(tmp)
            assert not r["success"]
            assert "unavailable" in r.get("error", "")
        finally:
            os.unlink(tmp)


class TestFormatProject:
    """Batch directory formatting."""

    def test_format_project_counts(self, tmp_path):
        from l3.services.code_format import format_project

        (tmp_path / "a.py").write_text("def a( ):return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def b( ):return 2\n", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("not code\n", encoding="utf-8")
        r = format_project(str(tmp_path))
        assert r["success"]
        assert r["total"] == 2  # only .py files counted; .txt ignored

    def test_format_project_ignores_dirs(self, tmp_path):
        from l3.services.code_format import format_project

        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("y = 2\n", encoding="utf-8")
        r = format_project(str(tmp_path))
        assert r["total"] == 1
        assert all("lib.py" not in res.get("path", "") for res in r["results"])

    def test_format_project_respects_max_files(self, tmp_path, monkeypatch):
        from l3.services.code_format import format_project

        monkeypatch.setattr("l3.services.code_format.FORMAT_MAX_FILES", 2)
        for i in range(5):
            (tmp_path / f"m{i}.py").write_text(f"def m{i}( ):return {i}\n", encoding="utf-8")
        r = format_project(str(tmp_path))
        assert r["total"] == 2

    def test_format_project_missing_dir(self):
        from l3.services.code_format import format_project

        r = format_project("/tmp/nonexistent_dir_xyz_123")
        assert not r["success"]
        assert "not found" in r.get("error", "")


class TestAutoFormatHook:
    """Post-execute hook semantics."""

    def test_trigger_on_create_file(self, monkeypatch):
        from l3.services.code_format import auto_format_hook

        monkeypatch.setattr(
            "l3.services.code_format.format_file",
            lambda path, tool="": {"success": True, "tool": "ruff", "changed": True, "path": path},
        )
        result = {"success": True, "path": "/tmp/x.py"}
        out = auto_format_hook("create_file", "agent1", {"path": "/tmp/x.py"}, result)
        assert out["formatted"]["tool"] == "ruff"
        assert out["formatted"]["changed"] is True

    def test_no_trigger_on_non_write_tool(self):
        from l3.services.code_format import auto_format_hook

        result = {"success": True}
        out = auto_format_hook("file_move", "agent1", {"path": "/tmp/x.py"}, result)
        assert "formatted" not in out

    def test_no_trigger_on_failure(self):
        from l3.services.code_format import auto_format_hook

        result = {"success": False, "error": "boom"}
        out = auto_format_hook("create_file", "agent1", {"path": "/tmp/x.py"}, result)
        assert "formatted" not in out

    def test_no_trigger_on_non_python(self):
        from l3.services.code_format import auto_format_hook

        result = {"success": True}
        out = auto_format_hook("create_file", "agent1", {"path": "/tmp/x.md"}, result)
        assert "formatted" not in out

    def test_gated_by_config(self, monkeypatch):
        from l3.services.code_format import auto_format_hook

        monkeypatch.setattr("l1.kernel.discovery.get_tool_config", lambda key, default: False)
        result = {"success": True}
        out = auto_format_hook("create_file", "agent1", {"path": "/tmp/x.py"}, result)
        assert "formatted" not in out


class TestLayerHygiene:
    """Module-level import constraints."""

    def test_code_format_no_l4_module_import(self):
        src = Path(__file__).parents[3] / "src" / "l3" / "services" / "code_format.py"
        text = src.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                assert "l4." not in stripped, f"module-level L4 import in code_format.py: {line}"

    def test_tool_handler_is_thin(self):
        src = Path(__file__).parents[3] / "src" / "l3" / "tools" / "_format.py"
        text = src.read_text(encoding="utf-8")
        assert "l3.services.code_format" in text
