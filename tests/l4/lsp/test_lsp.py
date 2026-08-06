"""LSP — local language server analysis tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestLSP:
    def test_get_lsp_returns_instance(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        assert lsp is not None

    def test_file_type_python(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        ft = lsp.file_type("test.py")
        assert ft == "python"

    def test_file_type_c(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        ft = lsp.file_type("main.c")
        assert ft == "c"

    def test_file_type_unknown(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        ft = lsp.file_type("Makefile")
        assert ft == "unknown"

    def test_symbol_search_returns_list(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        results = lsp.symbol_search("os")
        assert isinstance(results, list)

    def test_workspace_symbols_returns_list(self):
        from l4.lsp.lsp import get_lsp

        lsp = get_lsp()
        results = lsp.workspace_symbols()
        assert isinstance(results, list)

    def test_symbol_search_respects_limit(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        src = tmp_path / "sample.py"
        src.write_text("def alpha():\n    pass\n" * 10, encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        results = analyzer.symbol_search("alpha", limit=3)
        assert len(results) == 3

    def test_go_to_definition_finds_symbol(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        src = tmp_path / "sample.py"
        src.write_text("class Greeter:\n    def greet(self):\n        return 1\n", encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        sym = analyzer.go_to_definition("Greeter")
        assert sym is not None
        assert sym.name == "Greeter"
        assert sym.kind == "class"
        assert sym.file == "sample.py"

    def test_go_to_definition_missing_returns_none(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        src = tmp_path / "sample.py"
        src.write_text("class Greeter:\n    pass\n", encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        assert analyzer.go_to_definition("Missing") is None

    def test_find_references_lists_usage_lines(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        src = tmp_path / "sample.py"
        src.write_text("class Greeter:\n    pass\n\nuse = Greeter()\n", encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        refs = analyzer.find_references("Greeter")
        assert len(refs) == 2
        assert {r["file"] for r in refs} == {"sample.py"}

    def test_hover_info_returns_docstring(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        src = tmp_path / "sample.py"
        src.write_text('def greet():\n    """Say hello."""\n    return 1\n', encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        info = analyzer.hover_info("greet")
        assert info["found"] is True
        assert "Say hello" in info["docstring"]

    def test_diagnostics_ast_fallback_reports_syntax_error(self, tmp_path):
        from l4.lsp.lsp import LocalAnalyzer

        bad = tmp_path / "broken.py"
        bad.write_text("def f(:\n", encoding="utf-8")
        analyzer = LocalAnalyzer(str(tmp_path))
        analyzer._pyright_ok = False
        diags = analyzer.diagnostics("broken.py")
        assert diags and diags[0]["severity"] == "error"
