# L3 — Memory System (4 rings + side-channels)

How agents remember: operational rings, lossless archive, and the bypass
side-channels (Mer / R5 / User Profile). 20 files / 5,299 lines.

## Four-ring architecture

```
R1 working   — current task context (agent-local, hot)
R2 short     — session-scale memory (auto-persist, JSONL)
R3 long      — FTS5 searchable knowledge (SQLite)
R4 archive   — lossless, append-only (fonds/series/ref-code), restore baseline
```

| Concern | Module |
|---------|--------|
| Manager + rings | `memory.py`, `memory_ring.py`, `pager_swapper.py` |
| Multi-scope center | `central_memory.py` (register scopes: cells + L3A) |
| Persistence | `persist.py`-style mixins; crash-safety: dirty sets cleared only after write success |
| FTS5 / recall | `context_search.py`, `quality.py` (importance filtering) |
| R4 agent | `r4_agent.py` (archive, skill evolution, lean cases) |
| Task-aware injection | `memory_inject.py` (execute→summary / decide→Mer / resume→layered) |
| Init from memories | `memory_init.py` (boot restores agent topology) |

## Side-channels (bypass, all default off)

Independent transformations that never mutate the main flow; on error they
degrade to no-ops (originals intact):

| Channel | Module | What it does | Switch |
|---------|--------|--------------|--------|
| **Mer symbolization** | `memory_mer.py` | Aggregates high-value R1–R3 across scopes → **Mermaid flowchart** (node shapes = entry type: decision=diamond, summary/card=round; labels carry importance; R5 semantic edges solid; within-scope temporal chains dashed `-.->|t|`) → R4 (`agent-l3a/memory_mer_snapshot`) | `memory.mer.enabled` |
| **R5 graph** | `memory_graph.py` | SQLite `memory_edges`; rule + semantic (LLM) edges; diffusion recall; compact/reduce | `memory.graph.enabled` |
| **User profile** | `l3/services/user_profile.py` | Typed per-user model (preference/domain_focus/decision_style/rejection/habit/correction/trait/custom); collectors (APPROVAL_RESPONDED → decision_style, CARD_PENDING → domain_focus) + ingest API; rule refiner; TTL/decay; R4 per user; portable export/import; consumed by L3A (see `l3a-central.md`) | `user_profile.enabled` |

### Mer data flow (bypass pipeline)

```mermaid
flowchart LR
    TICK["L3A daemon tick"] -->|trigger| COLLECT["collect_entries(scope_ids)
        CentralMemory R1-R3, importance >= threshold,
        per-scope bounded, across Cells + L3A"]
    COLLECT -->|entries with _scope/imp/ts| EDGES["collect_edges(node_ids)
        R5 MemoryGraph edges (only when graph enabled)"]
    EDGES -->|semantic relations| SYM["to_mermaid(entries, edges)
        node shapes by entry type, importance labels,
        semantic edges solid + temporal chains dashed"]
    COLLECT --> SYM
    SYM -->|mermaid string| ARCHIVE["archive_to_r4
        fonds=agent-l3a, series=memory_mer_snapshot"]
    SYM -->|meta| EVENT["stats.memory.mer.transform event"]
    ARCHIVE --> R4["R4 archive (audit baseline, disposable)"]
```

Guarantees: bypass semantics (never mutates the main flow), lossless
originals (only a rendered condensation is archived), bounded work
(per-scope caps, max scopes, edge truncation).

### Mer symbolization example

```mermaid
flowchart LR
    subgraph mer_example
    e0{"decision: use JWT for auth (imp=0.8)"}
    e1("summary: token strategy review (imp=0.7)")
    e2{"decision: drop JWT in favor of mTLS (imp=0.9)"}
    e0 -->|contradicts| e2
    e0 -.->|t| e1
    end
```

## System-prompt injection (memory-related)

`prompt.inject.memory` (default true) gates task-aware memory context in
agent prompts; `prompt.inject.skills` gates evolved skills + lean failure
cases. See `cross-cutting.md` for the full injection table.

## Contract surface

- `/api/v2/memory*` (store/recall/stats), `/api/v2/memory/graph*` (R5),
  `/api/memory/mer/*` (Mer), `/api/v2/profile*` (user profile)
- Ports: none dedicated (memory accessed in-process); profile exposes
  port `"profile"` for cross-service queries
