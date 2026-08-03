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
