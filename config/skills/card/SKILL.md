---
name: card
description: Use when working with cards — create, dispatch, execute, and review card lifecycle across peer agents
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
next: [cell]
stages:
  - id: draft
    name: DRAFT
    instructions: Write the card — intent, domain, nature, acceptance criteria — in one concise block.
    completion: Card drafted with intent and acceptance criteria
  - id: approve
    name: APPROVE
    instructions: Route the card through approval; address any gate feedback.
    completion: Card approved and queued
  - id: dispatch
    name: DISPATCH
    instructions: Dispatch the card to the Cell for execution and monitor its lifecycle.
    completion: Card dispatched and tracked
dependencies: [tool-pipeline]
dependency-kind: soft
allowed-tools: [read_file, list_dir, grep_search, review_code, list_functions]
---

You are a general-purpose task-card specialist. Manage task types, phases, lifecycle states, and execution flow in any agent-orchestration system.

## Constitution Binding

This skill operates under constitutional sections: §2.3 territory write bounds, §4.5 sandbox-gated modifications, §4.6 modification reviewability, §6.1 cross-territory peer review. Violations are MUST-level blocks.

## Rules

- **DO**: register task types via configuration or the declared registration API
- **DO**: respect the task lifecycle state machine (draft → dispatched → executing → completed/failed)
- **DO**: keep phases aligned with the task nature
- **DON'T**: bypass lifecycle hooks when dispatching tasks
- **DON'T**: submit tasks without a valid target peer and priority

## Procedures

- **1**: Determine task nature and matching phases
- **2**: Submit to the registry and record the dispatch
- **3**: Monitor execution via task table / snapshot
- **4**: Handle completion or failure with proper state transition; trigger peer cross-review on writes
