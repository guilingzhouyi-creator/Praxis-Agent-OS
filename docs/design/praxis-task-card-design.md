---
fonds: DESIGN
series: Praxis-v1
title: Task Card UX Spec
status: Pending Implementation
relations: [ARCHIVE-design-004]
---

# Task Card UX Spec — Intent Card Creation Entry Design

## Core Decision

Define Task Card's three-layer input mode (free/template/expert), MVP data structure, and LLM parsing strategy.

## Design Rules

1. User creating a Task Card must satisfy four goals: zero learning cost, structured output, progressive enhancement, no conversation trap.
2. Must provide three-layer input mode: free mode (single-line text → parse → confirm), template mode (`#` triggers search or button opens selector), expert mode (direct YAML editing).
3. MVP phase must not use LLM for intent parsing, must use keyword rule `parse_intent_to_task_card()`.
4. Task Card creation entry must replace the chat input box, does not imply "conversation".
5. After P1, LLM-enhanced parsing may be added (call DeepSeek API to parse domain/context_refs/tools_hint from free text).

## Specifications

- `TaskCard` MVP fields: `intent` (required, 1-2 sentences), `domain` (optional, L3 auto-inferred), `context_refs` (optional, default []), `tools_hint` (optional, default []), `priority` (optional, 1-5 default 3)
- MVP `parse_intent_to_task_card()` implementation: pure keyword rule `infer_domain(intent)`, returns TaskCard(intent=intent, domain=domain, context_refs=[], tools_hint=[], priority=3)
- Template mode trigger: type `#` triggers search or click `[From Template...]` button
- Template selector interaction: search box → matching template list → select → fill fields → [Use This Template]
- Parse result preview: card-style structured view, displays intent/domain/context_refs, [Confirm] / [Redescribe]
- Consistency with non-conversation premise:
  - No bubbles, use cards → Task Card preview = card-style structured view, not chat bubble
  - No conversation, use intents → input is "describe intent", not "send message"
  - No compression, use eviction → Task Card submitted and archived, does not participate in context window

## Exclusions

- Pure template selector (Plan B): excluded (requires maintaining template library, user's first action is typing not selecting a template)
- Pure structured work order form (Plan C): excluded (3+ field form discourages new users)
- Using LLM for parsing in MVP phase: excluded (can be introduced after P1)
