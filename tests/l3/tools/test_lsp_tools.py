"""LSP tool handlers — _lsp.py end-to-end with mocked backends."""

from __future__ import annotations

from unittest import mock

import pytest

from l4.lsp.lsp_manager import LspManager


class _FakeManager:
    """Minimal LspManager stand-in for hover/diagnostics handlers."""

    def hover(self, path, line, column):
        return {"success": True, "result": {"value": f"hover@{path}:{line}:{column}"}}

    def get_diagnostics(self, path):
        return {"success": True, "diagnostics": [], "summary": {"errors": 0}}


@pytest.fixture
def sample_project(tmp_path):
    """A tiny Python module used as the analyzer workspace."""
    src = tmp_path / "sample.py"
    src.write_text(
        "class Greeter:\n"
        "    def greet(self, name: str) -> str:\n"
        '        return f"hello {name}"\n'
        "\n"
        "def make_greeter() -> Greeter:\n"
        "    return Greeter()\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def ast_fallback_manager(sample_project):
    """Real LspManager with server startup disabled (AST fallback path)."""
    mgr = LspManager(str(sample_project))
    with mock.patch.object(mgr, "_get_or_start_server", return_value=None):
        yield mgr


def test_go_to_definition_finds_symbol_at_position(ast_fallback_manager, sample_project):
    from l3.tools import _lsp

    path = str(sample_project / "sample.py")
    with mock.patch("l4.lsp.lsp_manager.get_manager", return_value=ast_fallback_manager):
        result = _lsp.go_to_definition({"path": path, "line": 5, "column": 16}, "agent-1")
    assert result["success"] is True
    assert result["found"] is True
    assert result["result"]["name"] == "make_greeter"


def test_go_to_definition_no_symbol_at_position(ast_fallback_manager, sample_project):
    from l3.tools import _lsp

    path = str(sample_project / "sample.py")
    with mock.patch("l4.lsp.lsp_manager.get_manager", return_value=ast_fallback_manager):
        result = _lsp.go_to_definition({"path": path, "line": 4, "column": 1}, "agent-1")
    assert result["success"] is True
    assert result["found"] is False


def test_go_to_definition_requires_path():
    from l3.tools import _lsp

    result = _lsp.go_to_definition({}, "agent-1")
    assert result["success"] is False
    assert "path" in result["error"]


def test_find_references_lists_usages(ast_fallback_manager, sample_project):
    from l3.tools import _lsp

    path = str(sample_project / "sample.py")
    with mock.patch("l4.lsp.lsp_manager.get_manager", return_value=ast_fallback_manager):
        result = _lsp.find_references({"path": path, "line": 5, "column": 8}, "agent-1")
    assert result["success"] is True
    assert result["total"] >= 1
    assert result["results"][0]["file"] == "sample.py"


def test_workspace_symbols_uses_analyzer(sample_project):
    from l3.tools import _lsp

    with mock.patch("l4.lsp.lsp.get_lsp") as fake_lsp:
        fake_lsp.return_value.symbol_search.return_value = []
        result = _lsp.workspace_symbols({"query": "Greeter"}, "agent-1")
    assert result["success"] is True
    assert fake_lsp.return_value.symbol_search.call_count == 1


def test_hover_info_uses_manager(sample_project):
    from l3.tools import _lsp

    path = str(sample_project / "sample.py")
    with mock.patch("l4.lsp.lsp_manager.get_manager", return_value=_FakeManager()):
        result = _lsp.hover_info({"path": path, "line": 2, "column": 4}, "agent-1")
    assert result["success"] is True
    assert "hover@" in result["result"]["result"]["value"]


def test_diagnostics_uses_manager(sample_project):
    from l3.tools import _lsp

    path = str(sample_project / "sample.py")
    with mock.patch("l4.lsp.lsp_manager.get_manager", return_value=_FakeManager()):
        result = _lsp.diagnostics({"path": path}, "agent-1")
    assert result["success"] is True
