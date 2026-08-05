"""Benchmark: realistic constantization refactoring card.

Scans for magic numbers, reads files, proposes constants.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from l1.kernel.params.agent import TERMINAL_MAX_WORKERS
from l1.kernel.params.system import SCOUT_POOL_MAX_PER_AGENT, SCOUT_POOL_MAX_TOTAL
from l3.agent.scout import get_pool
from l3.agent_terminal import reset_terminals
from l3.card.models import Card, CardMode, Phase, PhaseMode, Step
from l3.cell import get_cell, reset_cells

cell = get_cell("bench", ["/project"])
cell.add_agent("agent_a", role="http",     territory=["/project"], ring=1, max_scouts=4, auto_boot=True)
cell.add_agent("agent_b", role="business", territory=["/project"], ring=2, max_scouts=4, auto_boot=True)
cell.add_agent("agent_c", role="security", territory=["/project"], ring=3, max_scouts=4, auto_boot=True)

# Register bench agents in the kernel process table — the G2 identity gate
# requires every executing agent to exist as a process (boot does this for
# real agents; a standalone benchmark must do it itself).
from l1.kernel.process import get_table
for _name in ("scout_pool", "agent_a", "agent_b", "agent_c"):
    try:
        get_table().spawn(_name, role="agent", ring=1)
    except Exception:
        pass

# Register a stub LLM on the "llm" port — think steps drive AgentLoop which
# needs an LLM engine; a benchmark measures execution throughput, not model
# latency, so a fast stub keeps numbers deterministic without an ollama.
from l1.kernel.ports import register_port

class _BenchLLM:
    def context_window(self, cell_id: str = "", agent_id: str = "") -> int:
        return 8192
    def generate(self, prompt: str = "", system: str = "", **kwargs) -> dict:
        return {"content": "bench response", "tool_calls": []}
    def tool_use(self, prompt: str = "", system: str = "", tools=None,
                 **kwargs) -> dict:
        return {"content": "bench done", "tool_call_results": [],
                "turns": 1, "finish_reason": "stop", "context_trail": [],
                "tools_elapsed": 0.001}

register_port("llm", _BenchLLM())
# Poll for all agents to be ready instead of fixed sleep(0.2)
from l1.kernel.params.agent import AGENT_STATUS_IDLE
from l3.agent_terminal import get_terminal

_deadline = time.time() + 3.0
for _aid in ("agent_a", "agent_b", "agent_c"):
    while time.time() < _deadline:
        try:
            _t = get_terminal(_aid)
            if _t and _t.status.name == AGENT_STATUS_IDLE:
                break
        except Exception:
            pass
        time.sleep(0.05)

agent_map = {"http": "agent_a", "business": "agent_b", "security": "agent_c", "scout": "scout_pool"}

# Phase 1: investigate — scout scans for magic numbers in parallel
investigate_steps = []
for pattern in [r"\b\d{3,}\b", r"hardcode", r"magic.number", r"HARDCODED"]:
    investigate_steps.append(
        Step(action="grep", target="magic",
             params={"pattern": pattern, "path": ".", "template": "grep"},
             agent="scout")
    )
investigate_steps.append(Step(action="structure", target=".",
                               params={"path": ".", "template": "structure"}, agent="scout"))

# Phase 2: plan — agents read flagged files
plan_steps = [
    Step(action="read_file", target="/project/test.py", agent="http"),
    Step(action="read_file", target="/project/main.py", agent="business"),
]

# Phase 3: execute — agents propose replacements
execute_steps = [
    Step(action="think", target="propose constants for http", agent="http"),
    Step(action="think", target="propose constants for business", agent="business"),
    Step(action="think", target="review all proposals", agent="security"),
]

card = Card(
    intent="Constantization refactoring — scan, plan, execute",
    domain="/project",
    mode=CardMode.PARALLEL_ALL,
    phases=[
        Phase(name="investigate", mode=PhaseMode.PARALLEL, steps=investigate_steps),
        Phase(name="plan",        mode=PhaseMode.PARALLEL, steps=plan_steps),
        Phase(name="execute",     mode=PhaseMode.PARALLEL, steps=execute_steps),
    ],
)

total_steps = card.step_count()
print(f"Card: {total_steps} steps, {len(card.phases)} phases, mode={card.mode.name}")
print(f"  investigate: {len(investigate_steps)} steps (4 grep + 1 structure)")
print(f"  plan:        {len(plan_steps)} steps (2 read_file)")
print(f"  execute:     {len(execute_steps)} steps (3 think)")
print(f"  Pool: max_total={SCOUT_POOL_MAX_TOTAL} max_per_agent={SCOUT_POOL_MAX_PER_AGENT}")
print(f"  Workers: {TERMINAL_MAX_WORKERS} per agent\n")

# Warmup: run a single scout to pre-warm Python cache
get_pool().commission("warmup", "Search for import patterns in current directory")

t0 = time.time()
result = cell.execute_card(card, agent_map)
elapsed = time.time() - t0

steps = result.get("steps", [])
ok = sum(1 for s in steps if s.get("success"))
fail = sum(1 for s in steps if not s.get("success"))
print(f"Result: {'PASS' if ok == total_steps else 'SOME FAILED'}")
print(f"  {ok}/{total_steps} steps passed, {fail} failed")
print(f"  Wall time: {elapsed:.3f}s")
print(f"  Steps/s:   {total_steps/elapsed:.1f}")
print(f"  Parallel efficiency: {total_steps * min(s.get('elapsed',0) for s in steps if s.get('elapsed')) / elapsed:.1f}x")

for i, s in enumerate(steps):
    status = "OK" if s["success"] else "FAIL"
    action = s.get("step", s.get("action", "?"))
    target = s.get("target", "?")
    agent = s.get("agent_id", s.get("agent", "?"))
    print(f"  [{status}] {str(action)[:12]:12s} {str(target)[:16]:16s} agent={str(agent)[:16]:16s} {s.get('elapsed',0):.3f}s")

# Phase 2 and 3 should have started while phase 1 was still running (PARALLEL_ALL)
investigate_elapsed = sum(s.get("elapsed",0) for s in steps if s.get("phase") == "investigate")
plan_elapsed = sum(s.get("elapsed",0) for s in steps if s.get("phase") == "plan")
execute_elapsed = sum(s.get("elapsed",0) for s in steps if s.get("phase") == "execute")
total_cpu = investigate_elapsed + plan_elapsed + execute_elapsed
print(f"\n  CPU time: investigate={investigate_elapsed:.3f}s plan={plan_elapsed:.3f}s execute={execute_elapsed:.3f}s")
print(f"  Total CPU: {total_cpu:.3f}s, Wall: {elapsed:.3f}s, Speedup: {total_cpu/elapsed:.1f}x")

reset_terminals()
reset_cells()
