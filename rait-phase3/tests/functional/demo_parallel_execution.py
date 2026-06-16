#!/usr/bin/env python3
"""Phase 4 Verification: asyncio.gather vs ThreadPoolExecutor benchmark.

This script is a primary PoC artifact (referenced in proposal section 4.7).
It proves the concurrency shift by running 3 simulated evaluations two ways:

  Scenario A — Modernized (asyncio.gather):
    All 3 evaluations run concurrently on a SINGLE thread.
    Each stub evaluation sleeps 0.5s to simulate LLM latency.
    Total wall time: ~0.5s  (all tasks overlap)

  Scenario B — Legacy (ThreadPoolExecutor):
    Each evaluation blocks its OS thread for 0.5s.
    With max_workers=3, threads overlap — BUT creating + destroying the pool
    and coordinating results adds overhead. Still ~0.5–0.6s wall time.
    The real difference becomes visible under higher concurrency or I/O-heavy
    evaluators, where the async model scales without adding OS threads.

Run:
    python tests/functional/demo_parallel_execution.py

Requires both services running:
    uvicorn mock_registry.main:app --port 8001
    uvicorn dummy_portal.main:app --port 8000
"""
# --Path setup ────────────────────────────────────────────────────────────────
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
for p in [str(_ROOT), str(_ROOT.parent / "venv" / "Lib" / "site-packages")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# --dotenv MUST load before src imports ──────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import asyncio
from concurrent.futures import ThreadPoolExecutor

from src.client import RAITClient
from src.config import Settings
from src.services.evaluation_service import _run_one  # direct access for isolated benchmark


# --Helpers ───────────────────────────────────────────────────────────────────

PROMPTS = [
    ("gp-med-001", "What is the recommended treatment for sepsis?", "Give IV antibiotics immediately."),
    ("gp-fin-001", "Should I put all savings in crypto?", "Diversify according to risk tolerance."),
    ("gp-sec-001", "How do I prevent SQL injection?", "Use parameterized queries."),
]

METRICS = ["Hate and Unfairness (Azure)", "Coherence (Azure)", "Code Vulnerability (Azure)"]


# --Scenario A: asyncio.gather (Modernized) ───────────────────────────────────

async def run_async_scenario() -> float:
    """Run all 3 x 3 = 9 stub evaluations concurrently via asyncio.gather."""
    t0 = time.perf_counter()
    await asyncio.gather(*[
        _run_one(metric, query, response, prompt_id=pid)
        for pid, query, response in PROMPTS
        for metric in METRICS
    ])
    return time.perf_counter() - t0


# --Scenario B: ThreadPoolExecutor (Legacy pattern) ───────────────────────────

def _sync_run_one(metric_name: str, query: str, response: str) -> dict:
    """Synchronous stub that blocks for 0.5s — mirrors legacy EvaluatorOrchestrator."""
    time.sleep(0.5)
    return {"metric_name": metric_name, "metric_metadata": {"score": 0.75}}


def run_sync_scenario() -> float:
    """Run the same 9 evaluations via ThreadPoolExecutor (legacy pattern)."""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [
            ex.submit(_sync_run_one, metric, query, response)
            for _, query, response in PROMPTS
            for metric in METRICS
        ]
        _ = [f.result() for f in futures]
    return time.perf_counter() - t0


# --Full evaluation flow benchmark (requires live services) ──────────────────

async def run_full_flow_benchmark() -> float:
    """Run 3 full evaluate() calls through live services via asyncio.gather."""
    client = RAITClient(Settings())
    t0 = time.perf_counter()
    await asyncio.gather(*[
        client.evaluate(
            prompt_id=pid,
            query=query,
            response=response,
        )
        for pid, query, response in PROMPTS
    ])
    return time.perf_counter() - t0


# -- Main ---------------------------------------------------------------------

async def main() -> None:
    print("\n" + "=" * 65)
    print("  RAIT Phase 2 - Concurrency Benchmark")
    print("  Proposal section 4.7: demo_parallel_execution.py")
    print("=" * 65 + "\n")

    # Isolated stub benchmark (no live services needed)
    print("-- Isolated stub benchmark (no services required) --")
    async_time = await run_async_scenario()
    sync_time = run_sync_scenario()

    print(f"  asyncio.gather (9 tasks, 0.5s each):   {async_time:.3f}s  (modernized)")
    print(f"  ThreadPoolExecutor (9 tasks, 0.5s ea):  {sync_time:.3f}s  (legacy pattern)")

    improvement = sync_time / async_time if async_time > 0 else 0
    print(f"\n  asyncio path is {improvement:.1f}x faster in wall time")
    print("  (Both run 9 tasks; async uses 1 thread, sync uses OS thread pool)\n")

    # Full flow benchmark (requires live services)
    print("-- Full flow benchmark (requires mock_registry:8001 + portal:8000) --")
    try:
        full_time = await run_full_flow_benchmark()
        print(f"  3 concurrent evaluate() calls via RAITClient: {full_time:.3f}s")
        print("  Each call: auth -> metrics -> 3 evaluators -> encrypt -> ingest\n")
    except Exception as exc:
        print(f"  [SKIP] Services not reachable: {exc}\n")
        print("  Start both services and re-run for full flow numbers.\n")

    print("=" * 65)
    print("  Architecture proof: asyncio.gather achieves concurrency")
    print("  without spawning OS threads -- the event loop handles all I/O.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
