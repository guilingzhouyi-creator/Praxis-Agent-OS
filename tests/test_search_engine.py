"""Search Engine 集成测试 — 语义搜索 + 符号搜索 + 文档搜索 + API"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tempfile
from pathlib import Path


class TestSemanticSearch:
    """语义搜索（TF-IDF）"""

    def test_search_empty_query(self):
        from services.search_engine import SemanticSearch
        s = SemanticSearch()
        r = s.search("", max_results=10)
        assert not r["success"]

    def test_search_found(self):
        s = _make_semantic()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.py"
            p.write_text("def hello_world():\n    print('hello')\n", encoding="utf-8")
            r = s.search("hello", root_dir=d, max_results=20)
            assert r["success"]
            assert r["total_matches"] >= 1
            assert any("hello" in res["content"] for res in r["results"])

    def test_search_not_found(self):
        s = _make_semantic()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.py"
            p.write_text("def foo():\n    pass\n", encoding="utf-8")
            r = s.search("nonexistent_xyzzy", root_dir=d, max_results=20)
            assert r["success"]
            assert r["total_matches"] == 0


def _make_semantic():
    from services.search_engine import SemanticSearch
    return SemanticSearch()


class TestSymbolSearch:
    """符号搜索（AST）"""

    def test_search_function(self):
        from services.search_engine import SymbolSearch
        s = SymbolSearch()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.py"
            p.write_text("def my_function():\n    pass\nclass MyClass:\n    pass\n", encoding="utf-8")
            r = s.search("my_function", root_dir=str(d))
            assert r["success"]
            assert r["total_matches"] >= 1
            hits = [h for h in r["results"] if h["symbol_name"] == "my_function"]
            assert len(hits) >= 1
            assert hits[0]["symbol_type"] == "function"

    def test_search_class(self):
        from services.search_engine import SymbolSearch
        s = SymbolSearch()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.py"
            p.write_text("class MyClass:\n    pass\n", encoding="utf-8")
            r = s.search("MyClass", root_dir=str(d))
            assert r["success"]
            hits = [h for h in r["results"] if h["symbol_type"] == "class"]
            assert len(hits) >= 1

    def test_search_not_found(self):
        from services.search_engine import SymbolSearch
        s = SymbolSearch()
        with tempfile.TemporaryDirectory() as d:
            r = s.search("NonexistentSymbolXyzzy", root_dir=str(d))
            assert r["success"]
            assert r["total_matches"] == 0


class TestDocSearch:
    """API 文档搜索"""

    def test_search_known(self):
        from services.search_engine import DocSearch
        ds = DocSearch()
        r = ds.search("pathlib.Path")
        assert r["success"]
        assert r["total"] >= 1
        assert any("Path" in res["name"] for res in r["results"])

    def test_search_unknown(self):
        from services.search_engine import DocSearch
        ds = DocSearch()
        r = ds.search("zzz_nonexistent_api_zzz")
        assert r["success"]
        assert r["total"] == 0

    def test_index_custom(self):
        from services.search_engine import DocSearch
        ds = DocSearch()
        r = ds.index("my_pkg", "my_mod", "my_func",
                      signature="my_func(arg1)", docstring="custom function")
        assert r["success"]
        result = ds.search("my_func")
        assert result["total"] >= 1


class TestSearchEngine:
    """统一搜索入口"""

    def test_search_semantic_mode(self):
        from services.search_engine import get_engine
        engine = get_engine()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "code.py"
            p.write_text("target_function = 42\n", encoding="utf-8")
            r = engine.search("target_function", mode="semantic", root_dir=d)
            assert r["success"]

    def test_search_symbol_mode(self):
        from services.search_engine import get_engine
        engine = get_engine()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mod.py"
            p.write_text("class TargetSymbol:\n    pass\n", encoding="utf-8")
            r = engine.search("TargetSymbol", mode="symbol", root_dir=d)
            assert r["success"]

    def test_search_docs_mode(self):
        from services.search_engine import get_engine
        engine = get_engine()
        r = engine.search("json.dumps", mode="docs")
        assert r["success"]

    def test_search_auto_symbol(self):
        from services.search_engine import get_engine
        engine = get_engine()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.py"
            p.write_text("class AutoClass:\n    pass\n", encoding="utf-8")
            r = engine.search("AutoClass", mode="auto", root_dir=d)
            assert r["success"]


class TestApiHandlers:
    """API Handler 函数级测试"""

    def test_handle_search_no_query(self):
        from services.search_engine import handle_search
        r = handle_search({})
        assert not r["success"]

    def test_handle_search_semantic(self):
        from services.search_engine import handle_search_semantic
        r = handle_search_semantic({"query": "test", "root": os.getcwd()})
        assert r["success"]

    def test_handle_search_symbol(self):
        from services.search_engine import handle_search_symbol
        r = handle_search_symbol({"name": "os"})
        assert r["success"]

    def test_handle_search_docs(self):
        from services.search_engine import handle_search_docs
        r = handle_search_docs({"query": "json.loads"})
        assert r["success"]
        assert r["total"] >= 1

    def test_handle_search_missing(self):
        from services.search_engine import handle_search_symbol
        r = handle_search_symbol({})
        assert not r["success"]

    def test_handle_index_doc(self):
        from services.search_engine import handle_search_index_doc
        r = handle_search_index_doc({
            "package": "test", "module": "test", "name": "t_func",
            "signature": "t_func()", "docstring": "test",
        })
        assert r["success"]
