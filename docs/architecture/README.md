# Praxis Architecture — Layer Reference

Five-layer Agent Operating System. Each layer document covers responsibility
boundaries, module inventory, core mechanisms, and contract surfaces.

> **Numbers below are generated** — run `python scripts/gen-doc-stats.py`
> to refresh; never hand-edit them.

## Layer documents

| Layer | Document | Responsibility |
|-------|----------|----------------|
| L5 | [l5-user.md](l5-user.md) | CLI entry, user-facing contract, TUI surface |
| L4 | [l4-bridge.md](l4-bridge.md) | API gateway (263 routes), LLM engine, WS/SSE/RPC channels, sandbox, auth, fs |
| L3 | [l3-card-lifecycle.md](l3-card-lifecycle.md) | Card end-to-end: produce → execute → approve → archive (incl. agents, bus, services) |
| L3 | [l3-memory.md](l3-memory.md) | 4-ring memory + side-channels (Mer / R5 / User Profile) + injection |
| L3 | [l3a-central.md](l3a-central.md) | L3A decision layer: the central office (sessions, ask, cardwrite, profile consumption) |
| L2 | [l2-shell.md](l2-shell.md) | 46-command shell, i18n, completer, agent selector |
| L1 | [l1-kernel.md](l1-kernel.md) | Process table, sync, event bus, constitution, GateChain, ports, params |
| — | [cross-cutting.md](cross-cutting.md) | Governance, event flow, session contract, injection switches, port abstractions |

## Numbers snapshot

| Metric | Value |
|--------|-------|
| L1 Kernel | 46 files / 12,390 lines |
| L2 Shell | 18 files / 2,636 lines |
| L3 Cell | 225 files / 50,272 lines |
| L4 Bridge | 69 files / 13,989 lines |
| L5 User | 2 files / 489 lines |
| L3A (peers) | 15 files / 4,015 lines |
| L3 Memory | 20 files / 5,299 lines |
| L3 Card | 21 files / 5,505 lines |
| L3 Services | 34 files / 8,924 lines |
| L3 Bus | 15 files / 3,583 lines |
| L3 Agent | 24 files / 4,618 lines |
| L4 Handlers | 17 files / 3,544 lines |
| API routes | 263 (`/api/v2/*` versioned) |
| Params modules / constants | 9 / 889 |

## Reading path

1. **New to Praxis**: [l1-kernel.md](l1-kernel.md) → [l3-card-lifecycle.md](l3-card-lifecycle.md) → [l3a-central.md](l3a-central.md)
2. **Frontend / contract work**: [l4-bridge.md](l4-bridge.md) → [l5-user.md](l5-user.md) → [cross-cutting.md](cross-cutting.md)
3. **Memory / agents**: [l3-memory.md](l3-memory.md) → [cross-cutting.md](cross-cutting.md)

## Archived

The pre-rewrite architecture documents (overview / reference / SOC /
deep-dive, 15 files) are archived at `memories/archives/architecture-v1/`
(out of git; history remains via `git log -- docs/architecture/`).
