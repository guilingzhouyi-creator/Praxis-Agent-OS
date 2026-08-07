"""Guard: params library hygiene — name uniqueness, alias alignment, orphan baseline.

Scans src/l1/kernel/params/ for:
  - constant names defined in more than one module (hard gate)
  - known duplicate pairs staying aligned (alias regression gate)
  - defined-but-never-referenced constants staying within the known-debt
    baseline (shrink-only ledger, like the mypy-debt gate)
"""

from __future__ import annotations

import ast
import functools
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PARAMS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "l1" / "kernel" / "params"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Known-dead orphan ledger (2026-08-07 audit) ──
# Zero references anywhere outside their own definition line. SHRINK this
# set as debt is cleaned; any dead constant NOT listed here fails the test.
BASELINE_DEAD_ORPHANS: frozenset[str] = frozenset(
    {
        # agent.py (33)
        "AGENT_STATUS_BOOTING_LABEL",
        "BOOT_AUTO_EMIT_SIGNAL",
        "BOOT_CONSTITUTION_CHECK",
        "BOOT_MEMORY_WARM_TOKENS",
        "CARD_GATE_MEDIUM_MAX_FILES",
        "CARD_GATE_MEDIUM_MAX_LINES",
        "CARD_GATE_SMALL_MAX_FILES",
        "CARD_GATE_SMALL_MAX_LINES",
        "CELL_SCOUT_ROLE",
        "COMM_TRACE_SAMPLE_RATE",
        "CONSTITUTION_SANDBOX_KEYWORD",
        "CONVENTION_ARCHIVE_IMPORTANCE",
        "CONVERGENCE_ANSWER_TRUNC",
        "CONVERGENCE_DOC_TRUNC",
        "ISSUE_AUTO_CONSENSUS",
        "KEEPALIVE_TASK",
        "L3A_MEMORY_TYPE",
        "LOOP_COARSE_REPEAT_STOP",
        "LOOP_COMPACTION_THRESHOLD",
        "LOOP_CONTINUATION_NUDGE",
        "LOOP_FOLD_MAX_CHARS",
        "LOOP_STEP_RESULT_TRUNC",
        "LOOP_TOKEN_ESTIMATION_FACTOR",
        "LOOP_TOOL_REPEAT_STOP",
        "LOOP_TOOL_SEARCH_MAX",
        "LOOP_VERIFY_CADENCE",
        "MEMORY_CONTEXT_MAX_TOKENS",
        "R4_REDISTILL_COOLDOWN",
        "R4_RETRIEVAL_TOP_K",
        "SCOUT_DIR_LIMIT",
        "SCOUT_GREP_MAX",
        "SCOUT_GREP_OUTPUT_TRUNC",
        "SESSION_COMPRESSION_THRESHOLD",
        # allocator.py (1)
        "ALLOCATOR_ALLOCATE_AMOUNT",
        # api.py (12)
        "ANTHROPIC_API_VERSION",
        "CHANNEL_RING_GET_TIMEOUT",
        "CHANNEL_RING_PUT_TIMEOUT",
        "DEVICE_RATE_LIMIT_STORAGE",
        "ENV_DEFAULT_CELL",
        "ENV_DISCOVERY_PORT",
        "FILESYSTEM_RATE_LIMIT_DEFAULT",
        "HTTP_CALLBACK_TIMEOUT",
        "IPC_KEEPALIVE_INTERVAL",
        "LLM_RATE_LIMIT_DEFAULT",
        "PAL_DEFAULT_TIER",
        "SEARCH_MAX_WORKERS",
        # kernel.py (12)
        "CADENCE_MAX_ATTEMPTS",
        "CADENCE_MAX_STEPS",
        "EVENT_HEARTBEAT_SENDER",
        "EVENT_STORE_SENDER",
        "HEARTBEAT_INTERVAL",
        "STAGNATION_OSCILLATION_CYCLES",
        "SWAPPER_COMPACT_MIN_ENTRIES",
        "SWAPPER_COMPACT_MIN_PER_AGENT",
        "SWAPPER_COMPACT_QUERY_LIMIT",
        "SWAPPER_COMPACT_TAGS",
        "SWAPPER_PRESSURE_MEDIUM",
        "SWAPPER_RECALL_LIMIT",
        # sync.py (1)
        "MUTEX_POLL_INTERVAL",
        # system.py (32)
        "BOOT_VFS_TEMP_PATH",
        "CARD_QUEUE_CELL_MAX",
        "CELL_EVENTS_LIMIT",
        "CI_PIPELINE_CACHE_TTL",
        "CI_REVIEW_AUTOTEST_CACHE_TTL",
        "CONTEXT_BUILD_MIN_TOKENS",
        "CRON_DEFAULT_PRIORITY",
        "DIRECT_SESSION_TIMEOUT",
        "ERROR_BUS_DEDUP_WINDOW",
        "FAULT_AUTONOMOUS_RECONNECT_INTERVAL",
        "IRQ_PRIORITY_LEVELS",
        "MEMORY_BUILD_CONTEXT_ENTRIES",
        "MEMORY_GRAPH_LLM_TIMEOUT",
        "MEMORY_ID_HASH_MOD",
        "MEMORY_LOG_QUERY_LIMIT",
        "MEMORY_PAGER_RECALL_LIMIT",
        "MEMORY_RECALL_DEFAULT_LIMIT",
        "PERMISSION_DEFAULT_POLICY",
        "PERSIST_EXPORT_INTERRUPT_LIMIT",
        "PROFILE_REFINE_TIMEOUT",
        "REQUEST_POOL_CAPACITY",
        "SCOUT_POOL_MIN_IDLE",
        "SEQ_MONITOR_PATH",
        "SHELL_HISTORY_MAX_LIMIT",
        "SKILL_LEAN_CASES_LIMIT",
        "TLB_CLEARANCE_FALLBACK",
        "TOOL_SCOUT_MAX_STEPS",
        "TOOL_SCOUT_RUN_TIMEOUT",
        "TUI_CARD_LIST_LIMIT",
        "TUI_CARD_LIST_LIMIT_WIDE",
        "TUI_MAX_EVENTS",
        "TUI_REFRESH_MS",
        # tool.py (8)
        "TOOL_AGENT_COORD_TIMEOUT",
        "TOOL_CARGO_SEARCH_TIMEOUT",
        "TOOL_DOCKER_TIMEOUT",
        "TOOL_FILE_LOCK_TTL",
        "TOOL_L3_LIST_LIMIT",
        "TOOL_MEMORY_RECALL_LARGE",
        "TOOL_MEMORY_RECALL_LIMIT",
        "TOOL_PING_TIMEOUT",
    }
)


