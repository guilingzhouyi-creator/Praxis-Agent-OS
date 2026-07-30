"""MemoryInit tests — boot snapshot, shutdown dump, agent config round-trip."""
from __future__ import annotations

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Delay import so tests don't trigger memory_init side effects at module load
_imported = False


class TestMemoryInit:
    def test_snapshot_path_format(self):
        from l3.memory_init import _snapshot_path
        path = _snapshot_path("test")
        assert "test" in path
        assert path.endswith(".json")

    def test_read_write_json(self):
        from l3.memory_init import _read_json, _write_json
        td = tempfile.mkdtemp()
        test_path = os.path.join(td, "test.json")
        ok = _write_json(test_path, {"key": "value", "num": 42})
        assert ok
        data = _read_json(test_path)
        assert data["key"] == "value"
        assert data["num"] == 42
        shutil.rmtree(td, ignore_errors=True)

    def test_save_boot_snapshot(self):
        from l3.memory_init import save_boot_snapshot
        path = save_boot_snapshot([("agent-a", "reader", ["docs"])])
        assert path is not None
        assert path.endswith("_boot.json")
        if path and os.path.exists(path):
            os.remove(path)

    def test_latest_snapshot(self):
        from l3.memory_init import _latest_snapshot
        r = _latest_snapshot()
        assert r is None or r.endswith("_boot.json")
