---
fonds: DESIGN
series: Praxis-v1
title: G5 Gate Definition + Tool Mapping Audit
status: Pending Implementation
relations: [ARCHIVE-design-005, ARCHIVE-design-001]
---

# G5 Gate Definition and Tool Mapping Audit

## Core Decision

Define the trigger conditions and decision matrix of the G5 report judgment gate, audit the mapping relationship between PRAXIS_TOOLS and the actual NOMOS toolset.

## Design Rules

1. G5 trigger condition: triggered when any of G1-G4 returns non-`pass`, composite score based on violation severity + Agent reputation + frequency of similar recent violations.
2. G5 three outputs: `pass` (no report) / `report` (report to L3) / `block` (force block).
3. `app/services/gate_chain.py` must add a new `G5 = "gate_5_cross_unit"` entry.
4. Praxis must wrap existing tools, not re-implement them (existing tools get Praxis wrapper, new tools created as needed).
5. MVP 5 tools must correspond to the actual NOMOS toolset, `read_fingerprint` needs a new Ring 1 lookup interface.

## Specifications

- G5 decision matrix:
  - G4 triggered + Agent reputation < 0.7 → `block`
  - G3 triggered + first occurrence → `report`
  - G3 triggered + same Agent same tool > 3 times within 5 minutes → `block`
  - G2 triggered → `block`
  - G1 triggered → `block`
  - Single violation + high reputation Agent > 0.9 → `pass` (write audit log but do not interrupt workflow)
- GATES dictionary definition location: `app/services/gate_chain.py`
- MVP 5 tool mapping:
  - `read_file(0)`: calls VS Code `read_file` (Gate G1+G2)
  - `grep_search(0)`: calls VS Code `grep_search` (Gate G1+G2)
  - `replace_string_in_file(1)`: calls VS Code `replace_string_in_file` (Gate G1+G2+G3+G4)
  - `run_in_terminal(1)`: calls VS Code `run_in_terminal` (Gate G1+G2+G3+G4)
  - `read_fingerprint(0)`: new Ring 1 fingerprint reverse lookup interface (Gate G1+G2)
- Missing items that must be created:
  - `app/services/gate_chain.py` containing G5 (create if not exists)
  - `app/services/tool_ring.py` (Ring 1) MVP uses dict simulation
  - `PRAXIS_TOOLS` runtime dictionary (create if not exists)
  - `authorization.py` danger_level → scopeAllows bridge layer (create if not exists)

## Exclusions

- G5 left undefined as reserved field: excluded (multiple references need to be completed before implementation)
- G5 only pass/block binary state: excluded (needs three states pass/report/block)
- Re-implementing GateChain under `app/praxis/`: excluded (only use bridge wrapper)
