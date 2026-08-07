"""FS API tests — tree/read/watch/unwatch over the FilesystemPort adapter."""

from __future__ import annotations

import os

import pytest

from l3.services.fs_adapter import reset_adapter
from l4.api_handlers.api_handlers_fs import (
    handle_fs_read,
    handle_fs_tree,
    handle_fs_unwatch,
    handle_fs_watch,
)


@pytest.fixture(autouse=True)
def _clean_fs():
    reset_adapter()
    yield
    reset_adapter()


class TestFsApi:
    def test_tree(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("x", encoding="utf-8")
        r = handle_fs_tree({"root": str(tmp_path)})
        assert r["success"]
        names = {e["path"] for e in r["entries"]}
        assert "a.txt" in names
        assert "sub" in names  # rglob includes directories
        assert "sub/b.txt" in names
        assert r["count"] == 3

    def test_tree_missing_root(self):
        r = handle_fs_tree({"root": "/nonexistent-tree-root"})
        assert not r["success"]

    def test_read(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("content here", encoding="utf-8")
        r = handle_fs_read({"path": str(p)})
        assert r["success"]
        assert r["content"] == "content here"

    def test_read_requires_path(self):
        r = handle_fs_read({})
        assert not r["success"]
        assert "path required" in r["error"]

    def test_read_missing_file(self):
        r = handle_fs_read({"path": "/nonexistent-read-file"})
        assert not r["success"]

    def test_watch_and_unwatch(self, tmp_path):
        r = handle_fs_watch({"root": str(tmp_path)})
        assert r["success"]
        assert r["watching"] == str(tmp_path)
        r2 = handle_fs_watch({"root": str(tmp_path)})
        assert not r2["success"]  # already watching
        r3 = handle_fs_unwatch({"root": str(tmp_path)})
        assert r3["success"]

    def test_unwatch_not_watching(self, tmp_path):
        r = handle_fs_unwatch({"root": str(tmp_path)})
        assert not r["success"]

    def test_watch_missing_root(self):
        r = handle_fs_watch({"root": "/nonexistent-watch-root"})
        assert not r["success"]

    def test_port_registered(self):
        from l1.kernel.ports import get_port
        from l3.services.fs_adapter import get_adapter

        get_adapter()
        port = get_port("fs")
        port.write("/tmp-unused-praxis-probe.txt", "probe")
        # write may succeed or fail depending on env; the point is the port resolves
        assert port is not None
        from contextlib import suppress

        with suppress(OSError):
            os.remove("/tmp-unused-praxis-probe.txt")
