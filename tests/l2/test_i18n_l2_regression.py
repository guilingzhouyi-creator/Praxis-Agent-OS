"""L2 i18n completeness guard: no bare English user-facing strings in shell modules."""

import re
from pathlib import Path

SCAN_PATHS = [
    Path("src/l2/l2_shell/commands"),
    Path("src/l2/l2_shell/commands_settings.py"),
    Path("src/l2/selector.py"),
    Path("src/l2/shell_session.py"),
]
ERROR_FIELD = re.compile(r'"(error|message)":\s*"[^"]*[A-Za-z][^"]*"')
ALLOWED_ERROR_VALUES = {"send_failed", "refused", "alive", ""}
MACHINE_TEXT = re.compile(r'"(state|status|data|role|category|engine|format)":\s*"[^"]*"')


def _iter_py(path: Path):
    if path.is_dir():
        for p in sorted(path.rglob("*.py")):
            if "__pycache__" not in p.parts:
                yield p
    else:
        yield path


def test_no_bare_english_error_or_message_literals():
    offenders: list[str] = []
    for base in SCAN_PATHS:
        for p in _iter_py(base):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if ERROR_FIELD.search(line):
                    val = re.search(r'"(?:error|message)":\s*"([^"]*)"', line)
                    assert val, line
                    if val.group(1) in ALLOWED_ERROR_VALUES or MACHINE_TEXT.search(line):
                        continue
                    offenders.append(f"{p}:{i}: {line.strip()}")
    assert not offenders, "Bare user-facing English strings must go through i18n:\n" + "\n".join(offenders)
