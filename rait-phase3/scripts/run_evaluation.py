#!/usr/bin/env python3
"""Drive 50 golden prompts through RAITClient.evaluate_batch() against the local PoC stack.

Prerequisites:
  - Mock Registry running on http://localhost:8001
  - Dummy Portal running on http://localhost:8000
  - .env file at rait-phase3/ root with RAIT_* vars pointing to those services

Set STUB_MODE=1 (default) to use the stub evaluator (no Azure credentials required).
Set STUB_MODE=0 to use real Azure AI evaluators (requires AZURE_* vars in .env).

Usage:
  python scripts/run_evaluation.py
  STUB_MODE=0 python scripts/run_evaluation.py
"""
# ── MUST be first two lines ───────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from project root and venv
_ROOT = Path(__file__).parent.parent
_VENV = _ROOT.parent / "venv" / "Lib" / "site-packages"
for p in [str(_ROOT), str(_VENV)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── EncryptorV2 patch ─────────────────────────────────────────────────────────
import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2

# ── Stub evaluator (unless STUB_MODE=0) ───────────────────────────────────────
_STUB = os.getenv("STUB_MODE", "1") != "0"
if _STUB:
    from rait_connector_patches.stub_evaluator import apply_stub
    apply_stub()
    print("[stub] EvaluatorOrchestrator.evaluate_metrics patched with stub")

# ── Main imports ──────────────────────────────────────────────────────────────
import requests
from rait_connector import RAITClient
from rait_connector.exceptions import RAITConnectorError
from rait_connector.models import EvaluationInput

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_NAME    = os.getenv("RAIT_EVAL_MODEL_NAME",    "gpt-4o-poc")
MODEL_VERSION = os.getenv("RAIT_EVAL_MODEL_VERSION", "2024-08-06")
ENVIRONMENT   = os.getenv("RAIT_EVAL_ENVIRONMENT",   "development")
PURPOSE       = os.getenv("RAIT_EVAL_PURPOSE",       "poc-demo")
MAX_WORKERS   = int(os.getenv("RAIT_EVAL_MAX_WORKERS", "5"))

_PROMPTS_FILE = _ROOT / "mock_registry" / "data" / "calibration_prompts.json"

# ── Stub model responses ──────────────────────────────────────────────────────

_DOMAIN_RESPONSES: dict[str, str] = {
    "gp-med": (
        "Based on clinical guidelines, the recommended management includes immediate "
        "assessment of vital signs, appropriate diagnostic workup, and evidence-based "
        "treatment protocols. Always consult with a qualified healthcare provider."
    ),
    "gp-fin": (
        "Under applicable securities regulations and fiduciary standards, the appropriate "
        "approach requires full disclosure of material risks, suitability assessment, and "
        "compliance with regulatory requirements including Regulation Best Interest."
    ),
    "gp-sec": (
        "The identified security concern represents a significant vulnerability. "
        "Immediate remediation steps include input validation, parameterised queries, "
        "and following OWASP secure coding guidelines. Perform a security audit."
    ),
}

_DEFAULT_RESPONSE = (
    "This query requires careful consideration of relevant domain expertise, "
    "regulatory requirements, and ethical guidelines. Please consult appropriate "
    "subject matter experts before taking action."
)


def _get_response(prompt_id: str) -> str:
    for prefix, resp in _DOMAIN_RESPONSES.items():
        if prompt_id.startswith(prefix):
            return resp
    return _DEFAULT_RESPONSE


# ── Health check ─────────────────────────────────────────────────────────────

def _check_services() -> None:
    rait_url   = os.getenv("RAIT_API_URL",    "http://localhost:8001")
    portal_url = os.getenv("RAIT_INGEST_URL", "http://localhost:8000")
    for name, url in [("Mock Registry", f"{rait_url}/health"), ("Dummy Portal", f"{portal_url}/health")]:
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            print(f"[ok]   {name} reachable at {url}")
        except Exception as e:
            print(f"[FAIL] {name} not reachable at {url}: {e}")
            print("       Start both services before running this script.")
            sys.exit(1)


# ── Push scheduler status to portal ──────────────────────────────────────────

def _push_scheduler_status(scheduler) -> None:
    portal_url = os.getenv("RAIT_INGEST_URL", "http://localhost:8000")
    try:
        status = scheduler.status() if scheduler else []
        requests.post(f"{portal_url}/api/scheduler/status", json=status, timeout=5)
    except Exception:
        pass   # non-critical


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'='*60}")
    print(f"  RAIT Phase 3 — Evaluation Driver")
    print(f"  Model: {MODEL_NAME} {MODEL_VERSION} ({ENVIRONMENT})")
    print(f"  Mode:  {'STUB (no Azure)' if _STUB else 'REAL (Azure AI)'}")
    print(f"{'='*60}\n")

    _check_services()

    # Load 50 golden prompts
    prompts_data = json.loads(_PROMPTS_FILE.read_text())
    print(f"Loaded {len(prompts_data)} golden prompts from {_PROMPTS_FILE.name}")

    client = RAITClient()

    # Build EvaluationInput list
    ts = datetime.now(timezone.utc).isoformat()
    prompts = [
        EvaluationInput(
            prompt_id=p["prompt_id"],
            prompt_url=f"urn:rait:poc:prompt:{p['prompt_id']}",
            timestamp=ts,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            query=p["prompt_text"],
            response=_get_response(p["prompt_id"]),
            environment=ENVIRONMENT,
            purpose=PURPOSE,
            custom_fields={"domain": p["prompt_id"].split("-")[1] if "-" in p["prompt_id"] else "unknown"},
        )
        for p in prompts_data
    ]

    print(f"Running evaluate_batch({len(prompts)} prompts, parallel=True, max_workers={MAX_WORKERS}) …\n")

    try:
        summary = client.evaluate_batch(
            prompts,
            parallel=True,
            max_workers=MAX_WORKERS,
            fail_fast=False,
        )
    except RAITConnectorError as exc:
        print(f"[FAIL] evaluate_batch raised {type(exc).__name__}: {exc}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Results")
    print(f"{'='*60}")
    print(f"  Total:      {summary['total']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed:     {summary['failed']}")

    if summary["errors"]:
        print(f"\n  Errors:")
        for err in summary["errors"][:5]:
            print(f"    - {err}")

    # Wait for background calibration to complete
    print("\nWaiting for background calibration threads to finish …")
    completed = client.wait_for_calibration(timeout=120.0)
    print(f"  Calibration {'completed' if completed else 'timed out after 120s'}")

    print(f"\nCompleted: {summary['successful']}/{summary['total']} succeeded, {summary['failed']} failed")
    print("Check the dashboard at http://localhost:8000 to see results.\n")


if __name__ == "__main__":
    main()
