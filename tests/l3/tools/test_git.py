"""Tests for Git tool handlers."""

from __future__ import annotations

from l3.tools._git import (
    git_branch,
    git_commit,
    git_push,
)


def _guard_no_real_commit() -> None:
    import subprocess

    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip() == "true":
            import pytest

            pytest.skip("inside git repo — skip to prevent accidental commit")
    except Exception:
        pass


class TestGitCommit:
    def test_no_message(self):
        r = git_commit({}, "agent-a")
        assert not r["success"]
        assert "message is required" in r["error"]

    def test_with_message(self):
        _guard_no_real_commit()
        r = git_commit({"message": "test commit"}, "agent-a")
        assert isinstance(r, dict)
        assert "success" in r


class TestGitPush:
    def test_push(self):
        r = git_push({}, "agent-a")
        assert isinstance(r, dict)


class TestGitBranch:
    def test_no_action(self):
        r = git_branch({}, "agent-a")
        assert not r["success"]

    def test_list(self):
        r = git_branch({"action": "list"}, "agent-a")
        assert isinstance(r, dict)

    def test_create_no_name(self):
        r = git_branch({"action": "create"}, "agent-a")
        assert not r["success"]

    def test_switch_no_name(self):
        r = git_branch({"action": "switch"}, "agent-a")
        assert not r["success"]

    def test_delete_no_name(self):
        r = git_branch({"action": "delete"}, "agent-a")
        assert not r["success"]

    def test_invalid_action(self):
        r = git_branch({"action": "nonexistent"}, "agent-a")
        assert not r["success"]
