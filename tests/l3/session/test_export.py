"""Session Export integration test — export/import/snapshot + API"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSessionExport:
    """Session export"""

    def test_export_basic(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.export_session(
            session_id="sess-001",
            agent_id="agent-a",
            messages=[{"role": "user", "content": "hello"}],
            tags=["test"],
            metadata={"version": 1},
        )
        assert r["success"]
        assert r["session_id"] == "sess-001"
        assert r["turn_count"] == 1
        data = r["data"]
        assert data["version"] == 2
        assert "test" in data["tags"]

    def test_export_no_messages(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.export_session(agent_id="agent-b")
        assert r["success"]
        assert r["turn_count"] == 0


class TestSessionImport:
    """Session import"""

    def test_import_valid(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        export = mgr.export_session(
            session_id="sess-002",
            messages=[{"role": "user", "content": "hi"}],
        )
        raw = export["data"]
        import json
        r = mgr.import_session(json.dumps(raw))
        assert r["success"]
        assert r["session_id"] == "sess-002"
        assert len(r["messages"]) == 1

    def test_import_invalid_json(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.import_session("not valid json")
        assert not r["success"]

    def test_import_empty(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.import_session("")
        assert not r["success"]


class TestSnapshot:
    """Snapshot management"""

    def test_create_and_list(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.create_snapshot(
            session_id="sess-003",
            messages=[{"role": "user", "content": "test"}],
            agent_id="agent-c",
            label="first snapshot",
        )
        assert r["success"]
        snap_id = r["snapshot_id"]
        assert snap_id is not None

        # List
        lr = mgr.list_snapshots()
        assert lr["success"]
        assert lr["count"] >= 1
        snap_ids = [s["id"] for s in lr["snapshots"]]
        assert snap_id in snap_ids

    def test_restore_snapshot(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.create_snapshot(
            session_id="sess-restore",
            messages=[{"role": "user", "content": "save me"}],
            label="restore test",
        )
        assert r["success"]
        snap_id = r["snapshot_id"]

        rr = mgr.restore_snapshot(snap_id)
        assert rr["success"]
        assert rr["session_id"] == "sess-restore"
        assert len(rr["data"]["messages"]) == 1

    def test_restore_nonexistent(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.restore_snapshot("nonexistent-snap-id")
        assert not r["success"]

    def test_delete_snapshot(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.create_snapshot(session_id="sess-del", label="delete me")
        snap_id = r["snapshot_id"]

        dr = mgr.delete_snapshot(snap_id)
        assert dr["success"]

        # Confirm deleted
        rr = mgr.restore_snapshot(snap_id)
        assert not rr["success"]

    def test_delete_nonexistent(self):
        from l3.session_export import SessionExportManager
        mgr = SessionExportManager()
        r = mgr.delete_snapshot("nonexistent")
        assert not r["success"]


class TestSessionExportModel:
    """SessionExport data model"""

    def test_version(self):
        from l3.session_export import SessionExport
        s = SessionExport()
        assert s.version == 2

    def test_to_json_roundtrip(self):
        from l3.session_export import SessionExport
        s = SessionExport(session_id="rt", messages=[{"role": "u", "content": "ok"}])
        raw = s.to_json()
        s2 = SessionExport.from_json(raw)
        assert s2.session_id == "rt"
        assert len(s2.messages) == 1

    def test_to_dict(self):
        from l3.session_export import SessionExport
        s = SessionExport(session_id="dict-test", tags=["a"])
        d = s.to_dict()
        assert d["version"] == 2
        assert d["session_id"] == "dict-test"


class TestApiHandlers:
    """API Handler function-level test"""

    def test_handle_export(self):
        from l3.session_export import handle_session_export
        r = handle_session_export({"session_id": "api-export", "messages": []})
        assert r["success"]

    def test_handle_import(self):
        from l3.session_export import handle_session_import
        r = handle_session_import({"data": '{"version":2}'})
        assert r["success"]  # valid JSON with version=2 succeeds

    def test_handle_snapshots(self):
        from l3.session_export import handle_session_snapshots
        r = handle_session_snapshots()
        assert r["success"]

    def test_handle_create_snapshot(self):
        from l3.session_export import handle_session_snapshot_create
        r = handle_session_snapshot_create({"session_id": "api-snap"})
        assert r["success"]

    def test_handle_restore_nonexistent(self):
        from l3.session_export import handle_session_snapshot_restore
        r = handle_session_snapshot_restore({"snapshot_id": "no-such-snap"})
        assert not r["success"]

    def test_handle_delete_nonexistent(self):
        from l3.session_export import handle_session_snapshot_delete
        r = handle_session_snapshot_delete({"snapshot_id": "no-such-snap"})
        assert not r["success"]
