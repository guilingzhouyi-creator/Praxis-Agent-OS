"""Tests for l3.resource_buffer — RingBuffer stage/commit/discard/diff/status."""

from __future__ import annotations

import os
import tempfile

import pytest


class TestRingBufferBasic:
    """RingBuffer 基础操作 — stage / commit / discard / diff / status"""

    @pytest.fixture(autouse=True)
    def _fresh_buffer(self):
        """每个测试使用独立临时目录，避免互相污染。"""
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as tmpdir:
            self._root = tmpdir
            self.buf = RingBuffer(root=self._root)
            yield
            self.buf.stop()

    def _path(self, name: str = "test.txt") -> str:
        p = os.path.join(self._root, name)
        # 创建文件以便后续 commit 写入
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write("original content\n")
        return p

    # ── stage ──

    def test_stage_returns_success(self):
        """stage 应该返回成功的 dict。"""
        r = self.buf.stage(self._path(), "new content")
        assert r.get("success")
        assert r.get("slot") >= 0
        assert r.get("path").endswith("test.txt")

    def test_stage_multiple_slots(self):
        """多次 stage 应递增 slot 编号。"""
        p = self._path()
        r1 = self.buf.stage(p, "v1")
        r2 = self.buf.stage(p, "v2")
        assert r2["slot"] > r1["slot"]

    def test_stage_different_paths(self):
        """不同路径的 stage 应独立。"""
        p1 = self._path("a.txt")
        p2 = self._path("b.txt")
        r1 = self.buf.stage(p1, "content a")
        r2 = self.buf.stage(p2, "content b")
        assert r1.get("success")
        assert r2.get("success")

    def test_stage_empty_content(self):
        """stage 空内容应被接受。"""
        r = self.buf.stage(self._path(), "")
        assert r.get("success")

    # ── status ──

    def test_status_empty_after_init(self):
        """新 buffer 的 status 应为空。"""
        s = self.buf.status()
        assert isinstance(s, dict)
        assert "total_files" in s or "files" in s
        assert s.get("total_files", 0) == 0 or len(s.get("files", [])) == 0

    def test_status_after_stage(self):
        """stage 后 status 应反映有变更。"""
        self.buf.stage(self._path(), "new content")
        s = self.buf.status()
        assert s.get("total_files", 0) >= 1, f"expected staged files, got: {s}"

    # ── diff ──

    def test_diff_shows_changes(self):
        """diff 应返回原始内容与新内容的差异。"""
        p = self._path()
        # 创建文件
        with open(p, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")
        self.buf.stage(p, "line1\nmodified line2\nline3\n")
        d = self.buf.diff(p)
        assert d.get("success")
        assert "diff" in d
        assert "modified line2" in str(d["diff"])

    def test_diff_no_pending(self):
        """没有 stage 过的路径 diff 应返回错误。"""
        d = self.buf.diff("/nonexistent/path.txt")
        assert not d.get("success")

    # ── commit ──

    def test_commit_writes_file(self):
        """commit 应将 stage 内容写入实际文件。"""
        p = self._path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("old content\n")
        self.buf.stage(p, "new content")
        r = self.buf.commit(p)
        assert r.get("success"), f"commit failed: {r}"
        with open(p, encoding="utf-8") as f:
            assert f.read() == "new content"

    def test_commit_no_stage(self):
        """没有 stage 过的路径 commit 应返回错误。"""
        r = self.buf.commit("/nonexistent/path.txt")
        assert not r.get("success")

    # ── discard ──

    def test_discard_removes_pending(self):
        """discard 应清除 stage 内容，不影响文件。"""
        p = self._path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("original\n")
        self.buf.stage(p, "staged but discarded")
        r = self.buf.discard(p)
        assert r.get("success"), f"discard failed: {r}"
        with open(p, encoding="utf-8") as f:
            assert f.read() == "original\n", "file should be unchanged after discard"

    def test_discard_no_stage(self):
        """discard 未 stage 的路径应不报错（RingBuffer 认为已是空状态）。"""
        r = self.buf.discard("/nonexistent/path.txt")
        # RingBuffer.discard 返回 success=True 即使无变更
        assert isinstance(r, dict)
        assert "success" in r


class TestRingBufferConcurrency:
    """RingBuffer 并发安全测试"""

    def test_concurrent_stage(self):
        """多线程并发 stage 同一文件不应崩溃。"""
        import threading

        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as tmpdir:
            buf = RingBuffer(root=tmpdir)
            p = os.path.join(tmpdir, "concurrent.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("original\n")
            errors = []

            def worker(n):
                try:
                    for i in range(20):
                        buf.stage(p, f"worker {n} version {i}\n")
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"concurrent stage errors: {errors}"

            # commit 后验证文件内容
            r = buf.commit(p)
            assert r.get("success"), f"commit after concurrent stage failed: {r}"
            buf.stop()


class TestRingBufferManager:
    """ResourceBufferManager 高层 API 测试"""

    @pytest.fixture(autouse=True)
    def _fresh_manager(self):
        from l3.resource_buffer.manager import ResourceBufferManager
        self.mgr = ResourceBufferManager()
        # 重置根目录到临时目录
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.mgr._ring = __import__("l3.resource_buffer.ring", fromlist=["RingBuffer"]).RingBuffer(root=self._tmpdir)
        yield
        self.mgr._ring.stop()

    def _path(self, name: str = "test.txt") -> str:
        p = os.path.join(self._tmpdir, name)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write("original\n")
        return p

    def test_manager_stage_and_commit(self):
        """Manager 的 stage → commit 全流程。"""
        r1 = self.mgr.stage(self._path(), "manager content")
        assert r1.get("success")
        r2 = self.mgr.commit(self._path())
        assert r2.get("success")

    def test_manager_status(self):
        """Manager 的 status 返回 dict。"""
        s = self.mgr.status()
        assert isinstance(s, dict)

    def test_manager_diff(self):
        """Manager 的 diff 返回 dict。"""
        p = self._path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("before\n")
        self.mgr.stage(p, "after\n")
        d = self.mgr.diff(p)
        assert d.get("success")

    def test_manager_read(self):
        """Manager 的 read 返回文件内容字符串。"""
        p = self._path()
        with open(p, "w", encoding="utf-8") as f:
            f.write("read test\n")
        content = self.mgr.read(p)
        assert "read test" in content

    def test_manager_singleton(self):
        """get_manager() 返回单例。"""
        from l3.resource_buffer.manager import get_manager, reset_manager
        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2
