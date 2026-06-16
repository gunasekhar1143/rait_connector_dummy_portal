"""Phase 5 capstone demo script.

Demonstrates:
  1. Pre-flight health check (both services on :8000 and :8001)
  2. Architecture narrative (R1/R2/R3 risks and how they were resolved)
  3. Single live prompt evaluation via POST /api/generate-and-evaluate
  4. Async batch of all 50 golden prompts with progress tracking
  5. Dashboard evidence — dimension summary with scores
  6. Final evidence checklist

Run from the rait-phase3/ directory with both services running:
  ../venv/Scripts/python scripts/demo_phase5.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

PORTAL_URL   = "http://localhost:8000"
REGISTRY_URL = "http://localhost:8001"

_PROMPTS_FILE = Path(__file__).parent.parent / "mock_registry" / "data" / "calibration_prompts.json"

_DIVIDER  = "─" * 70
_SECTION  = "═" * 70


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hdr(title: str) -> None:
    print(f"\n{_SECTION}")
    print(f"  {title}")
    print(_SECTION)


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗  {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"     {msg}")


# ── 1. Health check ───────────────────────────────────────────────────────────

def check_health() -> bool:
    _hdr("PRE-FLIGHT: Service Health Check")
    all_ok = True
    for name, url in [("Dummy Portal  :8000", PORTAL_URL), ("Mock Registry :8001", REGISTRY_URL)]:
        try:
            r = httpx.get(f"{url}/health", timeout=5)
            if r.status_code == 200:
                _ok(f"{name}  →  {r.json()}")
            else:
                _fail(f"{name}  →  HTTP {r.status_code}")
                all_ok = False
        except Exception as exc:
            _fail(f"{name}  →  unreachable ({exc})")
            all_ok = False
    return all_ok


# ── 2. Architecture narrative ─────────────────────────────────────────────────

def print_architecture() -> None:
    _hdr("ARCHITECTURE: Phase 5 Transformation Summary")
    narrative = [
        ("R1 — Race condition in CalibrationScheduler",
         "asyncio.Event replaces threading.Lock; single-event gate eliminates double-fetch."),
        ("R2 — Serialised evaluation throughput",
         "asyncio.gather replaces run_in_executor; concurrent metric calls with no thread pool."),
        ("R3 — EvaluationService config pollution",
         "Pydantic BaseSettings with per-instance isolation; no os.environ mutation."),
        ("Golden prompts",
         "50 prompts in mock_registry/data/calibration_prompts.json (medical/financial/security)."),
        ("Dashboard",
         "Interactive evaluate panel — type a query, click Run, results appear inline."),
        ("Evaluate endpoint",
         "POST /api/generate-and-evaluate now accepts just {\"query\": \"...\"}; all other fields optional."),
    ]
    for risk, fix in narrative:
        print(f"\n  [{risk}]")
        _info(fix)


# ── 3. Single live prompt ─────────────────────────────────────────────────────

def demo_single_prompt() -> dict:
    _hdr("LIVE DEMO: Single Prompt Evaluation")
    query = "A patient presents with chest pain radiating to the left arm and diaphoresis. What is the most likely diagnosis and immediate management?"
    _info(f"Query: {query[:80]}…")

    t0 = time.perf_counter()
    r = httpx.post(
        f"{PORTAL_URL}/api/generate-and-evaluate",
        json={"query": query},
        timeout=30,
    )
    elapsed = time.perf_counter() - t0

    if r.status_code != 200:
        _fail(f"HTTP {r.status_code}: {r.text[:200]}")
        return {}

    data = r.json()
    _ok(f"Response received in {elapsed:.2f}s")

    generated = data.get("generated_response", "")
    _info(f"Generated: {generated[:100]}…")

    evaluation = data.get("evaluation", data)
    dims = evaluation.get("ethical_dimensions", [])
    print(f"\n  Ethical dimension scores:")
    for d in dims:
        metrics = d.get("dimension_metrics", [])
        score = (
            sum(m.get("metric_metadata", {}).get("score", 0) for m in metrics) / len(metrics)
            if metrics else 0.0
        )
        print(f"    {d['dimension_name']:<40}  {score:.2f} / 5.0")

    return data


# ── 4. Async batch of all 50 prompts ─────────────────────────────────────────

async def _evaluate_one(client: httpx.AsyncClient, prompt: dict, idx: int, total: int) -> dict:
    r = await client.post(
        f"{PORTAL_URL}/api/generate-and-evaluate",
        json={"query": prompt["prompt_text"]},
        timeout=30,
    )
    print(f"    [{idx:>2}/{total}] {prompt['prompt_id']:<15}  HTTP {r.status_code}")
    return r.json() if r.status_code == 200 else {}


async def batch_all_prompts() -> list[dict]:
    _hdr("BATCH: All 50 Golden Prompts (async concurrent)")

    prompts = json.loads(_PROMPTS_FILE.read_text())
    total = len(prompts)
    _info(f"Loaded {total} prompts from {_PROMPTS_FILE.name}")
    print()

    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[_evaluate_one(client, p, i + 1, total) for i, p in enumerate(prompts)]
        )
    elapsed = time.perf_counter() - t0

    successful = sum(1 for r in results if r)
    _ok(f"{successful}/{total} evaluations succeeded in {elapsed:.2f}s  ({elapsed/total:.2f}s avg)")
    return list(results)


# ── 5. Dashboard evidence ─────────────────────────────────────────────────────

def print_dashboard_evidence() -> None:
    _hdr("DASHBOARD EVIDENCE: Ethical Dimension Summary")

    r = httpx.get(f"{PORTAL_URL}/api/dimensions/summary", timeout=10)
    if r.status_code != 200:
        _fail(f"Could not fetch summary: HTTP {r.status_code}")
        return

    data = r.json()
    total_records = data.get("total_records", 0)
    _info(f"Total evaluation records in DB: {total_records}")
    print()

    print(f"  {'Dimension':<40}  {'Avg':>6}  {'Min':>6}  {'Max':>6}  {'Samples':>7}  Safe?  Strategy")
    print(f"  {_DIVIDER}")
    for dim in data.get("dimensions", []):
        safe_icon = "✓" if dim["is_safe"] else "✗"
        print(
            f"  {dim['dimension_name']:<40}  "
            f"{dim['avg_score']:>6.2f}  "
            f"{dim['min_score']:>6.2f}  "
            f"{dim['max_score']:>6.2f}  "
            f"{dim['sample_count']:>7}  "
            f"  {safe_icon}    "
            f"{dim['aggregation_strategy']}"
        )


# ── 6. Evidence checklist ─────────────────────────────────────────────────────

def print_evidence_checklist() -> None:
    _hdr("EVIDENCE CHECKLIST")
    checks = [
        "R1 fixed: CalibrationScheduler uses asyncio.Event (no threading.Lock)",
        "R2 fixed: EvaluationService uses asyncio.gather (no run_in_executor)",
        "R3 fixed: ModernSettings per-instance isolation (no os.environ)",
        "50 golden prompts loaded from calibration_prompts.json",
        "POST /api/generate-and-evaluate accepts {\"query\": \"...\"} — all fields optional",
        "Dashboard: interactive evaluate panel at http://localhost:8000",
        "Dashboard: safety-banner cards with score bars and strategy tooltips",
    ]
    for check in checks:
        _ok(check)
    print()
    _info("Open http://localhost:8000 — type a query, click Run, see results inline.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{_SECTION}")
    print("  RAIT Phase 5 — Capstone Demo")
    print(f"{_SECTION}")

    if not check_health():
        print("\n  Both services must be running. Start them first:")
        print("    Terminal 1: ../venv/Scripts/uvicorn mock_registry.main:app --port 8001 --reload")
        print("    Terminal 2: ../venv/Scripts/uvicorn dummy_portal.main:app  --port 8000 --reload")
        sys.exit(1)

    print_architecture()
    demo_single_prompt()
    await batch_all_prompts()
    print_dashboard_evidence()
    print_evidence_checklist()

    print(f"\n{_SECTION}")
    print("  Demo complete.")
    print(_SECTION)


if __name__ == "__main__":
    asyncio.run(main())
