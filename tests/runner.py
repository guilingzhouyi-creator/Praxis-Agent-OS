#!/usr/bin/env python3
"""Test runner — runs the validated test suite via pytest in two batches.

Batch 1 (fast, ~5s): core kernel + services
Batch 2 (slow, ~75s): r4_agent + integration + convention + archive
"""
import sys, os, subprocess

BATCH_1 = [
    ("infra", "test_layer_imports"),
    ("infra", "test_params_integrity"),
    ("infra", "test_params_compliance"),
    ("infra", "test_hardcoded_fixes_regression"),
    # L1: Kernel
    ("l1", "test_kernel"), ("l1", "test_kernel_extended"), ("l1", "test_gatechain"),
    ("l1", "test_reputation"), ("l1", "test_constitution"), ("l1", "test_vfs"),
    ("l1", "test_errors"), ("l1", "test_sync"), ("l1", "test_event"),
    ("l1", "test_device"), ("l1", "test_ipc"), ("l1", "test_registry_base"),
    ("l1", "test_versioning"),
    # L2: Shell
    ("l2", "test_shell"), ("l2", "test_selector"),
    # L3: Cell
    ("l3/cell", "test_core"), ("l3/cell", "test_agent"),
    ("l3/cell", "test_cache"), ("l3/cell", "test_cross_review"),
    ("l3/cell", "test_decompose"), ("l3/cell", "test_execute"),
    ("l3/cell", "test_fault_tolerance"), ("l3/cell", "test_interrupt"),
    ("l3/cell", "test_l3"), ("l3/cell", "test_mmu"), ("l3/cell", "test_monitor"),
    ("l3/cell", "test_orchestration"), ("l3/cell", "test_pmu"),
    ("l3/cell", "test_resource_buffer"), ("l3/cell", "test_rollback"),
    ("l3/cell", "test_statecharts"), ("l3/cell", "test_watchdog"),
    ("l3/agent", "test_loop"), ("l3/agent", "test_correction"),
    ("l3/agent", "test_loop_subprocess"), ("l3/agent", "test_steps_exhausted"),
    ("l3/agent", "test_terminal_lifecycle"),
    ("l3/agent_terminal", "test_core"),
    ("l3/bus", "test_htn_a"), ("l3/bus", "test_htn_b"),
    ("l3/bus", "test_htn_planner"), ("l3/bus", "test_l3b_bus"),
    ("l3/bus", "test_message_gate"), ("l3/bus", "test_message_pool"),
    ("l3/bus", "test_monitor_bus"), ("l3/bus", "test_observability_bus"),
    ("l3/bus", "test_task_bus_cron"),
    ("l3/card", "test_execution"), ("l3/card", "test_execution_plan"),
    ("l3/card", "test_execution_run"), ("l3/card", "test_issue"),
    ("l3/card", "test_lifecycle_integration"), ("l3/card", "test_registry_sm"),
    ("l3/memory", "test_core"), ("l3/memory", "test_central_memory"),
    ("l3/memory", "test_context_search"), ("l3/memory", "test_init"),
    ("l3/memory", "test_manager"), ("l3/memory", "test_pager_swapper"),
    ("l3/memory", "test_persist_integration"), ("l3/memory", "test_persistence"),
    ("l3/memory", "test_quality"), ("l3/memory", "test_sandbox"),
    ("l3/memory", "test_reference_channel"),
    ("l3/tools", "test_build"), ("l3/tools", "test_config"),
    ("l3/tools", "test_files"), ("l3/tools", "test_git"),
    ("l3/tools", "test_mute"), ("l3/tools", "test_pipeline"),
    ("l3/tools", "test_pipeline_integration"), ("l3/tools", "test_policy"),
    ("l3/tools", "test_registry"), ("l3/tools", "test_spec"),
    ("l3/discussion", "test_assembly"), ("l3/discussion", "test_convergence"),
    ("l3/discussion", "test_core"), ("l3/discussion", "test_dialogue_session"),
    ("l3/discussion", "test_integration"),
    ("l3/error_bus", "test_core"),
    ("l3/identity", "test_core"), ("l3/identity", "test_content_trust"),
    ("l3/identity", "test_content_trust_flow"),
    ("l3/l3a", "test_core"), ("l3/l3a", "test_context"),
    ("l3/l3a", "test_session"), ("l3/l3a", "test_subagent"),
    ("l3/l3a", "test_integration"),
    ("l3/scheduler", "test_comprehensive"), ("l3/scheduler", "test_rate"),
    ("l3/scheduler", "test_scope"),
    ("l3/services", "test_core"), ("l3/services", "test_basics"),
    ("l3/services", "test_file_editor"), ("l3/services", "test_file_editor_boundary"),
    ("l3/session", "test_export"), ("l3/session", "test_scout_planner"),
    ("l3/subagent", "test_dispatch"), ("l3/subagent", "test_dispatcher"),
    ("l3/subagent", "test_framework"), ("l3/subagent", "test_gate"),
    ("l3/subagent", "test_pool"), ("l3/subagent", "test_task"),
    ("l3/boot", "test_core"), ("l3/boot", "test_sequence"),
    ("l3/config", "test_loader"), ("l3/config", "test_settings"),
    ("l3", "test_approval_gate"), ("l3", "test_approval_policy"),
    ("l3", "test_archive_orchestrator"), ("l3", "test_prompt_engine"),
    ("l3", "test_tool_approval"), ("l3", "test_tool_ring"),
    # L4: Bridge
    ("l4", "test_misc"), ("l4", "test_credential_vault"), ("l4", "test_api_gateway"),
    ("l4", "test_api_routes"), ("l4", "test_api_handlers_cluster"),
    ("l4", "test_auth_session"), ("l4", "test_mcp_bridge"),
    ("l4", "test_subscriptions"), ("l4", "test_auth"), ("l4", "test_sandbox"),
    # Integration
    ("integration", "test_network"), ("integration", "test_phase5_integration"),
    ("integration", "test_integration"),
]

BATCH_2 = [
    ("l3/memory", "test_r4_agent"), ("l3/memory", "test_r4_agent_evolve"),
    ("l3/memory", "test_r4_agent_evolve_integration"),
    ("l3/memory", "test_r4_agent_full_cycle"),
    ("l3/discussion", "test_convention"),
    ("l3/cell", "test_orchestration"),
]


def run_batch(tests: list[tuple[str, str]], label: str) -> int:
    targets = [f"tests/{d}/{t}.py" for d, t in tests]
    cmd = [sys.executable, "-m", "pytest"] + targets + ["-v", "--tb=short", "-q"]
    print(f"\n{'='*60}")
    print(f"  Batch: {label} ({len(tests)} files)")
    print(f"{'='*60}")
    r = subprocess.run(cmd, cwd=os.path.join(os.path.dirname(__file__), ".."))
    if r.returncode != 0:
        print(f"  FAILED: {label} (exit {r.returncode})")
    return r.returncode


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    if pattern:
        return run_batch([pattern], pattern)

    code = run_batch(BATCH_1, "fast core")
    if code != 0:
        return code
    code = run_batch(BATCH_2, "slow extended")
    return code


if __name__ == "__main__":
    sys.exit(main())
