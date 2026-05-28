#!/usr/bin/env python3
"""Post telemetry data to the Dummy Portal.

In STUB_MODE=1 (default): uses synthetic Azure Monitor telemetry data.
In STUB_MODE=0: calls client.fetch_telemetry() against a real Azure Log Analytics workspace.

Usage:
  python scripts/run_telemetry.py
  STUB_MODE=0 python scripts/run_telemetry.py  # requires AZURE_LOG_ANALYTICS_WORKSPACE_ID
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

# ── Credential stubs (needed even for post_telemetry) ────────────────────────
from rait_connector_patches.stub_evaluator import apply_stub
apply_stub()

import requests
from rait_connector import RAITClient
from rait_connector.exceptions import RAITConnectorError

MODEL_NAME    = os.getenv("RAIT_EVAL_MODEL_NAME",    "gpt-4o-poc")
MODEL_VERSION = os.getenv("RAIT_EVAL_MODEL_VERSION", "2024-08-06")
ENVIRONMENT   = os.getenv("RAIT_EVAL_ENVIRONMENT",   "development")
PURPOSE       = os.getenv("RAIT_EVAL_PURPOSE",       "poc-demo")
_STUB         = os.getenv("STUB_MODE", "1") != "0"

# ── Stub telemetry data ───────────────────────────────────────────────────────

def _make_stub_telemetry() -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "AppDependencies": [
            {"name": "azure-openai", "type": "HTTP", "target": "eastus.api.openai.azure.com",
             "duration": 842, "success": True, "timestamp": ts, "resultCode": "200"},
            {"name": "azure-openai", "type": "HTTP", "target": "eastus.api.openai.azure.com",
             "duration": 1204, "success": True, "timestamp": ts, "resultCode": "200"},
            {"name": "rait-connector-ingest", "type": "HTTP", "target": "localhost:8000",
             "duration": 95, "success": True, "timestamp": ts, "resultCode": "200"},
        ],
        "AppExceptions": [
            {"problemId": "EncryptionWarning", "outerMessage": "RSA key cache miss — refetched",
             "severityLevel": 1, "timestamp": ts},
        ],
        "AppAvailabilityResults": [
            {"name": "PoC-Health-Probe", "success": True, "duration": 12,
             "timestamp": ts, "location": "localhost"},
        ],
    }


def _check_services() -> None:
    portal_url = os.getenv("RAIT_INGEST_URL", "http://localhost:8000")
    rait_url   = os.getenv("RAIT_API_URL",    "http://localhost:8001")
    for name, url in [("Mock Registry", f"{rait_url}/health"), ("Dummy Portal", f"{portal_url}/health")]:
        try:
            requests.get(url, timeout=5).raise_for_status()
            print(f"[ok]   {name} reachable")
        except Exception as e:
            print(f"[FAIL] {name} not reachable: {e}")
            sys.exit(1)


def main() -> None:
    print(f"\n{'='*60}")
    print(f"  RAIT Phase 3 — Telemetry Driver")
    print(f"  Model: {MODEL_NAME} {MODEL_VERSION} ({ENVIRONMENT})")
    print(f"  Mode:  {'STUB' if _STUB else 'REAL (Azure Log Analytics)'}")
    print(f"{'='*60}\n")

    _check_services()
    client = RAITClient()

    if _STUB:
        telemetry_data = _make_stub_telemetry()
        deps = len(telemetry_data["AppDependencies"])
        excs = len(telemetry_data["AppExceptions"])
        avail = len(telemetry_data["AppAvailabilityResults"])
        print(f"Stub telemetry: {deps} dependencies, {excs} exceptions, {avail} availability results")
    else:
        print("Fetching telemetry from Azure Log Analytics …")
        try:
            telemetry_data = client.fetch_telemetry()
        except RAITConnectorError as exc:
            print(f"[FAIL] fetch_telemetry raised: {exc}")
            sys.exit(1)
        total = sum(len(v) for v in telemetry_data.values())
        print(f"Fetched {total} telemetry rows across {len(telemetry_data)} tables")

    print("Posting telemetry to Dummy Portal …")
    try:
        result = client.post_telemetry(
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            model_environment=ENVIRONMENT,
            model_purpose=PURPOSE,
            telemetry_data=telemetry_data,
        )
    except RAITConnectorError as exc:
        print(f"[FAIL] post_telemetry raised: {exc}")
        sys.exit(1)

    print(f"\nCompleted: telemetry posted — status={result.get('status_code')}")
    print("Check GET /api/telemetry on the portal to verify.\n")


if __name__ == "__main__":
    main()
