"""Kernel constants — single source of truth for all magic numbers/strings.

Sub-modules:
  kernel — kernel primitives (allocator, sync, process, gatechain, vfs)
  agent  — agent config (roles, terminal, loop, scout, card, convention)
  tool   — tool config (danger, timeouts, rate limits, HTN)
  api    — API, network, LLM, IPC, transport
  system — services (cache, persistence, data paths, sandbox, polling)

Import directly from sub-modules:
  from kernel.params.kernel import ALLOCATOR_DEFAULTS
  from kernel.params.agent import DEFAULT_CELL_ID
"""
