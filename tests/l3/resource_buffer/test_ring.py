"""Resource buffer core — RingBuffer, ResourceBufferManager tests."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestRingBuffer:
    """RingBuffer — staged file modification buffer."""

    def test_stage_and_commit(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            fpath = os.path.join(td, "test.txt")
            r = buf.stage(fpath, "hello world", op="edit")
            assert r["success"]
            r2 = buf.commit(fpath)
            assert r2["success"]
            assert os.path.exists(fpath)
            with open(fpath, encoding="utf-8") as f:
                assert f.read() == "hello world"

    def test_discard(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            fpath = os.path.join(td, "discard.txt")
            buf.stage(fpath, "will be discarded", op="edit")
            r = buf.discard(fpath)
            assert r["success"]
            assert not os.path.exists(fpath)

    def test_read_staged(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            fpath = os.path.join(td, "readme.txt")
            buf.stage(fpath, "staged content", op="edit")
            content = buf.read(fpath)
            assert "staged content" in content

    def test_status_empty(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            st = buf.status()
            assert "success" in st
            assert st["total_files"] == 0

    def test_diff(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            fpath = os.path.join(td, "diff_test.txt")
            buf.stage(fpath, "diff content", op="edit")
            r = buf.diff(fpath)
            assert "success" in r

    def test_recover(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            fpath = os.path.join(td, "recover.txt")
            buf.stage(fpath, "recover me", op="edit")
            r = buf.recover()
            assert isinstance(r, dict)

    def test_stop(self):
        from l3.resource_buffer.ring import RingBuffer
        with tempfile.TemporaryDirectory() as td:
            buf = RingBuffer(root=td)
            buf.stop()  # should not raise


class TestResourceBufferManager:
    """ResourceBufferManager — higher-level buffer access."""

    def test_get_manager_singleton(self):
        from l3.resource_buffer.manager import get_manager, reset_manager
        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_stage_and_commit(self):
        from l3.resource_buffer.manager import get_manager, reset_manager
        reset_manager()
        with tempfile.TemporaryDirectory() as td:
            m = get_manager()
            fpath = os.path.join(td, "manager_test.txt")
            m.stage(fpath, "manager hello")
            r = m.commit(fpath)
            assert r["success"]
            assert os.path.exists(fpath)

    def test_status(self):
        from l3.resource_buffer.manager import get_manager, reset_manager
        reset_manager()
        with tempfile.TemporaryDirectory() as td:
            m = get_manager()
            st = m.status()
            assert isinstance(st, dict)

    def test_reset_singleton(self):
        from l3.resource_buffer.manager import get_manager, reset_manager
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        assert m2 is not None
