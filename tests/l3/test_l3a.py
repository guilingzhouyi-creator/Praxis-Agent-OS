"""L3A tests — intent parsing, domain inference, card type detection."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestL3A:
    def test_parse_intent_basic(self):
        from l3.l3a import L3A
        l3a = L3A()
        result = l3a.parse("修改数据库配置")
        assert result is not None

    def test_parse_intent_with_params(self):
        from l3.l3a import L3A
        l3a = L3A()
        result = l3a.parse("修改数据库配置")
        assert hasattr(result, "intent")
        assert hasattr(result, "card_type")
        assert hasattr(result, "domain")

    def test_domain_keywords(self):
        from tools.special.tools_l3 import _keyword_match
        assert _keyword_match("modify route endpoint", ["route"])
        assert _keyword_match("write test cases", ["test"])
        assert not _keyword_match("unknown topics", ["auth"])

    def test_card_type_detection(self):
        from l3.l3a import L3A, CardType
        l3a = L3A()
        result = l3a.parse("帮我查一下这个配置")
        assert result is not None

    def test_register_route(self):
        from l3.l3a import L3A
        l3a = L3A()
        l3a.register_route("app/routes", "cell-1")
        result = l3a.parse("修改路由配置")
        assert result is not None

    def test_parse_system_prompt(self):
        from l3.l3a import _PARSE_SYSTEM_PROMPT
        assert "L3A" in _PARSE_SYSTEM_PROMPT
        assert "JSON" in _PARSE_SYSTEM_PROMPT
