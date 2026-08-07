"""SettingsCenter tests — three-layer priority, get/set/reset, persistence."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSettingsCenter:
    def test_l1_defaults_available(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        assert sc.get("approval.danger_threshold") == 3
        assert sc.get("llm.max_tokens") == 2048
        assert sc.get("nonexistent") is None

    def test_l1_default_with_fallback(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        assert sc.get("unknown.key", "fallback") == "fallback"

    def test_l2_overrides_l1(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.load_l2({"approval": {"danger_threshold": 5}})
        assert sc.get("approval.danger_threshold") == 5

    def test_l2_nested_flatten(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.load_l2({"memory": {"working_budget": 4096, "short_budget": 16000}})
        assert sc.get("memory.working_budget") == 4096
        assert sc.get("memory.short_budget") == 16000

    def test_l3_overrides_l2(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.load_l2({"approval.danger_threshold": 5})
        sc.set("approval.danger_threshold", 10)
        assert sc.get("approval.danger_threshold") == 10

    def test_set_and_get(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        r = sc.set("test.key", 42)
        assert r["success"]
        assert sc.get("test.key") == 42

    def test_set_many(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        r = sc.set_many({"a": 1, "b": 2, "c": 3})
        assert r["success"]
        assert r["count"] == 3
        assert sc.get("a") == 1
        assert sc.get("b") == 2

    def test_reset(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.set("test.reset_me", "value")
        assert sc.get("test.reset_me") == "value"
        sc.reset("test.reset_me")
        assert sc.get("test.reset_me") is None

    def test_reset_l1_fallback(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.set("approval.danger_threshold", 99)
        sc.reset("approval.danger_threshold")
        # Falls back to L1 (3) since reset clears L3
        assert sc.get("approval.danger_threshold") == 3

    def test_reset_all(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.set("k1", "v1")
        sc.set("k2", "v2")
        sc.reset_all()
        assert sc.get("k1") is None

    def test_all_merges_l1_l2_l3(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.load_l2({"l2.key": "from_l2"})
        sc.set("l3.key", "from_l3")
        all_settings = sc.all()
        assert all_settings["approval.danger_threshold"] == 3  # L1
        assert all_settings["l2.key"] == "from_l2"  # L2
        assert all_settings["l3.key"] == "from_l3"  # L3

    def test_diff_no_overrides(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        d = sc.diff()
        assert d == {}

    def test_diff_with_overrides(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.set("approval.danger_threshold", 5)
        d = sc.diff()
        assert "approval.danger_threshold" in d
        assert d["approval.danger_threshold"]["default"] == 3
        assert d["approval.danger_threshold"]["current"] == 5

    def test_typed_getters(self):
        from l3.config.settings_center import SettingsCenter

        sc = SettingsCenter()
        sc.set("int_key", "42")
        assert sc.get_int("int_key") == 42
        assert sc.get_float("float_key", 3.14) == 3.14
        assert sc.get_bool("bool_key", True) is True
        sc.set("bool_str", "true")
        assert sc.get_bool("bool_str") is True

    def test_persistence(self):
        """Verify L3 persists to file and reloads."""
        from l3.config.settings_center import SettingsCenter

        td = tempfile.mkdtemp()
        persist_path = os.path.join(td, "settings.json")
        sc1 = SettingsCenter(persist_path=persist_path)
        sc1.set("persisted.key", "hello")
        # Create a new instance reading same file
        sc2 = SettingsCenter(persist_path=persist_path)
        sc2.load_l3()
        assert sc2.get("persisted.key") == "hello"
        shutil.rmtree(td, ignore_errors=True)

    def test_get_center_singleton(self):
        from l3.config.settings_center import get_center, reset_center

        reset_center()
        c1 = get_center()
        c2 = get_center()
        assert c1 is c2
