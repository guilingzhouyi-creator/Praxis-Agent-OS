"""Sandbox entry — SandboxEntry dataclass tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSandboxEntry:
    def test_create_entry(self):
        from l4.sandbox.entry import SandboxEntry
        entry = SandboxEntry(path="/test/file.txt", sandbox_path="/sb/file.txt", agent_id="agent-a")
        assert entry.path == "/test/file.txt"
        assert entry.agent_id == "agent-a"

    def test_to_serializable(self):
        from l4.sandbox.entry import SandboxEntry
        entry = SandboxEntry(path="/test/file.txt", sandbox_path="/sb/file.txt", agent_id="agent-a")
        s = entry.to_serializable()
        assert s["path"] == "/test/file.txt"

    def test_from_dict(self):
        from l4.sandbox.entry import SandboxEntry
        s = SandboxEntry.from_dict({
            "path": "/test/a.py", "sandbox_path": "/sb/a.py", "agent_id": "agent-x"
        })
        assert s.path == "/test/a.py"
        assert s.agent_id == "agent-x"

    def test_to_human_readable(self):
        from l4.sandbox.entry import SandboxEntry
        entry = SandboxEntry(path="/test/file.txt", sandbox_path="/sb/file.txt", agent_id="agent-a")
        hr = entry.to_human_readable()
        assert isinstance(hr, (str, dict))

    def test_to_summary(self):
        from l4.sandbox.entry import SandboxEntry
        entry = SandboxEntry(path="/test/file.txt", sandbox_path="/sb/file.txt", agent_id="agent-a")
        summary = entry.to_summary()
        assert isinstance(summary, dict)
