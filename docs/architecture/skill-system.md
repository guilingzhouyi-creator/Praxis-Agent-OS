# Skill System — Complete Architecture

The skill system is the Agent OS's mechanism for capturing, evolving, and
injecting reusable procedural knowledge. It spans all five layers: a kernel
registry (L1), an evolution engine (L3 memory), retrieval/ranking (L3), three
injection consumers (L3 agent loop, L3 hook, L3 tool), and governance
surfaces (L2 shell, L4 API, VFS).

```
                       ┌──────────────────────────────────────────────┐
                       │  L1 SkillManager (registry, single truth)     │
                       │  register/create/update/delete (write gate)   │
                       │  cell_skill_map (per-Cell whitelist)          │
                       │  offensive_policy (posture gate)              │
                       │  revision counter (cache invalidation)        │
                       └───────▲──────────────────────────┬───────────┘
                               │ register/persist          │ read
                ┌──────────────┴───────────────┐   ┌───────▼──────────────────┐
                │  Persistence                 │   │  Retrieval (L3)           │
                │  config/skills/ (builtin,RO) │   │  TfIdf / embedding rank   │
                │  .praxis/skills/evolved/     │   │  card:<nature> tag filter │
                │  .praxis/skills/lean/        │   │  audience routing          │
                │  SKILL.md frontmatter round- │   │  posture gate              │
                │  trip (name/desc/tags/tools/ │   └───────▲──────────────────┘
                │  variables/posture)          │           │ candidates
                └──────────────┬───────────────┘           │
                               │                           │
                ┌──────────────▼───────────────────────────▼──────────────┐
                │  L3 R4Agent (evolution engine, tick-driven)              │
                │  evolve_skill (LLM architect)        → register + persist│
                │  _process_failure_traces            → lean_case skills   │
                │  _generalize_lean_cases (≥5/tool)   → lean_<tool>_lessons│
                │  _prune_stale_skills (TTL)          → archive+delete     │
                │  _curate_skills (contrib = useful/injected, cap)         │
                │  reflect_failure (Reflexion why/fix/pattern)             │
                │  graph linkage (R5: refines/depends_on edges)            │
                └──────────────┬───────────────────────────────────────────┘
                               │ inject (token-budgeted)
                ┌──────────────▼───────────────────────────────────────────┐
                │  Consumers (3 paths)                                     │
                │  ① AgentLoop._inject_extra_context → system prompt       │
                │  ② SkillCatalogHook.session_start → session catalog      │
                │  ③ use_skill tool → expanded $VARIABLES message          │
                │  + manual surfaces: VFS /skills, worker_pool boot manual │
                └──────────────────────────────────────────────────────────┘
```

## 1. Registry (L1, `src/l1/kernel/skill.py`)

### 1.1 Skill record

