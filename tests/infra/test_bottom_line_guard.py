"""Bottom-line guard — harness modes may never degrade the safety base.

Regression tests for the security-hardening invariant: harness mode tables
may only skip *process* steps (approval/rate/pool), never safety-critical
steps (constitution/gatechain/sandbox), and the announced bottom-line string
must stay consistent across the two modules that publish it.
"""

from __future__ import annotations

import os

import pytest

from l1.kernel.params.tool import HARNESS_MODE_STEPS, HARNESS_MODES

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Only these process steps may ever be skipped by a harness mode.
_ALLOWED_SKIPS = frozenset({"approval", "rate", "pool"})
# Safety-critical steps named in the pipeline gate matrix; never skippable.
_SAFETY_STEPS = frozenset({"constitution", "gatechain", "sandbox"})
_SKIPPABLE_STEPS = _ALLOWED_SKIPS
_BOTTOM_LINE = "constitution + gatechain + sandbox + reference-channel recording"


class TestBottomLineGuard:
    """The per-mode skip table never touches safety-critical steps."""

    @pytest.mark.parametrize("mode", sorted(HARNESS_MODE_STEPS))
    def test_skip_table_only_process_steps(self, mode: str) -> None:
        skipped = set(HARNESS_MODE_STEPS[mode])
        assert skipped <= _SKIPPABLE_STEPS, f"{mode} skips non-process steps: {skipped - _SKIPPABLE_STEPS}"
        assert skipped.isdisjoint(_SAFETY_STEPS), f"{mode} skips a safety step: {skipped & _SAFETY_STEPS}"

    def test_mode_keys_are_valid_modes(self) -> None:
        assert set(HARNESS_MODE_STEPS) <= set(HARNESS_MODES)

    def test_governed_skips_nothing(self) -> None:
        assert set(HARNESS_MODE_STEPS["governed"]) == set()

    def test_bottom_line_consistent_across_modules(self) -> None:
        from l3.tool_system.harness import BOTTOM_LINE as HARNESS_BOTTOM_LINE
        from l3.tool_system.security_mode import BOTTOM_LINE as SECURITY_BOTTOM_LINE

        assert HARNESS_BOTTOM_LINE == _BOTTOM_LINE
        assert SECURITY_BOTTOM_LINE == _BOTTOM_LINE

    @pytest.mark.parametrize("rel_path", ["src/l3/tool_system/harness.py", "src/l3/tool_system/security_mode.py"])
    def test_hardcoded_bottom_line_matches_params_contract(self, rel_path: str) -> None:
        text = _read(rel_path)
        assert "constitution" in text and "gatechain" in text and "sandbox" in text
        assert "reference-channel" in text


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
        return f.read()
