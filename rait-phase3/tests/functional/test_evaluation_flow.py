"""Functional test: 5-prompt evaluation flow against live Mock Registry and Dummy Portal.

Requires both services to be running:
  uvicorn mock_registry.main:app --port 8001
  uvicorn dummy_portal.main:app  --port 8000

Marked @pytest.mark.functional — excluded from the default suite.
Run with: pytest tests/functional/ -m functional
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))

pytestmark = pytest.mark.functional

REGISTRY_URL = os.getenv("RAIT_API_URL",    "http://localhost:8001")
PORTAL_URL   = os.getenv("RAIT_INGEST_URL", "http://localhost:8000")
DB_PATH      = os.getenv("PORTAL_SQLITE_DB_PATH", "dummy_portal/portal.db")

FIVE_PROMPTS = [
    {"prompt_id": "ft-001", "prompt_text": "A patient presents with chest pain radiating to the left arm."},
    {"prompt_id": "ft-002", "prompt_text": "What is the fiduciary duty of a registered investment advisor?"},
    {"prompt_id": "ft-003", "prompt_text": "Review this SQL: SELECT * FROM users WHERE name = ' + user_input"},
    {"prompt_id": "ft-004", "prompt_text": "What is the recommended screening interval for colonoscopy?"},
    {"prompt_id": "ft-005", "prompt_text": "Explain the wash sale rule and tax-loss harvesting."},
]


def _services_up() -> bool:
    for url in [f"{REGISTRY_URL}/health", f"{PORTAL_URL}/health"]:
        try:
            requests.get(url, timeout=3).raise_for_status()
        except Exception:
            return False
    return True


@pytest.fixture(scope="module", autouse=True)
def require_services():
    if not _services_up():
        pytest.skip("Mock Registry and Dummy Portal not running — skipping functional tests")


@pytest.fixture(scope="module")
def pre_count():
    """Record current portal record count before the test."""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT COUNT(*) FROM ingest_records").fetchone()
        con.close()
        return row[0]
    except Exception:
        return 0


def test_evaluation_flow_end_to_end(pre_count):
    """5 prompts → RAITClient → Mock Registry → Dummy Portal → assert records stored."""
    # Apply patches (stub + v2 encryptor)
    import rait_connector.client as _rc
    from rait_connector_patches.encryptor_v2 import EncryptorV2
    from rait_connector_patches.stub_evaluator import apply_stub, remove_stub
    _rc.Encryptor = EncryptorV2
    apply_stub()

    try:
        from rait_connector import RAITClient
        from rait_connector.models import EvaluationInput

        client = RAITClient()
        ts = datetime.now(timezone.utc).isoformat()

        prompts = [
            EvaluationInput(
                prompt_id=p["prompt_id"],
                prompt_url=f"urn:rait:ft:{p['prompt_id']}",
                timestamp=ts,
                model_name="gpt-4o-ft",
                model_version="2024-08-06",
                query=p["prompt_text"],
                response=f"Functional test response for {p['prompt_id']}",
                environment="testing",
                purpose="functional-test",
            )
            for p in FIVE_PROMPTS
        ]

        summary = client.evaluate_batch(prompts, parallel=True, max_workers=3, fail_fast=False)
        client.wait_for_calibration(timeout=30.0)

    finally:
        remove_stub()

    # Assertions on summary
    assert summary["total"] == 5, f"Expected 5 total, got {summary['total']}"
    assert summary["successful"] == 5, f"Errors: {summary['errors']}"

    # Give portal a moment for any async writes to flush
    time.sleep(0.5)

    # Assert portal DB has at least 5 new evaluation records
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    new_evals = con.execute(
        "SELECT COUNT(*) as cnt FROM ingest_records WHERE log_type='evaluation' AND id > ?",
        (pre_count,)
    ).fetchone()["cnt"]
    con.close()

    assert new_evals >= 5, f"Expected >= 5 new evaluation records in portal, got {new_evals}"

    # Assert /api/dimensions/summary returns 3 dimensions with populated scores
    resp = requests.get(f"{PORTAL_URL}/api/dimensions/summary", timeout=10)
    assert resp.status_code == 200
    dims = resp.json()["dimensions"]
    assert len(dims) == 3

    for dim in dims:
        assert dim["sample_count"] > 0, f"Dimension {dim['dimension_name']} has 0 samples"
        assert dim["avg_score"] > 0.0


def test_portal_health_after_evaluation():
    resp = requests.get(f"{PORTAL_URL}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    # record_count should include our new evaluations
    assert resp.json()["record_count"] >= 5
