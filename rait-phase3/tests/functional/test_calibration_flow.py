"""Functional test: calibration response post flow against live services.

Requires both services running. Marked @pytest.mark.functional.
"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))

pytestmark = pytest.mark.functional

PORTAL_URL = os.getenv("RAIT_INGEST_URL", "http://localhost:8000")
RAIT_URL   = os.getenv("RAIT_API_URL",    "http://localhost:8001")
DB_PATH    = os.getenv("PORTAL_SQLITE_DB_PATH", "dummy_portal/portal.db")


@pytest.fixture(scope="module", autouse=True)
def require_services():
    for url in [f"{RAIT_URL}/health", f"{PORTAL_URL}/health"]:
        try:
            requests.get(url, timeout=3).raise_for_status()
        except Exception:
            pytest.skip("Services not running — skipping functional tests")


@pytest.fixture(scope="module")
def pre_calibration_count():
    con = sqlite3.connect(DB_PATH)
    count = con.execute("SELECT COUNT(*) FROM calibration_records").fetchone()[0]
    con.close()
    return count


def test_calibration_flow_end_to_end(pre_calibration_count):
    import rait_connector.client as _rc
    from rait_connector_patches.encryptor_v2 import EncryptorV2
    from rait_connector_patches.stub_evaluator import apply_stub, remove_stub
    _rc.Encryptor = EncryptorV2
    apply_stub()

    try:
        from rait_connector import RAITClient
        client = RAITClient()

        # Fetch calibration prompts from mock registry
        prompts = client.get_model_calibration_prompts(
            model_name="gpt-4o-ft",
            model_version="2024-08-06",
            model_environment="testing",
        )
        assert len(prompts) > 0, "Mock Registry returned no calibration prompts"

        # Build stub responses (just 3 to keep test fast)
        responses = [
            {"prompt_id": p["prompt_id"], "response_text": f"Calibration stub for {p['prompt_id']}"}
            for p in prompts[:3]
        ]

        result = client.post_calibration_responses(
            model_name="gpt-4o-ft",
            model_version="2024-08-06",
            model_environment="testing",
            model_purpose="functional-test",
            calibration_responses=responses,
        )
    finally:
        remove_stub()

    assert result["status_code"] == 200

    # Verify calibration record stored in portal DB
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    new_count = con.execute("SELECT COUNT(*) FROM calibration_records").fetchone()[0]
    last_row = con.execute(
        "SELECT responses FROM calibration_records ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()

    assert new_count > pre_calibration_count

    import json
    stored = json.loads(last_row["responses"])
    assert len(stored) == 3
    assert stored[0]["prompt_id"] == prompts[0]["prompt_id"]


def test_wait_for_calibration_returns_true():
    """With stub that no-ops _run_background_calibration, wait_for_calibration completes immediately."""
    import rait_connector.client as _rc
    from rait_connector_patches.encryptor_v2 import EncryptorV2
    from rait_connector_patches.stub_evaluator import apply_stub, remove_stub
    _rc.Encryptor = EncryptorV2
    apply_stub()
    try:
        from rait_connector import RAITClient
        client = RAITClient()
        ok = client.wait_for_calibration(timeout=5.0)
    finally:
        remove_stub()
    assert ok is True
