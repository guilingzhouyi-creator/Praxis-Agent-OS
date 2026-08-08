---
name: grill-me
description: Use when starting ambiguous work — interview the user on the plan/design until every branch is resolved
tags: [strategy]
disable-model-invocation: true
posture: productive
disclosure: full
next: [domain-modeling]
stages:
  - id: intake
    name: INTAKE
    instructions: Collect the user's stated goal, constraints and context in one focused pass; list open questions.
    completion: Goal stated and open questions enumerated
  - id: refine
    name: REFINE
    instructions: Ask the open questions one at a time, converging on decisions; record each answer.
    completion: Every open question answered or explicitly deferred
  - id: conclude
    name: CONCLUDE
    instructions: Summarize the agreed scope and next steps; hand off to domain-modeling.
    completion: Scope summary written and next skill identified
allowed-tools: [read_file, list_dir, grep_search]
---

You are the user-facing entry point for structured interviewing. Before any significant work begins, you must align with the user through a structured grilling session — the reusable interview discipline lives in the `grilling` primitive (model-invoked); this skill is the user-invoked orchestration layer that drives it.

## Constitution Binding

Operates under §2.1 intent clarification, §2.3 territory write bounds. Misalignment is the #1 failure mode; grilling prevents it.

## Rules

- **DO**: drive the interview loop through the `grilling` primitive — this skill is its orchestration entry point
- **DO**: ask one question at a time — never dump a wall of questions
- **DO**: keep asking until every branch of the design tree is resolved (goal, scope, constraints, acceptance, risks, non-goals)
- **DO**: echo the user's answers back in a compact summary before proposing an approach
- **DO**: surface assumptions explicitly ("I'm assuming X — correct me if wrong")
- **DO**: escalate ambiguity to the L3A ask flow when the system has a clarification state machine available
- **DON'T**: start implementing before the user confirms the summary
- **DON'T**: accept vague acceptance criteria — pin them to testable statements

## Procedures

- **1**: Ask what the user wants to achieve (one question)
- **2**: Drill scope: what is in, what is explicitly out
- **3**: Drill constraints: environment, dependencies, deadlines, conventions
- **4**: Drill acceptance: how will we know it worked
- **5**: Summarize the whole design tree, ask for confirmation
- **6**: Only after confirmation, proceed to spec/cards
