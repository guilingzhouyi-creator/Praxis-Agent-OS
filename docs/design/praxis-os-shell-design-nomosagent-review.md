---
Fonds: REVIEW
File: architecture
Item: 001
Type: Review
Date: 2026-07-21
Timestamp: 2026-07-21T19:00
Author: NOMOSAgent
Keywords: [NOMOS, Praxis, OS Shell, review, cross-review]
Relations: [ARCHIVE-design-006]
Debts: []
---

# 🟢 NOMOSAgent Cross-Review of the Praxis Agent OS Shell Design

## Core Decision

The review confirms that the Agent OS Shell positioning upgrade and L3 two-phase model are correct, and raises 4 inquiries and 4 issues that must be resolved before implementation.

## Design Rules

1. L3 dialogue history must be stored in Portal SQLite (`nomos_l3_dialogues` table); when refeeding, only load the "last 20 entries + historical entries referenced by Ring 1" — must not duplicate with `memories/sessions/`.
2. File names under `app/praxis/` must reflect bridging rather than reimplementation — `gate_chain.py` → `gate_bridge.py`, `tool_ring.py` → `tool_bridge.py`.
3. The trigger conditions for G5 tri-state (pass/report/block) must be clearly defined in the D2 design task: pass=operation within territory executed directly, report=cross-territory boundary execution + notify L3, block=write to production data denied.
4. Windows must define a default size (1280×800), minimum width (900px), and a degradation strategy for <900px (right column collapses to a bottom popup panel).
5. L3 confirmation wait must define a state machine — timeout auto-cancel / intent card locked / modifiable only after confirmation.
6. L3 and Copilot roles must be separated: L3 is an independent module (meta-coordinator), Copilot is one of the Agents — must not be merged.

## Specifications

- L3 dialogue storage: Portal SQLite table `nomos_l3_dialogues`, refeed loads "last 20 entries + Ring 1 referenced entries", does not duplicate `memories/sessions/` (session archive=periodic summary, L3 dialogue=raw interaction records)
- Bridge file naming: `app/praxis/gate_bridge.py` (bridges `app/services/gate_chain.py`), `app/praxis/tool_bridge.py` (bridges `app/services/tool_ring.py`)
- G5 tri-state triggers:
  - 🟢 pass: Agent operates within territory
  - 🟡 report: Agent crosses territory boundary (execute + notify L3)
  - 🔴 block: Agent attempts to write production data (deny execution)
- Window specs: default 1280×800, min width 900px (center column at least 300px), <900px → right column collapses to bottom popup panel
- Role separation: L3 independent process/module, not bound to any Agent; Copilot is Agent A; 🟢 only Copilot annotated
- L3 confirmation wait state machine: timeout auto-cancel / intent card locked / modifiable only after confirmation
- MVP conditions unified: 9 conditions from design draft + 7 from roadmap → unified as 9 gate checks, add G8 (UI consistency), G9 (Agent panel status), coexistence verification

## Exclusions

- L3 dialogue stored in memory or file system: excluded (memory OOM risk, file concurrent write conflicts)
- Reimplementing GateChain/ToolRing under `app/praxis/`: excluded (should bridge existing `app/services/`)
- G5 only two-state (pass/block): excluded (needs tri-state pass/report/block with report intermediate state)
- Window shrinkable below 680px without restriction: excluded (min 900px, otherwise center column cannot display tool call cards)
- L3 and Copilot roles merged: excluded (L3 cannot be both referee and player)
