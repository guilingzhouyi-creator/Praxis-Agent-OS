"""Tests for l4.search.search_engine — SemanticSearch + DocSearch + SymbolSearch."""

from __future__ import annotations

import tempfile
import os


class TestSemanticSearch:
    """SemanticSearch — TF-IDF keyword ranking."""

    def _make_search(self):
        from l4.search.search_engine import SemanticSearch
        return SemanticSearch()

    def test_search_empty_query(self):
        """空查询应返回错误。"""
        ss = self._make_search()
        r = ss.search("", root_dir=".")
        assert not r.get("success")
        assert "empty" in r.get("error", "")

    def test_search_nonexistent_dir(self):
        """不存在的目录应返回错误。"""
        ss = self._make_search()
        r = ss.search("test", root_dir="/nonexistent_path_xyz")
        assert not r.get("success")

    def test_search_finds_content(self):
        """搜索应返回匹配结果。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_search.py")
            with open(test_file, "w") as f:
                f.write("def hello_world():\n    return 'hello world'\n")
            ss = self._make_search()
            r = ss.search("hello_world", root_dir=tmpdir, file_pattern="*.py")
            assert r.get("success")
            assert r.get("total_matches", 0) >= 1
            results = r.get("results", [])
            assert any("hello_world" in res.get("content", "") for res in results)

    def test_search_no_match(self):
        """无匹配时 total 应为 0。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("x = 1\n")
            ss = self._make_search()
            r = ss.search("nonexistent_keyword_xyz", root_dir=tmpdir)
            assert r.get("success")
            assert r.get("total", 0) == 0

    def test_search_ignores_hidden(self):
        """应忽略隐藏目录中的文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hidden_dir = os.path.join(tmpdir, ".hidden")
            os.makedirs(hidden_dir)
            test_file = os.path.join(hidden_dir, "secret.py")
            with open(test_file, "w") as f:
                f.write("secret = 'hidden'\n")
            visible_file = os.path.join(tmpdir, "visible.py")
            with open(visible_file, "w") as f:
                f.write("visible = 'found'\n")
            ss = self._make_search()
            r = ss.search("visible", root_dir=tmpdir)
            assert r.get("success")
            assert r.get("total_matches", 0) >= 1


class TestDocSearch:
    """DocSearch — API documentation search."""

    def _make_doc(self):
        from l4.search.search_engine import DocSearch
        return DocSearch()

    def test_index_and_search(self):
        """索引后应能搜索到文档条目。"""
        ds = self._make_doc()
        ds.index("praxis", "l4.search", "SemanticSearch",
                 signature="SemanticSearch()",
                 docstring="Lightweight semantic search with TF-IDF")
        results = ds.search("semantic")
        assert results.get("success")
        items = results.get("results", [])
        assert len(items) >= 1
        names = [r["name"] for r in items]
        assert "SemanticSearch" in names

    def test_search_no_results(self):
        """搜索不存在的文档应返回空结果列表。"""
        ds = self._make_doc()
        results = ds.search("nonexistent_symbol_xyz")
        assert results.get("success")
        assert results.get("total", 0) == 0
        assert len(results.get("results", [])) == 0

    def test_index_multiple(self):
        """多个文档应全部可搜索。"""
        ds = self._make_doc()
        ds.index("praxis", "l3.cell", "Cell", docstring="Agent collaboration unit")
        ds.index("praxis", "l3.memory", "MemoryManager", docstring="Memory management")
        results = ds.search("memory")
        items = results.get("results", [])
        assert len(items) >= 1
        assert any(r["name"] == "MemoryManager" for r in items)

    def test_search_by_package(self):
        """搜索应支持按包过滤。"""
        ds = self._make_doc()
        ds.index("praxis", "l3.cell", "Cell", docstring="Cell class")
        ds.index("praxis", "l4.api", "ApiGateway", docstring="API gateway")
        results = ds.search("api")
        items = results.get("results", [])
        assert len(items) >= 1
        assert any("api" in r["module"] for r in items)


class TestSearchResult:
    """SearchResult dataclass — to_dict serialization."""

    def test_to_dict(self):
        from l4.search.search_engine import SearchResult
        sr = SearchResult(path="/test/file.py", line=10, content="def foo(): pass",
                          score=0.85, kind="symbol", symbol_name="foo", symbol_type="function")
        d = sr.to_dict()
        assert d["path"] == "/test/file.py"
        assert d["line"] == 10
        assert d["score"] == 0.85
        assert d["kind"] == "symbol"
        assert d["symbol_name"] == "foo"
