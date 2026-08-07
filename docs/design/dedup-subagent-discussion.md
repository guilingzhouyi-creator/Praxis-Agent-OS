# Dedup proposal: subagent implementations + assembly/discussion modules

Status: reviewed (2026-08-12). Audit + feasibility review. Executed so far:
test-suite dedup (`tests/l3/resource_buffer/` merged into
`tests/l3/cell/test_resource_buffer.py`, CI steps dropped) and the
`helpers.py` dead-import removal. No pool/assembly migration is planned — see
§2.5 verdict.

## 1. Scope

Two families of duplicated / overlapping code were identified while cleaning runtime
state. This proposal records the exact reference graph and a phased migration plan.
It is deliberately conservative: every candidate has live test coverage, so nothing
is deleted without a migration step.

## 2. SubAgent — three live implementations

All three run `AgentLoop` inside a `ThreadPoolExecutor` and expose some
`commission`/`pool`/`collect` shape. They differ in scope and spec model.

### 2.1 `src/l3/agent/subagent.py` — `SubAgent` (legacy, 128 lines)

- Synchronous single-shot runner (`run(task, tools)` → `SubAgentResult`).
- Callers:
  - `src/l3/tools/_subagent.py` — the `subagent_tool` (review/deploy/scout profiles)
  - `tests/l3/agent/test_subagent.py`
- Not wired into Cell or L3A delegation.

### 2.2 `src/l3/agent/subagent_*.py` — `SubAgentPool` (formal framework, ~1311 lines)

Files: `subagent_spec.py`, `subagent_task.py`, `subagent_dispatcher.py`,
`subagent_pool.py`, `subagent_framework.py`, `subagent_gate.py`, `subagent_merger.py`.

- Per-Cell pool with dual explore/execute buffers and `SUBAGENT_SESSION_TTL` history.
- Specs from `config/commands.yaml` + 8 built-ins (`security-auditor`,
  `code-reviewer`, `documenter`, `data-analyst`, `architect`, `helper`,
  `refactor-agent`, `fixer`).
- Territory / GateChain integration on commission.
- Callers: `src/l3/cell/__init__.py`, `src/l3/services/cell_orchestrate.py`,
  `src/l3/cell/components/cell_execute.py` (gate), tests `tests/l3/subagent/`.

### 2.3 `src/l3/cell/peers/l3a/subagent.py` — `L3ASubAgentPool` (297 lines)

- L3A-session pool singleton (`get_pool()`), two hardcoded specs
  (`card-planner`, `investigator`) in `_L3A_SPECS`.
- Group-based `collect(group)` with `as_completed`, custom `cardwrite` tool
  handler, `_extract_findings` (expect_keys), L3A prompt key.
- Callers: `src/l3/cell/peers/l3a/session.py`, `src/l3/cell/peers/l3a/__init__.py`,
  tests `tests/l3/l3a/`.

### 2.4 Overlap

`L3ASubAgentPool._run` superficially repeats what `SubAgentTask._run_agentloop`
does: build AgentLoop → register tools → run → collect a text answer. The
L3A version adds `expect_keys` extraction, the `cardwrite` handler, group
collect, and the L3A prompt key.

### 2.5 Feasibility review (2026-08-12) — the two pools are different runtimes

Deep-dive of the two execution paths shows the overlap is ONLY the
`AgentLoop()` / `add_tool()` / `run()` skeleton. The execution semantics,
tool authority, delivery, and buffer model diverge at every decision:

| Aspect | Cell `SubAgentPool` | L3A `L3ASubAgentPool` |
|--------|---------------------|----------------------|
| Role | Peer-Agent delegation inside a Cell | L3A session orchestration (subagent fan-out) |
| Tool binding | `_HANDLER_MAP` terminal-action handlers (`_term_handlers.py`: read_file/list_dir/bash → handle_*) | `tool_spec.get_tool().handler` ToolSpec registry + `register_func_handler` cardwrite override |
| Execution | `read_only` fast path = single `engine.generate()` (no AgentLoop) | always AgentLoop multi-step |
| Delivery | mailbox `CellMessage` (SUBAGENT_RESULT) to parent Peer, TTL session-history reuse | collected in-process by task-group, non-destructive `collect(group)` |
| Concurrency | dual explore/execute buffers; poll-with-timeout `collect(task_id)` then pop | `as_completed` group collection, `peek`, group lifecycle |
| Integration | Cell mailbox + territory/GateChain + post run | cardwrite → `CardRegistry`; `pipeline.bound` output clamp; strategy-config via `resolve_dict_with_strategy("l3a_subagent")` |

