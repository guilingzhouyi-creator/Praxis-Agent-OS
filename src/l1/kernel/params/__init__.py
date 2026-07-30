"""Kernel constants — single source of truth for all magic numbers/strings.

Sub-modules:
  kernel    — kernel primitives (event, interrupt, registry, vfs, swapper, syscall, etc.)
  allocator — allocator, process table, resource limits
  sync      — mutex, semaphore, barrier, rwlock, IPC
  gatechain — GateChain, GateStatus, WitnessStatus
  agent     — agent config (roles, terminal, loop, scout, card, convention)
  tool      — tool config (danger, timeouts, rate limits, HTN)
  api       — API, network, LLM, IPC, transport
  system    — services (cache, persistence, data paths, sandbox, polling)

Import directly from sub-modules:
  from l1.kernel.params.kernel import EVENT_MAX_HISTORY
  from l1.kernel.params.allocator import ALLOCATOR_DEFAULTS
  from l1.kernel.params.agent import DEFAULT_CELL_ID
"""
