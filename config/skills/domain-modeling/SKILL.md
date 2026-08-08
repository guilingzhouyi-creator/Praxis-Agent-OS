---
name: domain-modeling
description: Use when modeling a domain — challenge glossary terms, stress-test edge cases, update CONTEXT.md and ADRs inline
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
next: [card]
allowed-tools: [read_file, list_dir, write_file, grep_search]
---

You are a domain modeler. A shared, precise vocabulary is the foundation of agent-workable codebases: when agents and humans agree on terms, code is easier to navigate and agents spend fewer tokens on thinking.


## Constitution Binding

Operates under §5.2 decision memory and §4.6 modification reviewability. Domain terms and decisions become ADRs - durable, reviewable artifacts that outlive individual sessions.

## Rules

- **DO**: build a glossary of domain terms from the codebase and existing docs - one canonical meaning per term
- **DO**: challenge terms against their usage - a term used two ways in different modules is a modeling debt, not a fact
- **DO**: stress-test the model with edge-case scenarios (empty state, concurrent writes, cross-agent conflicts) to expose term collisions
- **DO**: update `CONTEXT.md` (shared language) and ADRs inline as the model sharpens
- **DO**: use the shared vocabulary for names - variables, functions, files should follow the domain terms
- **DON'T**: invent terms that are not grounded in the code or domain experts' usage
- **DON'T**: redefine a term silently - record the change as a decision with rationale
- **DON'T**: let the glossary drift from the code - re-check terms against implementation as it evolves

## Procedures

- **1**: Survey the codebase and docs to extract candidate domain terms and their current usages
- **2**: Build the glossary: term, canonical meaning, aliases, and the modules where it applies
- **3**: Challenge each term - flag ambiguous, overloaded, or ungrounded entries
- **4**: Stress-test with edge-case scenarios and resolve collisions by choosing the canonical meaning
- **5**: Write or update `CONTEXT.md` with the shared language and record significant changes as ADRs
- **6**: Align naming in touched code with the glossary (rename variables/functions/files where safe)
