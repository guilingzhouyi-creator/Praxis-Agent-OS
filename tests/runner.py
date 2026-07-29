#!/usr/bin/env python3
"""Test runner — runs the validated test suite via pytest in two batches.

Batch 1 (fast, ~5s): core kernel + services
Batch 2 (slow, ~75s): r4_agent + integration + convention + archive
"""
import sys, os, subprocess

BATCH_1 = [
    # Layer import constraint — must pass before any batch (run first for fast CI fail)
    "test_layer_imports",
    "test_kernel", "test_persistence", "test_tool_mute", "test_tool_pipeline",
    "test_l3a", "test_services_core", "test_shell", "test_params_integrity",
    "test_issue", "test_credential_vault", "test_api_gateway", "test_assembly",
    "test_approval_gate", "test_auth_session", "test_cell_agent", "test_cell_decompose",
    "test_settings_center", "test_identity", "test_kernel_extended", "test_misc",
    "test_convergence", "test_errors", "test_config_loader", "test_fault_tolerance",
    "test_network", "test_subscriptions", "test_memory_sandbox", "test_memory_init",
    "test_cell_monitor", "test_observability_bus", "test_services", "test_integration",
    "test_mcp_bridge",
    # New core tests
    "test_gatechain", "test_reputation",
    "test_auth", "test_selector",
    "test_constitution", "test_vfs",
    "test_statecharts",
]

BATCH_2 = [
    "test_r4_agent", "test_archive_orchestrator", "test_convention",
]


def run_batch(tests: list[str], label: str) -> int:
    targets = [f"tests/{t}.py" for t in tests]
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