@functools.lru_cache(maxsize=1)
def _module_names() -> dict[str, set[str]]:
    """Map params module → defined UPPER_SNAKE constant names (AST scan)."""
    out: dict[str, set[str]] = defaultdict(set)
    for path in sorted(PARAMS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        out[path.stem].add(t.id)
    return dict(out)


@functools.lru_cache(maxsize=1)
def _corpus() -> str:
    """Concatenated source of src/ + tests/ (params included — alias roots alive).

    Excludes this guard file itself — its ledger would otherwise count as a
    reference for every listed name.
    """
    parts: list[str] = []
    for root in (REPO_ROOT / "src", REPO_ROOT / "tests"):
        for path in root.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
    return "\n".join(parts)


def test_no_duplicate_names_across_modules() -> None:
    """A constant name must be defined in exactly one params module."""
    byname: dict[str, list[str]] = defaultdict(list)
    for mod, names in _module_names().items():
        for n in names:
            byname[n].append(mod)
    dups = {n: ms for n, ms in byname.items() if len(ms) > 1}
    assert not dups, f"constants defined in multiple modules: {dups}"


def test_known_duplicate_pairs_stay_aligned() -> None:
    """The unified duplicate pairs must stay value-aligned (alias pattern)."""
    from l1.kernel.params.allocator import ALLOCATOR_DEFAULTS
    from l1.kernel.params.api import GIT_TIMEOUT, NOTIFY_WEBHOOK_TIMEOUT, TOOL_WEBHOOK_TIMEOUT
    from l1.kernel.params.system import RING1_CAPACITY, RING2_CAPACITY, RING3_CAPACITY
    from l1.kernel.params.tool import TOOL_GIT_TIMEOUT

    # Unification 2026-08-07: GIT_TIMEOUT / NOTIFY_WEBHOOK_TIMEOUT are aliases.
    assert GIT_TIMEOUT == TOOL_GIT_TIMEOUT, "GIT_TIMEOUT must alias TOOL_GIT_TIMEOUT"
    assert NOTIFY_WEBHOOK_TIMEOUT == TOOL_WEBHOOK_TIMEOUT, "NOTIFY_WEBHOOK_TIMEOUT must alias TOOL_WEBHOOK_TIMEOUT"
    # Ring capacities: AllocatorDefaults must track the system constants.
    assert ALLOCATOR_DEFAULTS.ring1 == RING1_CAPACITY
    assert ALLOCATOR_DEFAULTS.ring2 == RING2_CAPACITY
    assert ALLOCATOR_DEFAULTS.ring3 == RING3_CAPACITY
    # API_GATEWAY_DEFAULT_PORT (dead twin) was deleted — must not resurface.
    import l1.kernel.params.api as _api

    assert not hasattr(_api, "API_GATEWAY_DEFAULT_PORT"), "dead twin API_GATEWAY_DEFAULT_PORT resurfaced"


def test_orphan_constants_do_not_grow() -> None:
    """Dead constants must stay within the known-debt ledger (shrink-only)."""
    corpus = _corpus()
    dead: set[str] = set()
    for n in set().union(*_module_names().values()):
        # count <= 1 → the only occurrence is the definition line itself
        if corpus.count(n) <= 1:
            dead.add(n)
    newcomers = dead - set(BASELINE_DEAD_ORPHANS)
    assert not newcomers, f"new orphan constants (add to BASELINE_DEAD_ORPHANS or delete them): {sorted(newcomers)}"
