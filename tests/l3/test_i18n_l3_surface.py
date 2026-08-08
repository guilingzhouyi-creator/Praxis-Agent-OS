"""L3 i18n completeness guard: no bare English user-facing strings in regulated modules."""

import re
from pathlib import Path

L3_ROOT = Path("src/l3")

# Modules whose error/message payloads surface to the user via shell/API renders.
# Tool result content (_tools/*) and diagnostics are intentionally excluded —
# those strings feed the LLM context and must stay in English.
REGULATED = [
    L3_ROOT / "_pool.py",
    L3_ROOT / "scheduler",
    L3_ROOT / "cell/components",
    L3_ROOT / "cell/peers/central_collector.py",
    L3_ROOT / "cell/peers/l3a/helpers.py",
    L3_ROOT / "services/identity.py",
    L3_ROOT / "services/model_service.py",
    L3_ROOT / "tool_system/security_mode.py",
]
ERROR_FIELD = re.compile(r'"(error|message)":\s*"[^"]*[A-Za-z][^"]*"')
ALLOWED_ERROR_VALUES = {
    "send_failed",
    "refused",
    "alive",
    "",
    "no edits provided",
    "path and old_str are required",
}
MACHINE_TEXT = re.compile(r'"(state|status|data|role|category|engine|format|classification|code)":\s*"[^"]*"')


def test_no_bare_english_error_or_message_literals_in_l3_surface_modules():
    offenders: list[str] = []
    for base in REGULATED:
        files = sorted(base.rglob("*.py")) if base.is_dir() else [base]
        for p in files:
            if "__pycache__" in p.parts:
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if ERROR_FIELD.search(line):
                    val = re.search(r'"(?:error|message)":\s*"([^"]*)"', line)
                    assert val, line
                    if val.group(1) in ALLOWED_ERROR_VALUES or MACHINE_TEXT.search(line):
                        continue
                    if "_t(" in line:
                        continue
                    offenders.append(f"{p}:{i}: {line.strip()}")
    assert not offenders, "Bare user-facing English strings must go through i18n:\n" + "\n".join(offenders)
