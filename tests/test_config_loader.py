"""Tests for config_loader — load, apply, validate, and handler registration."""
from __future__ import annotations

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestConfigLoaderCore:
    def test_register_handler(self):
        from l3.config_loader import register_config_handler, list_config_handlers
        before = len(list_config_handlers())
        def _test_handler(_cfg, _s, _r): pass
        register_config_handler("test_section", _test_handler, override=True)
        after = len(list_config_handlers())
        assert after >= before
        assert "test_section" in list_config_handlers()

    def test_load_no_file(self):
        from l3.config_loader import load
        r = load("/tmp/nonexistent_praxis_config.yaml")
        assert not r.get("success")
        assert "no config file found" in r.get("error", "")

    def test_load_valid_yaml(self):
        from l3.config_loader import load
        td = tempfile.mkdtemp()
        yaml_path = os.path.join(td, "praxis.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("llm:\n  provider: test\n  model: test-model\n")
        r = load(yaml_path)
        assert r.get("success"), f"load failed: {r}"
        assert r["data"]["llm"]["provider"] == "test"
        assert r["data"]["llm"]["model"] == "test-model"
        import shutil; shutil.rmtree(td, ignore_errors=True)

    def test_apply_empty(self):
        from l3.config_loader import apply
        r = apply({})
        assert not r.get("success")

    def test_apply_valid(self):
        from l3.config_loader import apply
        r = apply({"llm": {"provider": "ollama", "max_tokens": 1024}})
        assert r.get("success"), f"apply failed: {r}"

    def test_validate_valid(self):
        from l3.config_loader import validate
        r = validate({"kernel": {}, "llm": {}, "cell": {}})
        assert r.get("success")

    def test_validate_invalid(self):
        from l3.config_loader import validate
        r = validate({"kernel": "not_a_dict"})
        assert not r.get("success")
        assert len(r.get("errors", [])) >= 1

    def test_load_dotenv(self):
        from l3.config_loader import load_dotenv
        td = tempfile.mkdtemp()
        env_path = os.path.join(td, ".env")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write('TEST_VAR=hello\nANOTHER=world\n')
        load_dotenv(env_path)
        assert os.environ.get("TEST_VAR") == "hello"
        assert os.environ.get("ANOTHER") == "world"
        import shutil; shutil.rmtree(td, ignore_errors=True)

    def test_interpolate_env(self):
        from l3.config_loader import _interpolate_env
        os.environ["TEST_INTERP"] = "interpolated_value"
        result = _interpolate_env({"key": "prefix_${TEST_INTERP}_suffix"})
        assert result["key"] == "prefix_interpolated_value_suffix"


class TestConfigHandlers:
    def test_handler_registry_populated(self):
        from l3.config_loader import list_config_handlers
        handlers = list_config_handlers()
        assert "kernel" in handlers
        assert "llm" in handlers
        assert "cell" in handlers
        assert "gatechain" in handlers
        assert "constitution" in handlers
        assert "cache" in handlers
        assert len(handlers) >= 15

    def test_llm_handler(self):
        from l3.config_loader import apply
        from l1.kernel.settings import get_settings
        s = get_settings()
        old_provider = s.get("llm.provider")
        r = apply({"llm": {"provider": "ollama", "temperature": 0.5}})
        assert r.get("success"), f"apply failed: {r}"
        new_provider = s.get("llm.provider")
        assert new_provider == "ollama", f"expected ollama, got {new_provider}"
        assert s.get("llm.temperature") == 0.5
