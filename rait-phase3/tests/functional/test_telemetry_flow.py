"""Functional test: telemetry post flow against live Dummy Portal.

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

STUB_TELEMETRY = {
    "AppDependencies":        [{"name": "test-dep", "duration": 100, "success": True}],
    "AppExceptions":          [],
    "AppAvailabilityResults": [{"name": "health", "success": True, "duration": 5}],
}


@pytest.fixture(scope="module", autouse=True)
def require_services():
    for url in [f"{RAIT_URL}/health", f"{PORTAL_URL}/health"]:
        try:
            requests.get(url, timeout=3).raise_for_status()
        except Exception:
            pytest.skip("Services not running — skipping functional tests")


@pytest.fixture(scope="module")
def pre_telemetry_count():
    con = sqlite3.connect(DB_PATH)
    count = con.execute("SELECT COUNT(*) FROM telemetry_records").fetchone()[0]
    con.close()
    return count


def test_post_telemetry_succeeds(pre_telemetry_count):
    import rait_connector.client as _rc
    from rait_connector_patches.encryptor_v2 import EncryptorV2
    from rait_connector_patches.stub_evaluator import apply_stub, remove_stub
    _rc.Encryptor = EncryptorV2
    apply_stub()

    try:
        from rait_connector import RAITClient
        client = RAITClient()
        result = client.post_telemetry(
            model_name="gpt-4o-ft",
            model_version="2024-08-06",
            model_environment="testing",
            model_purpose="functional-test",
            telemetry_data=STUB_TELEMETRY,
        )
    finally:
        remove_stub()

    assert result["status_code"] == 200

    # Verify portal DB has a new telemetry record
    con = sqlite3.connect(DB_PATH)
    new_count = con.execute("SELECT COUNT(*) FROM telemetry_records").fetchone()[0]
    con.close()
    assert new_count > pre_telemetry_count


def test_get_telemetry_endpoint():
    resp = requests.get(f"{PORTAL_URL}/api/telemetry", timeout=5)
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    item = items[0]
    assert "record_id" in item
    assert "model_name" in item
    assert "raw_telemetry" in item