A skill is a dict with: `name`, `description`, `prompt` (the procedural
body), `rules` (DO/DON'T), `procedures`, `knowledge`, `tags`,
`allowed_tools`, `variables` ($VAR placeholders in prompt), `posture`
(productive|offensive), `source`, `loaded_at`, `last_used`, `useful_count`,
`inject_count`, `builtin`, `dependencies`/`dependency_kind`,
`disable_model_invocation`.

### 1.2 Write gate (`authorize_write`)

External callers (L2 shell, L4 API) MUST pass an explicit identity
(`agent_id`/`role`); identity-less writes are allowed only with
`internal=True` from system processes (boot loading, R4Agent
evolution/pruning). Policy is ring/role based (`skill.write_min_ring`,
`skill.write_roles`), runtime-overridable via `set_write_policy()`.

### 1.3 Per-Cell whitelist (`cell_skill_map`)

`bind_skill(cell_id, name)` binds a skill to a Cell; `skills_for_cell()`
returns the set. Injection paths filter by `cell_id`; unbound Cells fall
back to the global pool. Evolved skills are auto-bound to their originating
Cell ("演化即回灌").

### 1.4 Posture gate (offensive/productive)

Default-deny: `SKILL_OFFENSIVE_ENABLED=True` + `SKILL_OFFENSIVE_AUTHORIZED_NATURES=("offensive",)`.
`offensive_authorized(nature)` consulted by all three injection consumers
and `use_skill`. `_normalize_posture()` maps invalid values to the safe
default — neither LLM output, frontmatter, nor callers can escalate.

### 1.5 Revision & audit

Every structural mutation bumps `revision()` (R4Agent cache invalidation)
and emits `EVENT_SKILL_MUTATED` via `get_bus().emit_event` (best-effort,
never breaks the mutation).

## 2. Persistence & round-trip

- **SKILL.md**: YAML frontmatter (`name/description/tags/allowed_tools/
  variables/posture/dependencies/dependency-kind/disable-model-invocation`)
  + body as the prompt. `_load_markdown()` restores ALL fields;
  `_persist_skill_md()` writes them back — never add a persisted field to
  one side without the other, or skills degrade to tag-less form after
  reboot.
- **Sources**: `config/skills/` (21 built-in, read-only), evolved dirs
  (project: `.praxis/skills/evolved/`; global: `data_dir/skills/evolved/`),
  lean dir (`.praxis/skills/lean/`, failure traces).
- **Built-in contract** (`tests/infra/test_skill_contracts.py`): ≥7 skills,
  full frontmatter, 12 universal-principle sections, no project-specific
  path literals, no constitutional violations, `disable-model-invocation:
  true` (user-invoked only), explicit valid posture. Built-ins are
  immutable even for internal processes.

## 3. Evolution engine (L3 R4Agent)

Driven by `tick()` (background loop, gated by GateChain identity +
constitution). Skill-relevant steps:

1. **Failure traces → lean cases**: `tool_pipeline` records failures via
   `track_tool_failure(agent_id, tool, args, error, turn_log, domain, nature)`
   → JSON traces in lean dir → `_process_failure_traces()` creates
   `lean_<agent>_<tool>_<err>` skills tagged `[lean_case, failure, agent,
   tool, card:<nature>]` (dedup: exact name or `dedup_key_` prefix).
2. **Generalization**: ≥`R4_LEAN_GENERALIZE_THRESHOLD` cases for one tool →
   `lean_<tool>_lessons` (rule-based baseline or LLM summary; idempotent via
   case fingerprint).
3. **LLM evolution**: `evolve_skill(intent, cell_id, scope, extra_tags)` —
   skill-architect prompt → JSON skill def → `sm.create()` (with posture
   normalization) → bind to Cell → archive pre-version (`fonds="skills",
   series="evolved"`) → persist SKILL.md → R5 graph edges (`refines` old→new,
   `type_chain` via `remember_hook`). Fails safe to rule-based fallbacks
   (e.g. `agents_md._fallback_generic_skill`).
4. **TTL prune** (`_prune_stale_skills`): evolved skills past
   `SKILL_TTL_DAYS` (7d) → archive (`series="pruned"`) + delete. Each
   recorded use (`useful_count`) extends the effective TTL by
   `SKILL_TTL_EXTEND_PER_USE` (1h), and injection refreshes `last_used` —
   active skills survive the prune.
5. **Curation** (`_curate_skills`): `contrib = useful_count /
   max(inject_count, 1)`; retire under-performers (≥`R4_CONTRIB_MIN_TRIALS`
   trials, contrib < `R4_CONTRIB_MIN_RATIO`), archive
   (`series="retired"`/`"evicted"`), enforce `SKILL_LIBRARY_MAX` cap.
   Never touches built-in or lean_case skills.
6. **Reflexion** (`reflect_failure`): LLM distills why/fix/pattern per tool
   into the reference channel (non-blocking).

## 4. Retrieval & ranking (L3, `skill_retriever.py` + `r4_skill_feedback.py`)

- **`get_evolved_skills(agent_id, cell_id, limit, graph_diffusion, tags)`**:
  filters agent tag (strict membership), Cell whitelist, card-tag OR-match
  (`_passes_card_tags`: untagged universal, `card:*`-tagged gated); graph
  diffusion (BFS along R5 edges) with linear fallback; cached on
  `revision()`.
- **`retrieve_skills(query, ..., tags)`**: tfidf (or embedding backend)
  rank of candidates by description+prompt cosine similarity, min-score
  floor, fallback to loaded-at order. Backends pluggable:
  `set_backend()` / config `skill.retriever_backend`; unknown names degrade
  to tfidf.
- **`get_lean_cases(agent_id, tool_name, cell_id)`**: lean-case injection,
  Cell-whitelist filtered, shared cache with `get_lean_case_names()`.

## 5. Injection consumers

### 5.1 AgentLoop (`_inject_extra_context`)

Token-budgeted (`LOOP_CONTEXT_BUDGET_SKILL`), gated by
`prompt.inject.skills`:
1. lean cases (`get_lean_cases`, budgeted, truncated fallback)
2. evolved skills (`retrieve_skills` with `self.task` + card-tag boost +
   `card:<nature>` tags from the driving card, `LOOP_EVOLVED_SKILLS_LIMIT`)
   — filtered by `skill_visible` (audience) and posture gate
3. injection feedback: `last_used` refresh + `inject_count` bump (feeds
   curation denominators)

### 5.2 SkillCatalogHook (`session_start`)

Injects up to `SKILL_CATALOG_HOOK_LIMIT` skill summaries into the session
system prompt; hides offensive-posture skills while the gate is enabled;
built-ins take priority (auto-activation toggleable via
`skill.auto_activate_builtin`, default `SKILL_AUTO_ACTIVATE_BUILTIN`).

### 5.3 `use_skill` tool (`_skills.py`)

Explicit invocation: audience check → posture gate (reads `_card_nature`
from tool args, injected by `AgentLoop._wrap_handler`) → prompt expansion
of `$VARIABLES`. Refuses offensive skills without authorized card nature.

### 5.4 Manual surfaces

- **VFS**: `/skills` virtual mount (`skill_vfs_content`, per-skill read).
- **worker_pool boot**: loads up to 20 skills into the agent's context
  register as a "manual".
- **L3A `agents_md`**: handbook generation evolves a reusable skill via
  `evolve_generic_skill` (global scope, rule-based fallback).

## 6. Governance surfaces

- **L2 shell `/skills`**: list/lean/get (public); create/update/delete/
  reload/evolve/permissions/retriever (developer-gated via `--role`).
- **L4 API** `/api/v2/skills/*`: list/get/create/update/delete/reload/
  permissions/retriever/offensive-policy (GET+POST, developer-gated).
- **Config**: `params/` defaults ← `settings_center` L2 ← `praxis.yaml`
  `skill:` section (retriever_backend, evolve_scope, offensive_enabled,
  offensive_natures, cell.skills).

## 7. Feedback loop (self-improvement)

```
inject (5.1) → inject_count++, last_used refresh
    → use_skill / catalog exposure
    → tool failure → trace file → lean_case skill
    → ≥5 per tool → generalized lessons
    → LLM evolve (card intent) → evolved skill, bound to Cell
    → TTL prune / curation retire (archived) → loop
```

## 8. Key invariants

1. Round-trip integrity: frontmatter ↔ registry fields stay in sync.
2. Write gate: never weaken — it protects Cell bindings + TTL prune deletes.
3. Default-deny posture; `_normalize_posture` blocks escalation.
4. Built-in skills are immutable and user-invoked only.
5. All graph/archive calls are non-blocking (graph defaults off).
6. Injection refreshes `last_used` so active skills survive TTL prune.
7. Revision-based caching: SkillManager revision is the cache key for all
   R4Agent injection caches.
