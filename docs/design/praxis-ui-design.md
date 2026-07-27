---
fonds: DESIGN
series: ux
item_no: 001
type: design
date: 2026-07-21
timestamp: 2026-07-21T19:00
author: NOMOSAgent
keywords: [NOMOS, Praxis, UI, UX, design]
relations: [ARCHIVE-design-008, ARCHIVE-design-001]
debts: []
---

# NOMOS Praxis — Non-Chat UI/UX Design

## Core Decision

Negate the premises of Chat UI, establishing a card-based Agent OS UI paradigm of "no bubbles, no conversation, no compression".

## Design Rules

1. No bubbles, use cards — each tool call = one collapsible card, chat bubbles are prohibited.
2. No conversation, use intents — user sends a Task Card (intent + context references), not a "message".
3. No compression, use eviction — do not display "context window 87%", show the ring's real-time status, eviction runs automatically in the background.
4. Do not display percentage caps — rings have no concept of "full", only current information density.
5. User only talks to L3 — Agents are autonomous within territory, cross-territory requires approval, user does not directly assign tasks to Agents.
6. Tools are categorized not by function, but by danger level — level 0 (read-only) auto-pass, level 1 (write to disk) G1-G4, levels 2-5 (data operations) progressively increase approval/witness/snapshot/confirmation requirements.
7. Model does not need to know the level — model normally sends tool_call, Praxis automatically routes based on danger level.

## Specifications

- Three-column layout: intent card panel (left) | Agent activity flow + Diff (center) | dual-ring status panel (right)
- Four activity flow card styles: ToolCallCard (tool name + gate light + fingerprint reference, collapsed by default), ReasoningCard (real-time streaming, auto-collapse after 60s), KnowledgeCard (Ring 2→R3 extraction notification), backfill hint card
- Dual-ring status panel display: shared ring usage / private ring usage / layer distribution (L2-L7) / eviction rate / token estimate — no percentage cap
- Tool ring fingerprint chain panel display: Agent name, chain integrity, recent tool calls, gate statistics (pass/warn/block/report)
- Agent panel display: three Agent status lights (active/idle/unstarted), reputation score, territory, cross-territory approval status, governance layer status (shared ring / fingerprint chain / request pool / G1-G5)
- PraxisToolInterceptor flow: GateChain check → execute → fingerprint → write to ToolRing → compress summary to MemoryRing2 → return summary (not original text)
- Danger level 0 tools: read_file, grep_search, list_dir (Gate: G1+G2)
- Danger level 1 tools: replace_string_in_file, create_file, run_in_terminal (Gate: G1+G2+G3+G4)
- Danger levels 3-5 tools: needs_approval=true, level 5 additionally needs_witness=true+needs_snapshot=true, db_migrate+deploy additionally L3_CONFIRM
- Ring Ω (cross-unit governance ring): capacity 100, inherits SharedRing eviction strategy, adds unit_reputations dictionary, cross_feed/cross_tool_request interfaces
- Window zoom model: single-unit mode (intent card + activity flow + unit panel) → multi-unit mode (intent card + activity flow + Ring Ω + multi-unit collapsible cards)
- Implementation priority: P0 (intent card input + activity flow layout + dual-ring status panel, 2-3 days) / P1 (tool call cards + LLM integration, 2+ days) / P2 (Agent panel + fingerprint chain visualization) / P3 (memory backfill hints)

## Exclusions

- Chat bubble scroll list: replaced by Agent activity flow cards
- "Input box + send button": replaced by intent card
- "Compress conversation" manual button: replaced by auto-eviction
- Single-layer three-ring structure: replaced by fractal recursive three-ring (Ring Ω cross-unit governance)
- Tools categorized by function: replaced by categorization by danger level
