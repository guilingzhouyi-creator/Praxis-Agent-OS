"""Compliance: L1-L4 code must use params constants, not hardcoded magic values.

Scans src/l1/..src/l4 for:
  - Truncation [:N] where N has a LOG_TRUNC_* constant
  - Hash truncation hexdigest()[:N] / hex()[:N] / uuid.uuid4().hex[:N] where N has a HASH_TRUNC_* constant

Violations are reported and cause test failure.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# Known constants and their values
LOG_TRUNC_VALUES: dict[int, str] = {
    40: "LOG_TRUNC_40",
    50: "LOG_TRUNC_50",
    60: "LOG_TRUNC_60",
    80: "LOG_TRUNC_80",
    100: "LOG_TRUNC_100",
    120: "LOG_TRUNC_120",
    150: "LOG_TRUNC_150",
    200: "LOG_TRUNC_200",
    300: "LOG_TRUNC_300",
    500: "LOG_TRUNC_500",
    1000: "LOG_TRUNC_1000",
    2000: "LOG_TRUNC_2000",
    3000: "LOG_TRUNC_3000",
    4000: "LOG_TRUNC_4000",
    5000: "LOG_TRUNC_5000",
    10000: "LOG_TRUNC_10000",
}

HASH_TRUNC_VALUES: dict[int, str] = {
    8: "HASH_TRUNC_SHORT",
    12: "HASH_TRUNC_MEDIUM",
    16: "HASH_TRUNC_LONG",
}

# Files/types exempt from scanning (e.g., test files, param definitions)
EXEMPT_DIRS = {"__pycache__", "params"}
EXEMPT_FILES = {"params.py", "__init__.py"}

SCAN_ROOTS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "l1"),
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "l2"),
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "l3"),
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "l4"),
]


def _excess_bare_slices(
    content: str, values: dict[int, str], pattern: re.Pattern[str]
) -> list[tuple[re.Match[str], str]]:
    """Return bare-slice matches whose count exceeds the constant's references.

    Closes the whole-file exemption loophole: a single ``LOG_TRUNC_200``
    reference used to exempt every other bare ``[:200]`` in the file.
    Now each bare slice beyond the number of constant references is a
    violation (a defined-and-reused alias like ``T = LOG_TRUNC_200`` is
    still fine because the constant name appears on the definition line).
    """
    excess: list[tuple[re.Match[str], str]] = []
    for val, const in values.items():
        matches = [m for m in pattern.finditer(content) if int(m.group(2)) == val]
        refs = content.count(const)
        for m in matches[refs:]:
            excess.append((m, const))
    return excess


def _find_violations() -> list[str]:
    """Scan L1-L4 for hardcoded values that should use params constants."""
    violations: list[str] = []
    hash_re = re.compile(r"(hexdigest\(\)|hex\(\)|uuid\.uuid4\(\)\.hex)\[:(\d+)\]")
    slice_re = re.compile(r"([\w.]+(?:\([^)]*\))?)\[[:](\d+)\]")

    for scan_root in SCAN_ROOTS:
        for root, dirs, files in os.walk(scan_root):
            dirs[:] = [d for d in dirs if d not in EXEMPT_DIRS]
            for fname in sorted(files):
                if not fname.endswith(".py") or fname in EXEMPT_FILES:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, scan_root)

                with open(fpath, encoding="utf-8") as f:
                    content = f.read()

                # 1. Check hash truncation (count-based, per-value)
                for m, const in _excess_bare_slices(content, HASH_TRUNC_VALUES, hash_re):
                    line_no = content[: m.start()].count("\n") + 1
                    violations.append(f"{rel}:{line_no}: {m.group(0)} should use {const}")

                # 2. Check slice truncation (count-based, per-value)
                for m, const in _excess_bare_slices(content, LOG_TRUNC_VALUES, slice_re):
                    line_no = content[: m.start()].count("\n") + 1
                    violations.append(f"{rel}:{line_no}: {m.group(0)} should use {const}")

    return violations


def test_no_hardcoded_truncation_values():
    """All truncation/hash literals in L3 must use params constants."""
    violations = _find_violations()
    assert not violations, "Hardcoded truncation/hash values found:\n  " + "\n  ".join(violations)


def test_no_hardcoded_truncation_values_strict():
    """Strict mode — fail on any violation."""
    violations = _find_violations()
    assert not violations, "Hardcoded truncation/hash values found:\n  " + "\n  ".join(violations)


class TestParamConstantsExist:
    """Verify key params constants are importable and have correct values."""

    def test_log_trunc_150_exists(self):
        from l1.kernel.params.system import LOG_TRUNC_150

        assert LOG_TRUNC_150 == 150

    def test_memory_importance_critical_exists(self):
        from l1.kernel.params.system import MEMORY_IMPORTANCE_CRITICAL

        assert MEMORY_IMPORTANCE_CRITICAL == 0.9

    def test_memory_importance_very_high_exists(self):
        from l1.kernel.params.system import MEMORY_IMPORTANCE_VERY_HIGH

        assert MEMORY_IMPORTANCE_VERY_HIGH == 0.85

    def test_l3b_hot_ring_size_exists(self):
        from l1.kernel.params.system import L3B_HOT_RING_SIZE

        assert L3B_HOT_RING_SIZE == 200

    def test_resource_buffer_dir_constants_exist(self):
        from l1.kernel.params.system import (
            RESOURCE_BUFFER_CHECKPOINT_FILE,
            RESOURCE_BUFFER_HIDDEN_DIR,
            RESOURCE_BUFFER_JOURNAL_FILE,
            RESOURCE_BUFFER_PENDING_DIR,
            RESOURCE_BUFFER_ROOT_DIR,
        )

        assert RESOURCE_BUFFER_PENDING_DIR == "_pending"
        assert RESOURCE_BUFFER_HIDDEN_DIR == "_hidden"
        assert RESOURCE_BUFFER_CHECKPOINT_FILE == "_checkpoint.dat"
        assert RESOURCE_BUFFER_JOURNAL_FILE == "_journal.jsonl"
        assert RESOURCE_BUFFER_ROOT_DIR == "resource_buffer"

    def test_config_path_constants_exist(self):
        from l1.kernel.params.system import COMMANDS_CONFIG_PATH, TOOLS_CONFIG_PATH

        assert TOOLS_CONFIG_PATH == "config/tools.yaml"
        assert COMMANDS_CONFIG_PATH == "config/commands.yaml"

    def test_file_template_constants_exist(self):
        from l1.kernel.params.system import (
            CARD_YAML_EXPORT,
            LOG_EXPORT_FILE,
        )

        assert LOG_EXPORT_FILE  # just check importable, format varies
        assert CARD_YAML_EXPORT == "{name}.card.yaml"

    def test_memory_subdir_constants_exist(self):
        from l1.kernel.params.system import (
            MEMORY_AGENT_SESSIONS_DIR,
            MEMORY_WORKSPACES_FILE,
        )

        assert MEMORY_AGENT_SESSIONS_DIR == "AGENT/sessions"
        assert MEMORY_WORKSPACES_FILE == "workspaces.json"
