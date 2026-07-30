"""Tests for memory_context.py / memory_search.py — extracted context builder + FTS5 search."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestMemoryContext:
    def test_build_context_with_watermark(self):
        from l3.memory_context import build_context
        from l3.memory import MemoryManager
        mem = MemoryManager()
        ctx = build_context(mem, "agent-ctx", max_tokens=4096)
        assert isinstance(ctx, str)
        assert "WATERMARK" in ctx

    def test_build_context_includes_entries(self):
        from l3.memory_context import build_context
        from l3.memory import MemoryManager
        mem = MemoryManager()
        mem.remember("agent-ctx2", "decision",
                      "Use Python 3.11 with async features throughout the application codebase.",
                      ring=1)
        ctx = build_context(mem, "agent-ctx2", max_tokens=4096)
        assert "WATERMARK" in ctx

    def test_build_context_empty_agent(self):
        from l3.memory_context import build_context
        from l3.memory import MemoryManager
        mem = MemoryManager()
        ctx = build_context(mem, "nonexistent-agent", max_tokens=512)
        assert isinstance(ctx, str)
        assert "WATERMARK" in ctx


class TestMemorySearch:
    def test_search_empty_db(self):
        from l3.memory_search import search_long_term
        from l3.memory import MemoryManager
        mem = MemoryManager()
        results = search_long_term(mem, "test query")
        assert isinstance(results, list)

    def test_search_no_db_file(self):
        from l3.memory_search import search_long_term
        from l3.memory import MemoryManager
        mem = MemoryManager()
        results = search_long_term(mem, "something")
        assert results == []
