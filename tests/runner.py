#!/usr/bin/env python3
"""Test runner — runs the validated test suite via pytest in two batches.

Batch 1 (fast, ~5s): core kernel + services
Batch 2 (slow, ~75s): r4_agent + integration + convention + archive
"""
import sys, os, subprocess

BATCH_1 = [
    # Layer import constraint — must pass before any batch
    ("infra", "test_layer_imports"),
    # L1: Kernel
    ("l1", "test_kernel"), ("l1", "test_kernel_extended"), ("l1", "test_gatechain"),
    ("l1", "test_reputation"), ("l1", "test_constitution"), ("l1", "test_vfs"),
    ("l1", "test_errors"), ("infra", "test_params_integrity"),
    # L2: Shell
    ("l2", "test_shell"), ("l2", "test_selector"),
    # L3: Cell
    ("l3", "test_l3a"), ("l3", "test_services_core"), ("l3", "test_persistence"),
    ("l3", "test_tool_mute"), ("l3", "test_tool_pipeline"),
    ("l3", "test_issue"), ("l3", "test_assembly"),
    ("l3", "test_approval_gate"), ("l3", "test_cell_agent"), ("l3", "test_cell_decompose"),
    ("l3", "test_settings_center"), ("l3", "test_identity"),
    ("l3", "test_convergence"), ("l3", "test_config_loader"),
    ("l3", "test_fault_tolerance"), ("l3", "test_memory_sandbox"),
    ("l3", "test_memory_init"), ("l3", "test_cell_monitor"),
    ("l3", "test_observability_bus"), ("l3", "test_services"),
    ("l3", "test_subagent_gate"), ("l3", "test_subagent_pool"),
    ("l3", "test_subagent_task"), ("l3", "test_resource_buffer"),
    ("l3", "test_card_execution"), ("l3", "test_cell"),
    ("l3", "test_memory"), ("l3", "test_discussion"),
    ("l3", "test_statecharts"),
    # L4: Bridge
    ("l4", "test_credential_vault"), ("l4", "test_api_gateway"),
    ("l4", "test_auth_session"), ("l4", "test_mcp_bridge"),
    ("l4", "test_subscriptions"), ("l4", "test_auth"),
    # Integration
    ("integration", "test_network"), ("integration", "test_integration"),
]

BATCH_2 = [
    ("l3", "test_r4_agent"), ("l3", "test_convention"),
    ("l3", "test_cell_orchestration"),
    ("l3", "test_agent_loop"), ("l3", "test_agent_terminal_lifecycle"),
    ("l3", "test_discussion_integration"),
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
