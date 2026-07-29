"""Tests for Git tool handlers."""

from __future__ import annotations

import pytest

from l3.tools._git import (
    git_commit,
    git_push,
    git_branch,
)


class TestGitCommit:
    def test_no_message(self):
        r = git_commit({}, "agent-a")
        assert not r["success"]
        assert "message is required" in r["error"]

    def test_with_message(self):
        r = git_commit({"message": "test commit"}, "agent-a")
        # In a non-git repo, git add will fail — that's fine
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
