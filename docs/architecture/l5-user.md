# L5 — User Layer

Entry points and user-facing contract. 2 files / 514 lines.

## CLI entry (`main.py` → `l5/cli.py`)

```
python src/main.py boot | health | status | ps | card <intent> |
                     tools | audit | chain | interrupts | devices
```

`cli.py` commands return dicts and print summaries — the same dicts a TUI
would render.

## Interaction layers (three tiers, one contract)

```
CLI   — scripted, one-shot commands          (existing)
TUI   — full-screen session UI (OpenCode-style, planned; contract-ready)
Desktop — multi-panel formal client          (future)
VSCode — symbiotic extension platform        (future)
```

All three consume the same language-agnostic contract:

- **Sessions**: `/api/v2/l3a/sessions*` (create/list/messages/send/close)
- **Identity**: `/api/v2/auth/*` (login/logout/refresh)
- **Realtime**: SSE `/api/events` + WS bridge (subscribe/rpc)
- **Cards/approvals**: `/api/v2/card*`, `/api/v2/approvals*` (+ event push)
- **Files**: `/api/v2/fs/*`
- **Profile**: `/api/v2/profile*` (user model reference)
- **Settings**: `/api/v2/settings` (incl. `prompt.inject.*` switches)

The TUI layer must be a pure HTTP client (no in-process imports) so the
kernel can sink or multi-language later without rewriting the frontend —
see `cross-cutting.md` for the architecture principle.

## L2 shell vs L5 CLI

- L2 shell = interactive REPL (`!intent`, `$cmd`, tools) — stays.
- L5 CLI = scripted entry (`praxis boot`, `praxis card ...`).
- TUI will add a third renderer over the same L2 handler dicts.
