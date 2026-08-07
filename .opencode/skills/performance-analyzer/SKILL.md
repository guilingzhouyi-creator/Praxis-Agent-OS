---
name: performance-analyzer
description: Use when analyzing performance bottlenecks in Praxis — kernel syscall layer, allocator, scheduler, execution engine, concurrency primitives, and I/O paths.
---

## Overview

Performance analysis skill for the Praxis codebase. Identifies bottlenecks in the kernel syscall layer, allocator, scheduler, execution engine, concurrency primitives, and I/O paths.

## Workflow

### 1. Kernel & Syscall Layer Analysis
- Review syscall dispatch for overhead (lock contention on `_audit_log`).
- Check audit trail limits — does audit trail pruning cause O(n) copy?
- Analyze `syscall()` dictionary construction overhead in hot paths.

### 2. Allocator & Resource Management Analysis
- Review `allocator.py` for allocation/deallocation performance.
- Check `MUTEX_POLL_INTERVAL` / `SEMAPHORE_POLL_INTERVAL` — are poll intervals appropriate?
- Analyze resource limiter for token bucket efficiency.
- Check for memory leaks in ring buffer / memory entry lifecycle.

### 3. Scheduler & Process Table Analysis
- Review scheduling algorithm efficiency.
- Check PID scan/search complexity (O(n) on full table?).
- Analyze GC / zombie reaping performance.
- Verify CPU time tracking accuracy.

### 4. Execution Engine & Card Dispatch Analysis
- Review card dispatch latency.
- Check for planning complexity (HTN decomposition explosion).
- Analyze plan serialization/deserialization cost.

### 5. Concurrency & Locking Analysis
- Identify hot locks (`_audit_lock`, `_table_lock`, etc.).
- Check for lock contention in high-frequency paths.
- Review reader/writer fairness.
- Analyze mutex timeout vs spin patterns.

### 6. LLM & I/O Bottleneck Analysis
- Review LLM engine for request batching and connection pooling.
- Check polling intervals — is polling too aggressive?
- Analyze cache hit ratio and session timeout tuning.
- Review network connection reuse patterns.

### 7. Profiling
- Run a profile if available: `python -m cProfile -s cumulative`.
- Check health endpoint for useful performance metrics.
- Look for missing observability points in hot paths.

## Checklist

- [ ] Syscall audit lock contention analyzed — consider sharding if hot
- [ ] Poll intervals tuned (not too aggressive)
- [ ] Token bucket rate limiting effective (no bursts)
- [ ] Lock granularity appropriate (no coarse locks on hot paths)
- [ ] No O(n) scans in hot paths (PID table, audit queries)
- [ ] Memory lifecycle clean (no ring buffer leaks)
- [ ] HTN planner explosion bounded
- [ ] Connection pooling / reuse for external I/O
- [ ] Performance metrics exposed via health endpoint
- [ ] Truncation/logging constants used instead of raw literals
