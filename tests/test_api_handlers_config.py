"""Config API 集成测试 — 配置列表/读取/覆写/分类 + API"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestFetchConfig:
    """配置读取"""

    def test_fetch_known(self):
        from services.api_handlers_config import _fetch
        r = _fetch("API_GATEWAY_PORT")
        assert r["success"]
        assert r["key"] == "API_GATEWAY_PORT"
        assert isinstance(r["value"], int)

    def test_fetch_unknown(self):
        from services.api_handlers_config import _fetch
        r = _fetch("NONEXISTENT_KEY_XYZ")
        assert not r["success"]

    def test_fetch_string_value(self):
        from services.api_handlers_config import _fetch
        r = _fetch("DEFAULT_CELL_ID")
        assert r["success"]
        assert isinstance(r["value"], str)

    def test_fetch_override_source(self):
        from services.api_handlers_config import _fetch, _CONFIG_OVERRIDES
        _CONFIG_OVERRIDES.clear()
        # Initially source is "default"
        r = _fetch("API_GATEWAY_PORT")
        assert r["source"] == "default"

    def test_fetch_with_category(self):
        from services.api_handlers_config import _fetch
        r = _fetch("API_GATEWAY_PORT")
        assert "category" in r


class TestConfigList:
    """配置列表"""

    def test_list_all(self):
        from services.api_handlers_config import handle_config_list
        r = handle_config_list({})
        assert r["success"]
        assert r["count"] >= 10
        assert len(r["entries"]) >= 10

    def test_list_by_category(self):
        from services.api_handlers_config import handle_config_list
        r = handle_config_list({"category": "network"})
        assert r["success"]
        if r["count"] > 0:
            for e in r["entries"]:
                assert e["category"] == "network"

    def test_list_category_all(self):
        from services.api_handlers_config import handle_config_list
        r = handle_config_list({"category": ""})
        assert r["success"]
        assert r["category"] == "*"


class TestConfigGet:
    """配置读取端点"""

    def test_get_known(self):
        from services.api_handlers_config import handle_config_get
        r = handle_config_get({"key": "KERNEL_VERSION"})
        assert r["success"]
        assert r["key"] == "KERNEL_VERSION"
        assert r["value"] == "0.3.0"

    def test_get_unknown(self):
        from services.api_handlers_config import handle_config_get
        r = handle_config_get({"key": "NONEXISTENT_KEY_XYZ"})
        assert not r["success"]

    def test_get_missing_key(self):
        from services.api_handlers_config import handle_config_get
        r = handle_config_get({})
        assert not r["success"]


class TestConfigSet:
    """运行时覆写"""

    def test_set_and_get(self):
        from services.api_handlers_config import handle_config_set, handle_config_get, _CONFIG_OVERRIDES
        _CONFIG_OVERRIDES.clear()

        r = handle_config_set({"key": "TEST_OVERRIDE", "value": "custom_value"})
        assert r["success"]
        assert r["source"] == "override"

        r2 = handle_config_get({"key": "TEST_OVERRIDE"})
        assert r2["success"]
        assert r2["value"] == "custom_value"
        assert r2["source"] == "override"

    def test_set_int(self):
        from services.api_handlers_config import handle_config_set, _CONFIG_OVERRIDES
        _CONFIG_OVERRIDES.clear()
        r = handle_config_set({"key": "MAX_TEST", "value": 999})
        assert r["success"]
        assert r["value"] == 999

    def test_set_missing_key(self):
        from services.api_handlers_config import handle_config_set
        r = handle_config_set({})
        assert not r["success"]


class TestConfigCategories:
    """配置分类"""

    def test_categories(self):
        from services.api_handlers_config import handle_config_categories
        r = handle_config_categories()
        assert r["success"]
        assert "categories" in r
        cats = r["categories"]
        assert isinstance(cats, dict)
        assert len(cats) >= 5  # at least 5 categories

    def test_known_category(self):
        from services.api_handlers_config import handle_config_categories
        r = handle_config_categories()
        cats = r["categories"]
        assert "network" in cats
        assert "kernel" in cats
        assert "agents" in cats


class TestSerialize:
    """值序列化"""

    def test_serialize_int(self):
        from services.api_handlers_config import _serialize
        assert _serialize(42) == 42
        assert _serialize(3.14) == 3.14

    def test_serialize_string(self):
        from services.api_handlers_config import _serialize
        assert _serialize("hello") == "hello"

    def test_serialize_list(self):
        from services.api_handlers_config import _serialize
        r = _serialize(["a", "b", "c"])
        assert isinstance(r, list)
        assert "a" in r

    def test_serialize_dict(self):
        from services.api_handlers_config import _serialize
        r = _serialize({"key": "val"})
        assert isinstance(r, dict)
        assert r["key"] == "val"
