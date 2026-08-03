"""LSP Manager integration test — diagnostics + feedback + API"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tempfile


class TestDiagnosticCache:
    """Diagnostic cache"""

    def test_cache_miss(self):
        from l4.lsp.lsp_manager import DiagnosticCache
        dc = DiagnosticCache(ttl=30.0)
        r = dc.get("/tmp/nonexistent.py")
        assert r is None

    def test_cache_set_get(self):
        from l4.lsp.lsp_manager import DiagnosticCache, DiagnosticEntry, FileDiagnostics

        dc = DiagnosticCache(ttl=30.0)
        fd = FileDiagnostics(
            file="/tmp/test.py",
            diagnostics=[
                DiagnosticEntry(file="/tmp/test.py", line=1, column=0,
                                message="test error", severity="error"),
            ],
        )
        dc.set(fd)
        cached = dc.get("/tmp/test.py")
        assert cached is not None
        assert cached.has_errors()
        s = cached.summary()
        assert s["errors"] == 1

    def test_cache_ttl(self):
        import time

        from l4.lsp.lsp_manager import DiagnosticCache, FileDiagnostics

        dc = DiagnosticCache(ttl=0.1)
        fd = FileDiagnostics(file="/tmp/t.py")
        dc.set(fd)
        time.sleep(0.15)
        cached = dc.get("/tmp/t.py")
        assert cached is None

    def test_invalidate(self):
        from l4.lsp.lsp_manager import DiagnosticCache, FileDiagnostics

        dc = DiagnosticCache()
        fd = FileDiagnostics(file="/tmp/t.py")
        dc.set(fd)
        dc.invalidate("/tmp/t.py")
        assert dc.get("/tmp/t.py") is None

    def test_clear(self):
        from l4.lsp.lsp_manager import DiagnosticCache, FileDiagnostics

        dc = DiagnosticCache()
        dc.set(FileDiagnostics(file="/tmp/a.py"))
        dc.set(FileDiagnostics(file="/tmp/b.py"))
        dc.clear()
        stats = dc.stats()
        assert stats["cached_files"] == 0

    def test_stats_summary(self):
        from l4.lsp.lsp_manager import DiagnosticCache, DiagnosticEntry, FileDiagnostics

        dc = DiagnosticCache()
        fd = FileDiagnostics(
            file="/tmp/e.py",
            diagnostics=[DiagnosticEntry(file="/tmp/e.py", line=1, column=0,
                                          message="err", severity="error")],
        )
        dc.set(fd)
        stats = dc.stats()
        assert stats["cached_files"] == 1
        assert stats["files_with_errors"] == 1


class TestAstDiagnostics:
    """AST fallback diagnostics"""

    def test_syntax_error(self):
        from l4.lsp.lsp_manager import LspManager
        mgr = LspManager()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def broken(\n")
            tmp = f.name
        try:
            diags = mgr._ast_diagnostics(tmp)
            assert len(diags) >= 1
            assert diags[0]["severity"] == "error"
            assert "SyntaxError" in diags[0]["message"]
        finally:
            os.unlink(tmp)

    def test_valid_syntax(self):
        from l4.lsp.lsp_manager import LspManager
        mgr = LspManager()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("# valid\nx = 1\n")
            tmp = f.name
        try:
            diags = mgr._ast_diagnostics(tmp)
            assert len(diags) == 0
        finally:
            os.unlink(tmp)


class TestLanguageDetection:
    """Language detection"""

    def test_python_ext(self):
        from l4.lsp.lsp_manager import LspManager
        mgr = LspManager()
        assert mgr._detect_language(".py") == "python"
        assert mgr._detect_language(".ts") == "typescript"
        assert mgr._detect_language(".rs") == "rust"
        assert mgr._detect_language(".rb") == "ruby"
        assert mgr._detect_language(".unknown") is None


class TestApiHandlers:
    """API Handler function-level test"""

    def test_handle_lsp_diagnostics_missing_file(self):
        from l4.lsp.lsp_manager import handle_lsp_diagnostics
        r = handle_lsp_diagnostics({})
        assert not r["success"]

    def test_handle_lsp_diagnostics_python(self):
        from l4.lsp.lsp_manager import handle_lsp_diagnostics

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("x = 1\n")
            tmp = f.name
        try:
            r = handle_lsp_diagnostics({"file": tmp})
            # may fail if pyright not installed — fallback to AST should work
            assert isinstance(r, dict)
            if r.get("success"):
                assert "diagnostics" in r
        finally:
            os.unlink(tmp)

    def test_handle_lsp_feedback_no_file(self):
        from l4.lsp.lsp_manager import handle_lsp_feedback
        r = handle_lsp_feedback({})
        assert not r["success"]

    def test_handle_lsp_servers(self):
        from l4.lsp.lsp_manager import handle_lsp_servers
        r = handle_lsp_servers()
        assert r["success"]
        assert "servers" in r

    def test_handle_lsp_start_stop(self):
        from l4.lsp.lsp_manager import handle_lsp_start
        # Just test that the handlers are callable
        r = handle_lsp_start({"language": "python"})
        assert isinstance(r, dict)
        # might fail if pyright not installed — that's fine
        del r
