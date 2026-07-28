#!/usr/bin/env python3
"""NOMOS Praxis Agent OS — shell entry point.

Commands extracted to cli.py for modularity.
Usage:
  python main.py boot                  # Start kernel + Cell
  python main.py health                # Kernel self-test
  python main.py ps                    # List processes
  python main.py card "<intent>"       # Dispatch a card
  python main.py tools [agent_id]      # List agent tools
  python main.py audit [agent_id]      # View syscall audit log
  python main.py chain <call_id>       # Verify tool call chain
  python main.py interrupts            # View interrupt counts
  python main.py devices               # List registered devices
  python main.py status                # Full system status
"""

import sys
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR) if _SCRIPT_DIR.endswith("src") else _SCRIPT_DIR
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from l5.cli import COMMANDS


def repl():
    """Interactive REPL loop — type commands at the prompt."""
    import atexit
    print("NOMOS Praxis Agent OS  —  type 'help' for commands, 'exit' to quit")

    try:
        from l3.memory.memory_init import register_shutdown_handler
        register_shutdown_handler()
    except Exception:
            pass

    while True:
        try:
            line = input("praxis> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        args = parts[1:]
        if cmd in ("exit", "quit", "q"):
            print("\n⏻ Shutting down...")
            try:
                from l3.memory.memory_init import shutdown_to_memories
                r = shutdown_to_memories()
                if r.get("success"):
                    for k, v in r.get("results", {}).items():
                        print(f"  {k}: {v}")
            except Exception:
                pass
            print("Goodbye.")
            break
        if cmd in ("help", "?"):
            print("Commands: " + ", ".join(sorted(COMMANDS.keys())))
            continue
        fn = COMMANDS.get(cmd)
        if not fn:
            print(f"Unknown: {cmd}. Type 'help'")
            continue
        try:
            fn(args)
        except Exception as e:
            print(f"Error: {e}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        args = sys.argv[2:]
        fn = COMMANDS.get(cmd)
        if not fn:
            print(f"Unknown command: {cmd}")
            print(__doc__)
            return
        fn(args)
    else:
        repl()


if __name__ == "__main__":
    main()
