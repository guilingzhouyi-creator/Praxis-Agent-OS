# L2 — Shell Layer

Human interface: 49 YAML commands + 2 code-registered, i18n, completion,
agent selection. 22 files / 3,384 lines. Imports L1 only (shell logic is
pure dict-in/dict-out).

## Responsibility boundary

- Parse human intent → dispatch to L3/L4 through tool calls or signals.
- Every handler returns a plain `dict` — the same contract the TUI/desktop
  frontends will render (logic/render separation).
- Never owns execution state: L3A direct sessions route to cells.

## Core modules

| Module | Role |
|--------|------|
| `l2_shell/` | Command dispatch (`dispatch`), state (L3A/Direct mode), output guard, settings commands, model commands |
| `commands/` | Per-domain command handlers (memory, settings, model, …) returning dicts |
| `i18n.py` | Localization (en/zh-CN/ja/ko), cached adapter |
| `shell_completer.py` | Tab completion + aliases (revision-based cache) |
| `selector.py` | Agent selector (locked index) |
| `shell.py` | REPL entry: `!intent` → L3A, `$cmd` → system, tool calls |

## Interaction model

```
line ──┬─ !<intent>          → L3A direct session (cardwrite path)
       ├─ !<intent>@cell/agent → routed direct session
       ├─ $ <command>        → raw system command (platform.run_shell)
       ├─ <tool> <args>      → tool execution (aliases: rf→read_file)
       └─ /command           → shell command handlers (dict results)
```

## Contract surfaces

- L3A direct session routing: `_handle_direct` → `intent_parse` → card
- Tool execution via `l3.tool_system.tool_spec.execute_tool_spec`
- Event emission: shell state changes / human corrections
  (`reference_channel.human_correction` — a profile collector source)

## Key points

- **L3A/Direct mode**: `l2_shell/state.py` singleton (reset per test via
  conftest `_RESETS`).
- Handlers are the frontend contract: TUI/desktop will call the same
  dict-returning functions (see `l5-user.md`).
