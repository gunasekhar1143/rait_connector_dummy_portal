#!/usr/bin/env python3
"""Post calibration responses to the Dummy Portal.

Fetches calibration prompts from Mock Registry, generates stub responses,
then posts them via post_calibration_responses().

Usage:
  python scripts/run_calibration.py
"""
# ── MUST be first two lines ───────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_VENV = _ROOT.parent / "venv" / "Lib" / "site-packages"
for p in [str(_ROOT), str(_VENV)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── EncryptorV2 patch ─────────────────────────────────────────────────────────
import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2

# ── Credential stubs ──────────────────────────────────────────────────────────
from rait_connector_patches.stub_evaluator import apply_stub
apply_stub()

import requests
from rait_connector import RAITClient
from rait_connector.exceptions import CalibrationError, RAITConnectorError

MODEL_NAME    = os.getenv("RAIT_EVAL_MODEL_NAME",    "gpt-4o-poc")
MODEL_VERSION = os.getenv("RAIT_EVAL_MODEL_VERSION", "2024-08-06")
ENVIRONMENT   = os.getenv("RAIT_EVAL_ENVIRONMENT",   "development")
PURPOSE       = os.getenv("RAIT_EVAL_PURPOSE",       "poc-demo")

# ── Stub model invocation ─────────────────────────────────────────────────────

_DOMAIN_RESPONSES = {
    "gp-med": "Based on clinical guidelines, the recommended approach involves thorough assessment and evidence-based treatment protocols.",
    "gp-fin": "Under applicable securities regulations, full disclosure of material risks and suitability assessment are required.",
    "gp-sec": "The identified vulnerability requires input validation, parameterised queries, and OWASP secure coding practices.",
}


def _invoke_model(prompt_text: str, prompt_id: str = "") -> dict:
    """Stub model: generate a domain-aware response."""
    response = _DOMAIN_RESPONSES.get("default", "Stub response.")
    for prefix, resp in _DOMAIN_RESPONSES.items():
        if prompt_id.startswith(prefix):
            response = resp
            break
    return {
        "model_response": response,
        "external_prompt_id": None,
    }


def _check_services() -> None:
    for name, url in [
        ("Mock Registry", f"{os.getenv('RAIT_API_URL', 'http://localhost:8001')}/health"),
        ("Dummy Portal",  f"{os.getenv('RAIT_INGEST_URL', 'http://localhost:8000')}/health"),
    ]:
        try:
            requests.get(url, timeout=5).raise_for_status()
            print(f"[ok]   {name} reachable")
        except Exception as e:
            print(f"[FAIL] {name} not reachable: {e}")
            sys.exit(1)


def main() -> None:
    print(f"\n{'='*60}")
    print(f"  RAIT Phase 3 — Calibration Driver")
    print(f"  Model: {MODEL_NAME} {MODEL_VERSION} ({ENVIRONMENT})")
    print(f"{'='*60}\n")

    _check_services()
    client = RAITClient()

    # ── Flow: model-registry calibration prompts ──────────────────────────────
    print("Fetching calibration prompts from Mock Registry …")
    try:
        prompts = client.get_model_calibration_prompts(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            model_environment=ENVIRONMENT,
        )
    except CalibrationError as exc:
        print(f"[FAIL] get_model_calibration_prompts raised: {exc}")
        sys.exit(1)

    print(f"Fetched {len(prompts)} calibration prompts")

    # Generate stub model responses
    ts = datetime.now(timezone.utc).isoformat()
    responses = []
    for p in prompts:
        result = _invoke_model(p.get("prompt_text", ""), p.get("prompt_id", ""))
        responses.append({
            "prompt_id":    p["prompt_id"],
            "response_text": result["model_response"],
        })

    print(f"Generated {len(responses)} stub responses — posting to portal …")
    try:
        result = client.post_calibration_responses(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            model_environment=ENVIRONMENT,
            model_purpose=PURPOSE,
            calibration_responses=responses,
        )
    except RAITConnectorError as exc:
        print(f"[FAIL] post_calibration_responses raised: {exc}")
        sys.exit(1)

    print(f"\nCompleted: {len(responses)} calibration responses posted — status={result.get('status_code')}")
    print("wait_for_calibration() …", end=" ", flush=True)
    ok = client.wait_for_calibration(timeout=10.0)
    print("done" if ok else "timed out (background threads not tracked for direct post)")
    print("Check GET /api/records?log_type=calibration on the portal to verify.\n")


if __name__ == "__main__":
    main()
