"""Reasoning effort tier normalization tests (provider capability sets)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestNormalizeEffort:
    def _norm(self, effort, provider):
        from l4.llm.llm import LLMEngine

        return LLMEngine._normalize_effort({"reasoning_effort": effort}, provider)

    def test_anthropic_high_passthrough(self):
        d = self._norm("high", "anthropic")
        assert d["reasoning_effort"] == "high"

    def test_anthropic_none_falls_to_lowest(self):
        # Claude has no none tier: falls back to lowest supported (low)
        d = self._norm("none", "anthropic")
        assert d["reasoning_effort"] == "low"

    def test_anthropic_xhigh_falls_to_max_or_self(self):
        d = self._norm("xhigh", "anthropic")
        assert d["reasoning_effort"] == "xhigh"

    def test_deepseek_max_falls_to_high(self):
        # DeepSeek supports up to high
        d = self._norm("max", "deepseek")
        assert d["reasoning_effort"] == "high"

    def test_openai_xhigh_passthrough(self):
        d = self._norm("xhigh", "openai")
        assert d["reasoning_effort"] == "xhigh"

    def test_ollama_drops_param(self):
        d = self._norm("high", "ollama")
        assert "reasoning_effort" not in d

    def test_none_passthrough_untouched(self):
        # none is not sent to the provider anyway (llm.py guards it)
        d = self._norm("none", "openai")
        assert d["reasoning_effort"] == "none"

    def test_unknown_provider_untouched(self):
        d = self._norm("high", "mystery-provider")
        assert d["reasoning_effort"] == "high"

    def test_settings_override_tiers(self):
        from l3.config.settings_center import get_center
        from l4.llm.llm import LLMEngine

        sc = get_center()
        sc.set("llm.effort_tiers.anthropic", ["low", "medium"])
        try:
            d = LLMEngine._normalize_effort({"reasoning_effort": "high"}, "anthropic")
            assert d["reasoning_effort"] == "medium"
        finally:
            sc.reset("llm.effort_tiers.anthropic")
            sc.reset("llm.effort_tiers")
