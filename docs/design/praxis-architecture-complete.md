---
fonds: DESIGN
series: architecture
item_no: 001
type: design
date: 2026-07-22
timestamp: 2026-07-22T19:00
author: L3
keywords: [NOMOS, Praxis, architecture, Agent OS]
relations: [ARCHIVE-design-002, ARCHIVE-design-003, ARCHIVE-design-006]
debts: []
---

# NOMOS Praxis Complete Architecture

## Core Decision

Define Praxis as the Agent OS Desktop Shell with a five-layer architecture, core components, and MVP scope.

## Design Rules

1. Praxis must be a Desktop Shell (primary), Portal is a Web debug interface (fallback), CLI is an emergency channel.
2. No bubbles, use cards — Agent output must be structured cards (execution card/dispute card/review card), not chat bubbles.
3. No conversation, use intents — Input must be a structured intent Task Card, not free-form text chat.
4. No compression, use auto-eviction — Ring full automatically evicts oldest records, no manual compression button.
5. L3 must use a pure Python rule engine (~100 lines), no LLM for routing decisions.
6. Task Card must include seven fields: intent/domain/card_type/context_refs/tools_hint/priority/agent_id.
7. Agent Cell must contain 3 peer Agents for mutual review, each Agent has independent territory.
8. Scout must be a read-only auxiliary unit, cannot write files, cannot redelegate (depth = 1), auto-terminates after 5 minutes timeout, max 3 active Scouts per Agent.
9. Inter-agent communication must go through MessageBus, Agents are forbidden from directly interacting with humans.

## Specifications

- Startup command: `python run.py --gui` (Praxis desktop), `python run.py` (Portal Web), `python run.py --cli` (CLI)
- TaskCard `@dataclass` fields: intent (str), domain (str), card_type (str), context_refs (list), tools_hint (list), priority (int, 1-5 default 3), agent_id (str)
- ToolRing three-ring capacity: Ring 1=32 (G1+G2 direct), Ring 2.5=8 (G1-G4 RequestPool), Ring 3=16 (G1-G5 approval+witness)
- RequestPool scheduling weights: reputation 40%, priority 35%, wait time 25%
- GateChain G5 decision matrix: all pass → pass | G3 warn + reputation ≥ 0.9 → pass | G3 warn + 0.7~0.9 → report | G3 warn + < 0.7 → block | any block → block
- IPC message paths: L3→Agent (TASK_ASSIGN/TASK_CANCEL/REVIEW_RESULT), Agent→L3 (TASK_ACCEPT/TASK_DONE/TASK_ERROR/DISPUTE_RAISE), Agent↔Agent (CROSS_REVIEW_REQ/CROSS_REVIEW_RESP/TERRITORY_QUERY)
- Agent→Human direct communication: forbidden, all human interaction must go through L3
- Three input modes: free mode (natural language → L3 parsing), template mode (template library select and fill), expert mode (direct YAML Task Card editing)
- MVP 5 tools: read_file(0/G1-G2), grep_search(0/G1-G2), replace_string_in_file(1/G1-G4), run_in_terminal(1/G1-G4), read_fingerprint(0/G1-G2)

## Exclusions

- Electron / Tauri / Qt: replaced by pywebview (<500ms startup, <50MB bundle, three-platform native WebView)
- LLM for L3 decisions: replaced by pure rule engine (Task Card is already structured, no reasoning needed)
- SubAgent concept: replaced by Scout (read-only, depth=1, no state persistence)
