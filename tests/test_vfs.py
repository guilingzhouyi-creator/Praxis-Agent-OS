"""Tests for Virtual File System — mount, read, write, list, access control."""

from __future__ import annotations

import os
import tempfile

import pytest

from l1.kernel.vfs import VFS, MountType, MountPoint, get_vfs, reset_vfs


# ═══════════════════════════════════════════════════════════════════
# MountPoint
# ═══════════════════════════════════════════════════════════════════

class TestMountPoint:
    def test_default_values(self):
        mp = MountPoint(name="test")
        assert mp.name == "test"
        assert mp.min_ring == 1
        assert not mp.read_only

    def test_custom_values(self):
        mp = MountPoint(name="secure", min_ring=3, read_only=True, description="safe")
        assert mp.min_ring == 3
        assert mp.read_only


# ═══════════════════════════════════════════════════════════════════
# VFS — mount
# ═══════════════════════════════════════════════════════════════════

class TestVfsMount:
    def test_mount_project(self):
        vfs = VFS()
        r = vfs.mount("/project", MountType.PROJECT, real_path=".", min_ring=1)
        assert r["success"]
        assert r["mount"] == "/project"

    def test_mount_duplicate(self):
        vfs = VFS()
        vfs.mount("/project", MountType.PROJECT, real_path=".")
        r = vfs.mount("/project", MountType.PROJECT, real_path=".")
        assert not r["success"]
        assert "already exists" in r["error"]

    def test_mounts_list(self):
        vfs = VFS()
        vfs.mount("/a", MountType.PROJECT, real_path=".")
        vfs.mount("/b", MountType.TEMP)
        mounts = vfs.mounts()
        assert len(mounts) == 2


# ═══════════════════════════════════════════════════════════════════
# VFS — read / write (real files via mount)
# ═══════════════════════════════════════════════════════════════════

class TestVfsReadWrite:
    def test_read_mounted_file(self):
        with tempfile.TemporaryDirectory() as td:
            file_path = os.path.join(td, "test.txt")
            with open(file_path, "w") as f:
                f.write("hello vfs")
            vfs = VFS()
            vfs.mount("/project", MountType.PROJECT, real_path=td)
            r = vfs.read("/project/test.txt")
            assert r["success"]
            assert r["content"] == "hello vfs"

    def test_write_mounted_file(self):
        with tempfile.TemporaryDirectory() as td:
            vfs = VFS()
            vfs.mount("/project", MountType.PROJECT, real_path=td)
            r = vfs.write("/project/out.txt", "written by vfs")
            assert r["success"]
            actual = open(os.path.join(td, "out.txt")).read()
            assert actual == "written by vfs"

    def test_read_nonexistent_mount(self):
        vfs = VFS()
        r = vfs.read("/nonexistent_mount/x")
        assert not r["success"]
        assert "ENOENT" in r.get("error_code", "")

    def test_read_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as td:
            vfs = VFS()
            vfs.mount("/project", MountType.PROJECT, real_path=td)
            r = vfs.read("/project/nonexistent.txt")
            assert not r["success"]

    def test_write_read_only_mount(self):
        with tempfile.TemporaryDirectory() as td:
            vfs = VFS()
            vfs.mount("/project", MountType.PROJECT, real_path=td, read_only=True)
            r = vfs.write("/project/x.txt", "data")
            assert not r["success"]
            assert "read-only" in r.get("error", "").lower() or "EACCES" in r.get("error_code", "")

    def test_read_ring_too_low(self):
        vfs = VFS()
        vfs.mount("/secure", MountType.PROJECT, real_path=".", min_ring=3)
        r = vfs.read("/secure/x", agent_ring=1)
        assert not r["success"]
        assert "EACCES" in r.get("error_code", "")


# ═══════════════════════════════════════════════════════════════════
# VFS — virtual files
# ═══════════════════════════════════════════════════════════════════

class TestVfsVirtual:
    def test_virtual_write_then_read(self):
        vfs = VFS()
        vfs.mount("/virtual", MountType.VIRTUAL)
        r = vfs.write("/virtual/note.txt", "virtual content")
        assert r["success"]
        r2 = vfs.read("/virtual/note.txt")
        assert r2["success"]
        assert r2["content"] == "virtual content"

    def test_virtual_no_mount(self):
        vfs = VFS()
        r = vfs.read("/virtual/x")
        # No mount point for /virtual → ENOENT
        assert not r["success"]


# ═══════════════════════════════════════════════════════════════════
# VFS — list directory
# ═══════════════════════════════════════════════════════════════════

class TestVfsList:
    def test_list_root(self):
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "a.txt"), "w").close()
            open(os.path.join(td, "b.txt"), "w").close()
            vfs = VFS()
            vfs.mount("/project", MountType.PROJECT, real_path=td)
            r = vfs.list("/project")
            assert r["success"]
            names = [e["name"] for e in r.get("entries", [])]
            assert "a.txt" in names
            assert "b.txt" in names

    def test_list_virtual_dir(self):
        vfs = VFS()
        vfs.mount("/virtual", MountType.VIRTUAL)
        r = vfs.list("/virtual")
        # Virtual root can be listed
        assert isinstance(r, dict)


# ═══════════════════════════════════════════════════════════════════
# VFS — proc / sys read
# ═══════════════════════════════════════════════════════════════════

class TestVfsProc:
    def test_proc_mounts(self):
        vfs = VFS()
        vfs.mount("/proc", MountType.SYSTEM)
        r = vfs.read("/proc/mounts")
        assert r["success"]
        assert "mounts" in r["content"].lower()

    def test_proc_processes(self):
        vfs = VFS()
        vfs.mount("/proc", MountType.SYSTEM)
        r = vfs.read("/proc/processes")
        assert r["success"]

    def test_sys_read(self):
        vfs = VFS()
        vfs.mount("/sys", MountType.SYSTEM)
        r = vfs.read("/sys/version")
        assert r["success"]


# ═══════════════════════════════════════════════════════════════════
# VFS — unmount
# ═══════════════════════════════════════════════════════════════════

class TestVfsUnmount:
    def test_unmount(self):
        vfs = VFS()
        vfs.mount("/project", MountType.PROJECT)
        r = vfs.unmount("/project")
        assert r["success"]
        mounts = vfs.mounts()
        assert len(mounts) == 0

    def test_unmount_nonexistent(self):
        vfs = VFS()
        r = vfs.unmount("/nonexistent")
        assert not r["success"]


# ═══════════════════════════════════════════════════════════════════
# VFS — singleton
# ═══════════════════════════════════════════════════════════════════

class TestVfsSingleton:
    def test_get_vfs(self):
        reset_vfs()
        v1 = get_vfs()
        v2 = get_vfs()
        assert v1 is v2

    def test_reset_vfs(self):
        reset_vfs()
        v = get_vfs()
        v.mount("/project", MountType.PROJECT)
        reset_vfs()
        v2 = get_vfs()
        assert len(v2.mounts()) == 0
