---
Fonds: REVIEW
File: ui
Item: 001
Type: Review
Date: 2026-07-21
Timestamp: 2026-07-21T19:00
Author: OpenCode
Keywords: [NOMOS, Praxis, UI, review, cross-review]
Relations: [ARCHIVE-design-003]
Debts: []
---

# 🔵 OpenCode Cross-Review of the Praxis UI Design

## Core Decision

The review confirms that the three iron laws and the fractal three-ring direction are correct, and raises 6 inquiries and 5 issues that must be resolved before implementation.

## Design Rules

1. Task Card UX must finalize the creation entry scheme before P0 implementation (Issue A: free text + LLM parsing fallback + template library, three-phase progressive).
2. L3 concurrency model must be defined before P2 — single-queue serial / multi-L3 instance contention / intent-level time-slice round-robin (Issue D).
3. Fingerprint collision must be resolved before P2 — extend to 128 bit (SHA-256 truncated), verify full output hash on lookup, last-write-wins + warning log on extreme collision (Issue C).
4. G5 gate definition must be completed before P1 — defined as "cross-unit/production-level approval gate" (Issue B).
5. Before P1, a bidirectional mapping audit of PRAXIS_TOOLS ↔ NOMOS actual toolset must be performed (Issue E).
6. When tool output exceeds 200 lines or Ring 1 capacity is full, the storage strategy (truncate/deny/spill to disk) must be clearly defined and data eviction must be indicated in the UX.
7. When constitution's 200-line limit causes Tool Ring 1 eviction, the refeed prompt card must inform the user that evicted fingerprint data is unavailable.

## Specifications

- Fingerprint collision parameters: SHA-256 truncated → extend to 128 bit; at 48 bit space with N=10⁵, collision probability ≈ 1.8%, must be reduced
- Current `tool_ring.py` fingerprint lookup implementation: `next((r for r in ring if r.fingerprint == fp), None)` — silently returns error on collision, must be fixed
- G5 trigger conditions (Issue B): (1) operation involves files/resources outside Agent's territory (2) operation rank ≥ 4 (3) requires a second Agent witness; G5 failure → operation enters cross-unit request pool awaiting approval
- Implementation order enforced: Issue A (P0) → Issue B + Issue E (P1 parallel) → Issue C + Issue D (P2 parallel)
- Issue A three phases: P0 hardcoded templates → P1 user-defined templates → P2 LLM ad-hoc parsing
- Issue D stress test pass criteria: 50 intents arriving simultaneously, queuing delay < 10s (P95), no OOM

## Exclusions

- L3 unlimited concurrent intent processing: excluded (L3 must define a concurrency model; single queue is the default candidate)
- Fingerprint collision tolerance: excluded (48 bit collision is not negligible in production systems)
- G5 left undefined: excluded (document references G1-G5 in 7 places but G5 is undefined; must be completed before implementation)
- Implementing without mapping the toolset: excluded (`read_fingerprint` not listed in PRAXIS_TOOLS table, db_* tools not implemented)
