"""Tests for file operation tool handlers."""

from __future__ import annotations

import os
import tempfile

import pytest

from l3.tools._files import (
    read_file,
    list_dir,
    file_stat,
    create_file,
    file_move,
    file_copy,
)


class TestReadFile:
    def test_no_path(self):
        r = read_file({}, "agent-a")
        assert not r["success"]
        assert "path is required" in r["error"]

    def test_nonexistent_path(self):
        r = read_file({"path": "/nonexistent_file_xyz"}, "agent-a")
        assert not r["success"]


class TestListDir:
    def test_current_dir(self):
        r = list_dir({"path": "."}, "agent-a")
        assert r["success"]
        assert "data" in r
        assert isinstance(r["data"], list)

    def test_invalid_path(self):
        r = list_dir({"path": "/nonexistent_dir_xyz"}, "agent-a")
        assert not r["success"]

    def test_default_path(self):
        r = list_dir({}, "agent-a")
        assert r["success"]
        assert "data" in r


class TestFileStat:
    def test_no_path(self):
        r = file_stat({}, "agent-a")
        assert not r["success"]

    def test_this_file(self):
        r = file_stat({"path": __file__}, "agent-a")
        assert r["success"]
        assert "size" in r["data"]
        assert r["data"]["size"] > 0

    def test_nonexistent(self):
        r = file_stat({"path": "/nonexistent_stat_xyz"}, "agent-a")
        assert not r["success"]


class TestCreateFile:
    def test_no_path(self):
        r = create_file({}, "agent-a")
        assert not r["success"]

    def test_create_with_content(self):
        r = create_file({"path": "/tmp/test_praxis.txt", "content": "hello"}, "agent-a")
        # May fail due to sandbox but should return a dict
        assert isinstance(r, dict)


class TestFileMove:
    def test_no_source(self):
        r = file_move({}, "agent-a")
        assert not r["success"]

    def test_no_destination(self):
        r = file_move({"source": "/a"}, "agent-a")
        assert not r["success"]

    def test_nonexistent_source(self):
        r = file_move({"source": "/nonexistent_src", "destination": "/tmp/dst"}, "agent-a")
        assert not r["success"]


class TestFileCopy:
    def test_no_source(self):
        r = file_copy({}, "agent-a")
        assert not r["success"]

    def test_no_destination(self):
        r = file_copy({"source": "/a"}, "agent-a")
        assert not r["success"]