Key finding — **the two pools bind tools through different authorities**:
`SubAgentTask` resolves `read_file|grep|bash` to terminal-action handlers via
`l3/agent/_term_handlers._HANDLER_MAP`, while `L3ASubAgentPool` resolves
`read_file|grep|bash` to `l3/tool_system/tool_spec.get_tool().handler` (the
config-driven ToolSpec). These are not interchangeable: merging pools would
force one runtime onto the other's tool chain, mailbox model, and TTL/session
semantics, and silently change which authority executes a tool for cards sent
down the wrong path. `l3a/subagent.py` states the design intent explicitly:
*"All subagents run in L3A's own thread pool (not Cell SubAgentPool)"*.

**Verdict:**

- **Unify pools → rejected.** Merging would produce a god-pool that must carry
  mailbox delivery + dual-buffer + territory + read_only fast path (Cell) AND
  group collect + non-destructive state + cardwrite + expect_keys + L3A prompt
  (L3A). Both lifecycles are small and independent; a merged pool is strictly
  more complex and would need to back off one signature per patch. Treat
  Cell-SubAgent and L3A-SubAgent as two product surfaces that happen to share
  the AgentLoop primitive, not two copies of the same component.

- **Shared-runner extraction → LOW value / MISLEADING.** The "shared" slice is
  only `loop.add_tool(...)` calls and `loop.run(...)`. The surrounding
  tool-binding, delivery, and collection logic is different by design. A shared
  helper would have to accept 3-4 callbacks (handler-resolver, model resolver,
  text→findings normalizer, state writer) — at which point it is a parameter
  bomb that does not outweigh the ~200 duplicated skeleton lines; any shared
  change now double-risks two runtimes. The one genuinely shared piece —
  registering a single `ToolSpec` on an `AgentLoop` — should live as
  `AgentLoop.add_tool_spec(spec, handler=None)` and be used by both; that is the
  only extraction with positive ROI.

- **Legacy `SubAgent` → KEEP, not delete.** The `tools/_subagent.py` tool path
  runs with only `agent_id`, no Cell and no Pool ownership — Cell Delegation is
  not guaranteed to a `SubAgentPool` buffer. A pooled rewrite would have to
  spawn a standalone pool for the tool without a Cell context, adding a third
  ownership surface for ~40 lines of saving and no behavior change apart from
  extra latency. The legacy class is 128 lines, sync, pure; it is the *third*
  runtime (L2/cell tool sync commission). Remove it only if `subagent_tool` is
  re-architected onto group-style collect — a feature change, not a dedup.

**Revised plan for 2:**
1. Extract `AgentLoop.add_tool_spec()` — **DONE** (2026-08-12): `add_tool_from_spec(spec, handler=None, parallel_safe=None)` marshals
   name/description/parameters (list-of-ParamSpec or dict) + handler +
   parallel-safety; `SubAgentTask._run_agentloop` and `L3ASubAgentPool._run`
   both delegate. Side benefit: the Cell runner's raw `spec.parameters`
   (ParamSpec list) previously fed `add_tool(params.items())` and would have
   crashed on real registry specs — the shared marshaller fixes that. Two new
   unit tests in `tests/l3/agent/test_loop.py`; full runner green (1754 passed).
2. Keep three runtimes; document the divide (this table). No pool-to-pool
   migration. The original "three implementations" framing is superseded by
   "three **distinct-use** substrates that share the `AgentLoop` file", which
   dedup would not mean.
3. Remove the legacy `SubAgent` line from the dedup scope.

## 3. Assembly vs Discussion — two generations of the same concept

### 3a `src/l3/services/assembly.py` (218 lines)

