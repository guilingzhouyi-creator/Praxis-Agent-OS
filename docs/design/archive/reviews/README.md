# Archived Code Reviews

Review documents from the 2026-07 review cycle. All P0 items and the
overwhelming majority of P1 items have been implemented; the remaining
debt is tracked below. The documents are preserved here for reference
(original fix proposals, scoring, and cross-layer analysis).

## Archive manifest

| Document | Scope | Status |
|----------|-------|--------|
| `fix-verification.md` | L1-L4 fix verification (29/29 + gatechain P0 callback) | ✅ Complete |
| `l1-code-review.md` | L1 kernel (10 cross-layer imports, DCLP) | ✅ P0/P1 done |
| `l1-kernel-code-review.md` | L1 deep review (os/errors/device) | ✅ P0 done |
| `l2-code-review.md` | L2 shell (47 findings) | ✅ P0 done |
| `l2-code-review-comparative.md` | L2 comparative (global lock, allowlist) | ✅ P0/P1 done |
| `l3-cell-code-review.md` | L3 cell (agent_loop import, except discipline) | ✅ P0 done |
| `l3-quality-review.md` | L3 quality sweep (l3b/message pool fixes) | ✅ Done |
| `l3a-deep-review.md` | L3A (lock, process_intent split) | ✅ P0/P1 done |
| `l3a-refactor-review.md` | L3A refactor (DCLP/bug fixes verified) | ✅ Done |
| `l4-code-review.md` | L4 bridge (DCLP, notify, search, git) | ✅ P0/P1 done |
| `l4-code-review-comparative.md` | L4 comparative + cross-layer roadmap | ✅ P0/P1 done |
| `l4-api-gateway-review.md` | API gateway (SSE, route cache) | ✅ Done |
| `l5-user-code-review.md` | L5 user layer | ✅ Done |
| `perf-review.md` | Performance (allocator O(N), HTTP pool) | ✅ P0/P1 done (HTTP pool in net_client) |
| `r4-archive-review.md` | R4 archive (fonds/ref-code/ttl) | ✅ Done |
| `bus-dataflow-review.md` | Bus dataflow (DCLP, monitor IO) | ✅ Done |

## Remaining debt (P1/P2, not scheduled)

1. **Large file splitting (P1)**: `cell/__init__.py` (919), `boot/boot.py` (929),
   `agent_terminal/__init__.py` (825), `agent/agent_loop.py` (937),
   `error_bus/__init__.py` (715) — component extraction started (cell: 18
   components) but aggregator files remain heavy.
2. **Broad `except Exception` precision (P1/P2)**: ~70+ occurrences across L3
   remain generic (no `except: pass` anywhere; all have logging or fallback).
3. **L2→L4 direct imports (P0, 2 sites)**: resolved via the layer-import
   allowlist (documented in `tests/infra/test_layer_imports.py`), not via an
   L3 bridge — acceptable per allowlist policy.
