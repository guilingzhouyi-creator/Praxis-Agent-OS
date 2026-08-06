"""L2 Shell — interactive entry point (`python -m l2.l2_shell`).

Starts a REPL that routes input through ``l2.l2_shell.dispatch``: ``/``-prefixed
commands hit the CommandRegistry, pipelines split on ``|``, and plain text falls
back to L3A intent processing.  Type ``exit`` (or ``q``) to quit.
"""

from __future__ import annotations

import os
import sys

# Make the package importable from a source checkout without `pip install -e .`
# (mirrors src/main.py's bootstrap).
_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from l2.l2_shell import dispatch  # noqa: E402


def _render(result) -> None:
    """Print a dispatch result dict to stdout.

    Prefers the pre-formatted ``output`` / ``answer`` fields; falls back to a
    flat ``key: value`` dump for data-only results (e.g. ``/status``).
    """
    if not isinstance(result, dict):
        print(result)
        return
    if result.get("success"):
        output = result.get("output")
        if output:
            print(output)
            return
        answer = result.get("answer")
        if answer:
            print(answer)
            return
        for key, value in result.items():
            if key not in ("success", "format"):
                print(f"{key}: {value}")
        return
    error = result.get("error", "unknown error")
    print(f"[error] {error}")
    suggestions = result.get("suggestions")
    if suggestions:
        print(f"[hint] try: {', '.join(suggestions[:10])}")


def repl() -> None:
    """Run the interactive L2 Shell REPL loop."""
    print("Praxis L2 Shell — type '/help' for commands, 'exit' to quit")
    while True:
        try:
            line = input("l2> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            break
        if line in ("help", "?"):
            line = "/help"
        try:
            result = dispatch(line)
        except Exception as e:
            print(f"[error] {e}")
            continue
        _render(result)


if __name__ == "__main__":
    repl()