`AssemblyMode` (start_issue / submit_proposal / challenge / respond / converge /
status) + Proposal/Challenge/Response/IssueDocument — the blank-Cell → proposals →
cross-exam → consensus → constitution flow.

Live call graph (as of 2026-08-12):
- `src/l3/cell/peers/l3a/helpers.py` **no longer imports it** — the former
  `from l3.services.assembly import AssemblyMode` was a dead import, shadowed by
  `from .types import AssemblyMode` (the routing enum); removed in the first
  dedup pass. Nothing else in `src/` references the module.
- `tests/l3/discussion/test_assembly.py` exercises it directly.

### 3b `src/l3/discussion/` (7 modules)

`IssueOrchestrator` / `DiscussionSession` / `AnswerSession` / `CellAnswerRepo` /
`AnswerAggregator` / `SupplementManager` / `ReportService` — cross-Cell issue →
answer → aggregation → report. Actively wired: `boot.py`, `lifecycle.py`,
`cell_execute.py`, `cell/__init__.py`, `l3a/__init__.py`, `l3a/helpers.py`,
`api_handlers_discussion.py`.

### 3c Naming collision hazard

`l3a/types.py:11` also defines `AssemblyMode(Enum)` (AUTO_APPROVE / CONFERENCE /
DEFAULT) — a routing mode unrelated to `services/assembly.py`'s class. Two same-named
types, one of which is only reachable via a dead import.

### 3.4 Recommendation

1. Remove the dead import in `helpers.py` — **DONE** (2026-08-12): the module
   now imports `AssemblyMode` from `.types`; the `l3.services.assembly` import
   is gone and the shadowed local import was deleted. `ruff` + infra tests
   clean.
2. Decide `services/assembly.py` fate:
   - Option A (preferred if the blank-constitution flow's semantics are folded into
     the issue/answer pipeline): delete `services/assembly.py` + `test_assembly.py`,
     migrate the `submit_proposal/challenge/respond` assertions into the discussion
     tests.
   - Option B (conservative): rename to `discussion/legacy_assembly.py`, mark
     deprecated, and land it once the L3A flow moves to `IssueOrchestrator`.
   - **DONE** (2026-08-12): **Option A**. `services/assembly.py` had zero
     production references in `src/` (only `tests/l3/discussion/test_assembly.py`
     exercised it; the lone `assembly_mode` hits in `boot.py`/`api_endpoints.py`
     are unrelated local wording). Deleted both files; its single assertion with
     real semantic value (`TerritoryConstitution.is_blank()`) was already
     covered by `tests/l1/test_constitution.py:34-41`. Removed the stale
     `("l3/discussion", "test_assembly")` entry from `tests/runner.py` BATCH_1.
     `tests/l3/discussion` + infra gates green.
3. Rename the `AssemblyMode` collision: keep `l3a/types.AssemblyMode` for the
   routing semantics, and document (in code) that `services/assembly.AssemblyMode`
   is the legacy discussion class.

## 4. Naming overlaps (low priority, document-only)

- `src/l1/kernel/ipc.py` vs `src/l3/bus/ipc.py` — kernel primitive vs L3 bus transport.
- `src/l3/memory/context.py` (`ContextManager`) vs `src/l3/cell/peers/l3a/context.py`
  (`ContextRegistry`) — two different "context" systems with the same file name.
- `src/l4/{rpc,sandbox,llm_worker}/server.py` + `l4/ws/ws_bridge.py` +
  `l4/sse/sse_bridge.py` — separate server entrypoints, different ports. No merge.

These are keep-as-is; they only matter when making a new `context`/`ipc`/`server`
file, to avoid importing the wrong one.

## 5. Verification gates for any change

```bash
python -m pytest tests/infra/test_layer_imports.py -q -p xdist -n 0
python -m pytest tests/infra/test_params_compliance.py -q
python -m pytest tests/l3/subagent/ tests/l3/l3a/ tests/l3/agent/ -q
python tests/runner.py
ruff check src/ tests/
```

## 6. Extra

- `tests/l3/cell/test_resource_buffer.py` is the single home for RingBuffer +
  ResourceAPI after merging the duplicate `tests/l3/resource_buffer/` directory.