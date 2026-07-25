"""Test kernel.params constant integrity — all referenced constants must exist."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kernel.params import (
    ALLOCATOR_DEFAULTS, ALLOCATOR_FALLBACK_LIMIT, ALLOCATOR_PRESSURE_THRESHOLD,
    MUTEX_DEFAULT_TIMEOUT, MUTEX_DEFAULT_PRIORITY, MUTEX_POLL_INTERVAL,
    SEMAPHORE_DEFAULT_MAX, SEMAPHORE_DEFAULT_TIMEOUT,
    BARRIER_DEFAULT_COUNT, BARRIER_DEFAULT_TIMEOUT,
    RWLOCK_DEFAULT_TIMEOUT, RWLOCK_POLL_INTERVAL,
    HEARTBEAT_INTERVAL, EVENT_MAX_HISTORY, EVENT_QUERY_LIMIT,
    INTERRUPT_MAX_HISTORY, INTERRUPT_QUERY_LIMIT,
    REGISTRY_QUERY_LIMIT, TOOLCHAIN_MAX_CALLS, TOOLCHAIN_QUERY_LIMIT,
    DEVICE_HEALTH_INTERVAL, DEVICE_DEGRADED_THRESHOLD, DEVICE_DOWN_THRESHOLD,
    SYSCALL_AUDIT_MAX, SYSCALL_AUDIT_DETAIL_MAXLEN,
    TOOL_TERMINAL_TIMEOUT, TOOL_GREP_TIMEOUT,
    TOOL_RATE_RING_1, TOOL_RATE_RING_2_5, TOOL_RATE_RING_3,
    GATECHAIN_DANGER_LEVELS, LEDGER_MAX_ENTRIES,
    PROOF_TTL, KERNEL_VERSION, DEFAULT_TOKEN_BUDGET,
    CONSTITUTION_FILE_ACTIONS, CONSTITUTION_MODIFY_ACTIONS,
    CONSTITUTION_GATE_ACTIONS, CONSTITUTION_SCOUT_BLOCKED,
    SANDBOX_ROOT_PATH, DEFAULT_CELL_ID, PRAXIS_CONFIG_DIR,
    ANTHROPIC_DEFAULT_URL,
    MAX_SCOUTS_PER_AGENT, SCOUT_TIMEOUT, SCOUT_POOL_MAX,
    SESSION_TIMEOUT, BROADCAST_INTERVAL, PEER_TIMEOUT,
    PraxisRing, GateStatus, RequestPoolConfig, WitnessStatus,
    AGENT_REPUTATION_DEFAULTS, AGENT_CLEARANCE, DEFAULT_AGENT_CONFIGS,
    TOOL_DANGER_LEVEL, DANGER_TO_GATES,
)

import pytest


class TestParamsIntegrity:
    def test_allocator_defaults(self):
        assert ALLOCATOR_DEFAULTS.tokens == 4096
        assert ALLOCATOR_DEFAULTS.ring1 == 32
        assert ALLOCATOR_FALLBACK_LIMIT == 100
        assert ALLOCATOR_PRESSURE_THRESHOLD == 80.0

    def test_sync_defaults(self):
        assert MUTEX_DEFAULT_TIMEOUT == 30.0
        assert SEMAPHORE_DEFAULT_MAX == 3
        assert BARRIER_DEFAULT_COUNT == 3
        assert RWLOCK_DEFAULT_TIMEOUT == 30.0

    def test_event_constants(self):
        assert EVENT_MAX_HISTORY == 200
        assert EVENT_QUERY_LIMIT == 20

    def test_interrupt_constants(self):
        assert INTERRUPT_MAX_HISTORY == 200
        assert INTERRUPT_QUERY_LIMIT == 20

    def test_tool_timeouts(self):
        assert TOOL_TERMINAL_TIMEOUT == 30.0
        assert TOOL_GREP_TIMEOUT == 15.0

    def test_tool_rates(self):
        assert TOOL_RATE_RING_1 == 60
        assert TOOL_RATE_RING_2_5 == 20
        assert TOOL_RATE_RING_3 == 5

    def test_gatechain_danger_levels(self):
        assert GATECHAIN_DANGER_LEVELS["deploy"] == 5
        assert GATECHAIN_DANGER_LEVELS["run_in_terminal"] == 3

    def test_constitution_action_sets(self):
        assert "read_file" in CONSTITUTION_FILE_ACTIONS
        assert "write_file" in CONSTITUTION_MODIFY_ACTIONS
        assert "deploy" in CONSTITUTION_GATE_ACTIONS
        assert "write_file" in CONSTITUTION_SCOUT_BLOCKED

    def test_new_constants(self):
        assert DEFAULT_CELL_ID == "cell-1"
        assert PRAXIS_CONFIG_DIR == ".config/nomos-praxis"
        assert ANTHROPIC_DEFAULT_URL == "https://api.anthropic.com/v1/messages"

    def test_praxis_ring(self):
        assert PraxisRing.TOOL_RING_CAPACITY == 50

    def test_gate_status(self):
        assert GateStatus.PASS == "PASS"
        assert GateStatus.BLOCK == "BLOCK"

    def test_witness_status(self):
        assert WitnessStatus.PENDING == "PENDING"
        assert WitnessStatus.APPROVED == "APPROVED"

    def test_request_pool_config(self):
        assert RequestPoolConfig.CAPACITY == 8
        assert RequestPoolConfig.WEIGHT_REPUTATION == 0.40
        assert RequestPoolConfig.MAX_WAIT_S == 300.0

    def test_agent_configs(self):
        assert "default" in DEFAULT_AGENT_CONFIGS
        assert AGENT_CLEARANCE["l3"] == 3

    def test_tool_danger_levels(self):
        assert TOOL_DANGER_LEVEL[0] == "read_only"
        assert TOOL_DANGER_LEVEL[3] == "destructive"

    def test_version(self):
        assert KERNEL_VERSION == "0.3.0"

    def test_sandbox_root(self):
        assert "nomos-sandbox" in SANDBOX_ROOT_PATH
