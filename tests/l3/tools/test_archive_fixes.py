"""Archive fixes verification: fonds normalization, ref codes, ttl purge."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import l3.tools._archive as arc  # noqa: E402


def _fresh():
    """Point archive at a temp DB and reset the module-level connection."""
    arc._db_conn = None
    arc._ARCHIVE_DB = os.path.join(tempfile.mkdtemp(), "archive.db")


class TestFondsNormalization:
    def test_case_insensitive_fonds(self):
        _fresh()
        r1 = arc._cmd_archive_store("Agent-A", "series-1", "one")
        r2 = arc._cmd_archive_store("agent-a", "series-1", "two")
        assert r1["success"] is True and r2["success"] is True
        conn = arc._get_db()
        rows = conn.execute("SELECT fonds FROM archive").fetchall()
        assert all(r[0] == "agent-a" for r in rows)

    def test_search_normalizes_fonds_query(self):
        _fresh()
        arc._cmd_archive_store("agent-a", "s", "payload-x")
        r = arc.archive_search({"query": "payload-x", "fonds": "AGENT-A"}, "agent-a")
        assert r["success"] is True
        assert r["total"] == 1


class TestRefCode:
    def test_ref_code_generated_and_increments(self):
        _fresh()
        r1 = arc._cmd_archive_store("agent-a", "evolved", "one")
        r2 = arc._cmd_archive_store("agent-a", "evolved", "two")
        assert r1["ref_code"] == "agenta-evolve-00001"
        assert r2["ref_code"] == "agenta-evolve-00002"

    def test_ref_code_per_series(self):
        _fresh()
        r1 = arc._cmd_archive_store("agent-a", "lean", "one")
        r2 = arc._cmd_archive_store("agent-a", "evolved", "two")
        assert r1["ref_code"].endswith("-00001")
        assert r2["ref_code"].endswith("-00001")

    def test_search_returns_ref_code(self):
        _fresh()
        arc._cmd_archive_store("agent-a", "s", "needle")
        r = arc.archive_search({"query": "needle"}, "agent-a")
        assert r["results"][0]["ref_code"].startswith("agenta-")


class TestTtlPurge:
    def test_expired_entries_purged_on_search(self):
        _fresh()
        conn = arc._get_db()
        now = 1000.0
        conn.execute(
            "INSERT INTO archive (fonds, series, content, ttl, created_at, updated_at) VALUES ('a','s','old',60,?,?)",
            (now - 100, now - 100),
        )
        conn.execute(
            "INSERT INTO archive (fonds, series, content, ttl, created_at, updated_at) VALUES ('a','s','fresh',60,?,?)",
            (now - 10, now - 10),
        )
        conn.commit()
        import time as _t

        with (
            _t.patch("time.time", return_value=now)
            if hasattr(_t, "patch")
            else __import__("unittest.mock").mock.patch("l3.tools._archive.time.time", return_value=now)
        ):
            n = arc._purge_expired()
        assert n == 1
        rows = conn.execute("SELECT content FROM archive").fetchall()
        assert [r[0] for r in rows] == ["fresh"]

    def test_purge_skips_no_ttl(self):
        _fresh()
        conn = arc._get_db()
        conn.execute(
            "INSERT INTO archive (fonds, series, content, ttl, created_at, updated_at) VALUES ('a','s','keep',0,1,1)"
        )
        conn.commit()
        n = arc._purge_expired()
        assert n == 0
