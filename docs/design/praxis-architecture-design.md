---
fonds: DESIGN
series: architecture
item_no: 002
type: design
date: 2026-07-22
timestamp: 2026-07-22T19:00
author: L3
keywords: [NOMOS, Praxis, architecture, Agent OS, federalism]
relations: [ARCHIVE-design-001]
debts: []
---

# Praxis Complete Architecture — Agent OS Federalism

## Core Decision

Define the conceptual system of Agent OS federalism, five-layer architecture, L3 dual modes, Agent Cell structure, and Scout reconnaissance groups.

## Design Rules

1. Terminology must be precise: Human (final decision maker), L3 Meta-Coordination (central decision layer), Agent Cell (autonomous federation), Peer Agent (equal peers), Scout (read-only reconnaissance group), Constitution (.nomos-rules.md supreme constraint).
2. Prohibit use of SubAgent, parent Agent, Orchestrator, Worker, spawn — replace with Scout, delegator, L3 Meta-Coordination, Peer Agent, delegate/route respectively.
3. L3 must support two modes: Assembly Mode (default, intent → decompose into multiple cards → Agent claim → convergence) and Direct Mode (human specifies Agent → direct assignment).
4. Core constraints spanning both modes are not bypassable: GateChain G1-G5, cross-review, audit log.
5. Three Agents within an Agent Cell must be equal peers, no master-slave relationship, each autonomous within its territory.
6. Cross-territory operations must be approved by L3.
7. Scout must be a read-only, stateless, depth=1 investigation unit, cannot write files, cannot make decisions.
8. Human must perform 5 things: express intent, confirm Task Card, observe execution, adjudicate disputes, merge code.
9. Humans are forbidden from writing code, reviewing code, assigning tasks, tracking dependencies, checking security — these are done by Agent/Scout/L3.

## Specifications

- L3 Assembly Mode flow: human intent → NLP interpretation → decompose into Task Cards → transaction area display → human confirmation → rule engine routing → execution → cross-review → convergence
- L3 Direct Mode granularity: coarsest (unspecified → Assembly Mode) / medium (unit only → L3 selects Agent) / finer (unit+Agent → L3 assembles card) / finest (all specified → skip reconnaissance and plan)
- Agent Cell unit: 3 Peer Agents + L3 coordination, Agent A (routes/params/middleware/auth/i18n), Agent B (pages/services/visa/cache/config), Agent C (tests/security/nomos_mcp/memories/scripts)
- Scout attributes: read-only, no identity, no territory, depth=1, no reputation, template pool extensible
- Cross-review automatic flow: change lands in sandbox area → notify other Agents → review → fix → resubmit → merge after all pass
- Dispute handling: two Agents disagree → dispute card reported to transaction area → human adjudication
- L3 boundaries: responsible for interpretation/decomposition/public display/routing/Agent matching/convergence/dispute reporting/cross-unit coordination; does not decide for human, does not write code or review for Agents, does not adjudicate disputes for human, does not define territory boundaries (defined by Constitution)
- GateChain G1-G5 strict order: G1 territory validation → G2 permission validation → G3 parameter validation → G4 reputation validation → G5 cross-unit/production approval

## Exclusions

- SubAgent model: replaced by Scout (Scout read-only, does not replace execution)
- Orchestrator centralized scheduling: replaced by L3 Meta-Coordination (L3 is decision layer, not orchestrator)
- Conversational Chat design: L3 Chat is the interaction interface of the central decision layer, not chat bubbles (never reset, layered memory)
- LLM adjudicating disputes: humans must ultimately adjudicate disputes
