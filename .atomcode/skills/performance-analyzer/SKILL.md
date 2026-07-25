---
name: performance-analyzer
description: Performance analysis for NOMOS Praxis. Finds bottlenecks in kernel, allocator, scheduler, and execution engine.
allowed-tools: Read, Grep, Glob, Bash
---

## Performance Analysis Focus Areas

### Kernel & Syscall Layer
- Review `kernel/__init__.py` syscall dispatch for overhead (lock contention on `_audit_log`)
- Check `audit_max` limits — does audit trail pruning cause O(n) copy?
- Analyze `syscall()` dictionary construction overhead in hot paths

### Allocator & Resource Management
- Review `allocator.py` for allocation/deallocation performance
- Check `MUTEX_POLL_INTERVAL` / `SEMAPHORE_POLL_INTERVAL` — are poll intervals appropriate?
- Analyze `resource.py` limiter for token bucket efficiency
- Check for memory leaks in ring buffer / memory entry lifecycle

### Scheduler & Process Table
- Review `scheduler.py` for scheduling algorithm efficiency
- Check `process.py` for PID scan/search complexity (O(n) on full table?)
- Analyze GC / zombie reaping performance
- Verify `cpu_time` tracking accuracy

### Execution Engine & Planner
- Review `execution_engine.py` for card dispatch latency
- Check `htn_planner.py` for planning complexity (HTN decomposition explosion)
- Analyze `execution_plan.py` for plan serialization/deserialization cost

### Concurrency & Locking
- Identify hot locks: `_audit_lock`, `_table_lock`, etc.
- Check for lock contention in high-frequency paths
- Review `rwlock.py` reader/writer fairness
- Analyze `sync.py` mutex timeout vs spin patterns

### LLM & I/O Bottlenecks
- Review `llm.py` for request batching and connection pooling
- Check `card_poll_interval` — is polling too aggressive?
- Analyze `scout.py` for cache hit ratio and session timeout tuning
- Review `network.py` for connection reuse patterns

### Metrics & Profiling
- Run a profile if available: `python -m cProfile -s cumulative`
- Check `health.py` for useful performance metrics exposed
- Look for missing observability points in hot paths

### Checklist
- [ ] Syscall audit lock contention analyzed — consider sharding if hot
- [ ] Poll intervals tuned (not too aggressive)
- [ ] Token bucket rate limiting effective (no bursts)
- [ ] Lock granularity appropriate (no coarse locks on hot paths)
- [ ] No O(n) scans in hot paths (PID table, audit queries)
- [ ] Memory lifecycle clean (no ring buffer leaks)
- [ ] HTN planner explosion bounded
- [ ] Connection pooling / reuse for external I/O
- [ ] Performance metrics exposed via health endpoint
