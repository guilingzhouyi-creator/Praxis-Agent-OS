"""Benchmark: cross-platform kernel baselines for the Rust migration.

Measures L1 kernel primitives (mutex, event bus, ring channel, worker pool)
on the current platform and prints a comparable report. Run it on every
platform (Windows native, WSL, Linux, macOS) and diff the JSON outputs to
decide where a Rust kernel must pay attention.

Usage:
    python tests/benchmarks/bench_platform.py                 # micro benches only
    python tests/benchmarks/bench_platform.py --card          # + full card benchmark
    python tests/benchmarks/bench_platform.py --json out.json # machine-readable report

The --card flag shells out to bench_card.py and appends its throughput
numbers to the report; micro benches need no L3 boot and run standalone.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Benchmark sizing — iteration counts are generous so per-op cost is stable.
MUTEX_ITERS: int = 20_000
EVENT_ITERS: int = 50_000
CHANNEL_ITERS: int = 100_000
WORKER_TASKS: int = 20_000
THREAD_ITERS: int = 1_000
ROUNDS_DEFAULT: int = 3


def collect_platform_info() -> dict[str, Any]:
    """Return a dict describing the host OS, Python, and CPU."""
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "pid": os.getpid(),
    }
    if platform.system() == "Linux":
        try:
            with open("/proc/version", encoding="utf-8", errors="replace") as f:
                ver = f.read().lower()
            info["wsl"] = "microsoft" in ver or "wsl" in ver
        except OSError:
            info["wsl"] = False
    return info


def _median(values: list[float]) -> float:
    """Return the median of *values*."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _measure(fn: Any, iters: int, rounds: int) -> dict[str, float]:
    """Run *fn* for *rounds* passes of *iters* ops, return median ops/sec."""
    rates: list[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        fn(iters)
        elapsed = time.perf_counter() - start
        rates.append(iters / elapsed if elapsed > 0 else 0.0)
    return {"ops_per_sec": _median(rates), "rounds": len(rates)}


def bench_mutex(iters: int) -> None:
    """Contended-acquire microbenchmark on kernel Mutex."""
    from l1.kernel.sync import Mutex

    m = Mutex("bench_mutex", timeout=5.0)
    for _ in range(iters):
        m.acquire("bench", blocking=True)
        m.release("bench")


def bench_event_bus(iters: int) -> None:
    """Event-bus emit microbenchmark (no listeners → queue cost only)."""
    from l1.kernel.event import get_bus

    bus = get_bus()
    for _ in range(iters):
        bus.emit_event("bench.marker", {"i": 0})


def bench_channel(iters: int) -> None:
    """RingChannel put+get microbenchmark (single-thread round trip)."""
    from l1.kernel.channel_ring import RingChannel

    ch = RingChannel(capacity=1024)
    for _ in range(iters):
        ch.put(1)
        ch.get(timeout=0.001)


def bench_worker_pool(iters: int) -> None:
    """ThreadPoolWorker submit throughput (fire-and-forget no-op tasks)."""
    from l1.kernel.worker_thread import ThreadPoolWorker

    pool = ThreadPoolWorker(min_workers=2, max_workers=8, queue_size=8192)
    try:
        for _ in range(iters):
            pool.submit(lambda: None)
    finally:
        pool.shutdown(wait=True)


def bench_thread_create(iters: int) -> None:
    """Raw daemon-thread create+join cost (scheduler baseline)."""
    for _ in range(iters):
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        t.join()


def run_micro_benches(rounds: int) -> dict[str, dict[str, float]]:
    """Run all kernel micro benches, keyed by bench name."""
    benches = {
        "mutex.acquire_release": bench_mutex,
        "event_bus.emit": bench_event_bus,
        "channel.put_get": bench_channel,
        "worker_pool.submit": bench_worker_pool,
        "thread.create_join": bench_thread_create,
    }
    iters = {
        "mutex.acquire_release": MUTEX_ITERS,
        "event_bus.emit": EVENT_ITERS,
        "channel.put_get": CHANNEL_ITERS,
        "worker_pool.submit": WORKER_TASKS,
        "thread.create_join": THREAD_ITERS,
    }
    results: dict[str, dict[str, float]] = {}
    for name, fn in benches.items():
        try:
            results[name] = _measure(fn, iters[name], rounds)
        except Exception as exc:  # pragma: no cover — platform-specific failure
            results[name] = {"error": str(exc), "ops_per_sec": 0.0, "rounds": 0}
    return results


def run_card_bench() -> dict[str, float]:
    """Shell out to bench_card.py and parse its wall/step summary."""
    script = os.path.join(os.path.dirname(__file__), "bench_card.py")
    out = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[-400:], "steps_per_sec": 0.0}
    steps_per_sec = 0.0
    for line in out.stdout.splitlines():
        if line.strip().startswith("Steps/s:"):
            with contextlib.suppress(ValueError):
                steps_per_sec = float(line.split(":")[-1].strip())
    return {"steps_per_sec": steps_per_sec, "rc": out.returncode}


def print_report(platform_info: dict[str, Any], micro: dict[str, dict[str, float]], card: dict | None) -> None:
    """Print a human-readable benchmark report."""
    print("=" * 62)
    print("Praxis kernel cross-platform benchmark")
    print("=" * 62)
    print(f"  system : {platform_info['system']} {platform_info['release']} ({platform_info['machine']})")
    if platform_info.get("wsl"):
        print("  wsl    : yes (Linux kernel running under WSL)")
    print(f"  python : {platform_info['python']}  cpus: {platform_info['cpu_count']}")
    print("-" * 62)
    print(f"  {'bench':<28} {'ops/sec':>14}")
    for name, res in micro.items():
        if res.get("error"):
            print(f"  {name:<28} {'ERROR: ' + res['error'][:20]:>14}")
        else:
            print(f"  {name:<28} {res['ops_per_sec']:>14,.0f}")
    if card:
        print("-" * 62)
        if card.get("error"):
            print(f"  card benchmark   ERROR: {card['error'][:40]}")
        else:
            print(f"  card.steps/sec   {card['steps_per_sec']:>14,.1f}")
    print("=" * 62)


def main() -> int:
    """Entry point: parse args, run benches, print and optionally dump JSON."""
    parser = argparse.ArgumentParser(description="Praxis cross-platform kernel benchmark")
    parser.add_argument("--rounds", type=int, default=ROUNDS_DEFAULT, help="median rounds per bench")
    parser.add_argument("--json", type=str, default="", help="write machine-readable report to this file")
    parser.add_argument("--card", action="store_true", help="also run the full bench_card.py benchmark")
    args = parser.parse_args()

    platform_info = collect_platform_info()
    micro = run_micro_benches(args.rounds)
    card = run_card_bench() if args.card else None

    print_report(platform_info, micro, card)

    if args.json:
        report = {"platform": platform_info, "micro": micro}
        if card is not None:
            report["card"] = card
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
        print(f"JSON report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
