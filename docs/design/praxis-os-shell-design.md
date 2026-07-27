---
fonds: DESIGN
series: Praxis-v1
title: Praxis Agent OS Shell — Complete Design Draft
status: Design Draft — Pending Three-Agent Review
style_reference: NOMOS Portal (black+red+gold) + VS Code Style Menu Bar
relations: [ARCHIVE-design-009, ARCHIVE-design-003, ARCHIVE-design-001]
---

# Praxis Agent OS Shell — Complete Design Draft

## Core Decision

Define Praxis five-region desktop layout, dual-mode main view, L3 Chat interaction model, Agent status bar, and MVP pass conditions.

## Design Rules

1. Window must adopt five-region layout: VS Code style menu bar (top), transaction area (left ~280px), main view (center), L3 Chat (right ~320px), Agent status bar (bottom).
2. Center main view must support dual-mode switching: monitor mode (default, track Agent real-time changes) and dispute review mode.
3. Transaction area must contain pending decision issue list (top half) and dispute report cards (bottom half).
4. File changes must be marked with change type: M (green, modified), A (blue, added), D (red, deleted), each Agent has a corresponding color (A=green #3fb950, B=blue #58a6ff, C=red #f85149).
5. L3 Chat must implement a never-reset continuous conversation thread, with core responsibility of interpreting intent → producing Task Card → mounting to transaction area → human confirmation → pushing to Agent → returning execution results.
6. Agent execution flow must be displayed in real-time at the top of the center view (Agent name + tool name + progress bar + status light + fingerprint chain + gate status).
7. L3 must handle changes hierarchically based on impact scope: architecture-level changes (cross-territory) → trigger approval flow, small-scope changes (single territory 2-5 files) → direct execution, single-file changes → auto-execute without confirmation.
8. `gate_chain.py` and `tool_ring.py` under `app/praxis/` must adopt bridge pattern, must not copy existing `app/services/` implementation.

## Specifications

- Transaction area card fields: number, intent summary, target Agent, impact scope (mild/moderate/severe/architecture-level), estimated steps, expand to show full Task Card
- Dispute review mode display: dispute file and line numbers, Agent A vs B each position+rationale+territory, [Adopt A]/[Adopt B]/[Manual Intervention]/[Mark False Positive] buttons
- Button decisions written to gate: Adopt A → G3 allows A's changes, Adopt B → opposite, Manual Intervention → open sandbox editor, Mark False Positive → dispute recorded for reputation adjustment
- Sandbox Diff dual view: top half = Agent isolated sandbox Diff (real-time, not yet landed), bottom half = landed Diff (editable, file tree linked when editing)
- Agent unit status bar display: Agent name + status light + reputation score + status (active/waiting/ready) + territory path + intra-unit rule hints
- Extension interface: [+ Add Unit] button, after adding, unit tab appears at bottom (#1/#2/#3...), each unit has independent three Agents, shares Ring Ω
- Window loading: development `python run.py` (browser DevTools), desktop `python run.py --gui` (pywebview native window)
- `app/praxis/` file structure: bridge.py/l3_engine.py/gate_bridge.py/tools.py/tool_bridge.py/task_card.py/transaction.py/dispute.py/territory.py + ui/index.html/praxis.css/praxis.js

## Exclusions

- Stacked icons on the right side of the menu bar: excluded, user explicitly requested "nothing else on the right side"
- Single column layout / no degradation below 900px: excluded (minimum window 900px, <900px right column collapses to bottom popup panel)
- Default pywebview window size < 1280x800: excluded
- Portal and Praxis sharing GateChain/ToolRing implementation files (copying instead of bridging): excluded
