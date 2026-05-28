"""Tests for PUT /v1/{key:path}: real connector-encrypted payloads, all log_types, error paths."""
import base64
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))

from rait_connector.encryption import Encryptor

from rait_connector_patches.encryptor_v2 import EncryptorV2


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_encrypted_payload(data: dict, enc: Encryptor) -> str:
    return base64.b64encode(enc.encrypt(json.dumps(data))).decode()


def _make_ingest_body(log_type: str, data: dict, enc: Encryptor) -> dict:
    return {
        "model_name":        "gpt-4o-test",
        "model_version":     "2024-08-06",
        "model_environment": "testing",
        "model_purpose":     "unit-test",
        "log_generated_at":  datetime.now(timezone.utc).isoformat(),
        "model_data_logs":   _make_encrypted_payload(data, enc),
        "connector_logs":    _make_encrypted_payload("", enc),
        "log_type":          log_type,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def portal_client(tmp_path_factory, rsa_key_pair):
    import os
    from dummy_portal.main import app
    from dummy_portal.config import settings

    tmp = tmp_path_factory.mktemp("portal")
    key_path = tmp / "rsa_private.pem"
    key_path.write_bytes(rsa_key_pair["private_pem"])

    settings.rsa_private_key_path = str(key_path)
    settings.sqlite_db_path = str(tmp / "portal.db")

    with TestClient(app) as client:
        yield client, settings.sqlite_db_path


@pytest.fixture(scope="module")
def v1_encryptor(rsa_key_pair):
    return Encryptor(public_key=rsa_key_pair["public_pem"])


@pytest.fixture(scope="module")
def v2_encryptor(rsa_key_pair):
    return EncryptorV2(public_key=rsa_key_pair["public_pem"])


# ── Evaluation ingest ─────────────────────────────────────────────────────────

class TestEvaluationIngest:
    _EVAL_DATA = {
        "prompt_id": "test-prompt-001",
        "prompt_url": "https://example.com/p/001",
        "prompt_response_id": "",
        "calibration_run_id": "",
        "for_calibration": False,
        "ethical_dimensions": [
            {
                "dimension_id": "dim-bias-001",
                "dimension_name": "Bias & Fairness",
                "dimension_metrics": [
                    {"metric_id": "met-hate-001", "metric_name": "Hate and Unfairness (Azure)",
                     "metric_metadata": {"score": 4.2}},
                ],
            }
        ],
    }

    def test_v1_evaluation_returns_accepted(self, portal_client, v1_encryptor):
        client, _ = portal_client
        body = _make_ingest_body("evaluation", self._EVAL_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000000/uuid-001", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        assert isinstance(resp.json()["record_id"], int)

    def test_v2_evaluation_returns_accepted(self, portal_client, v2_encryptor):
        client, _ = portal_client
        body = _make_ingest_body("evaluation", self._EVAL_DATA, v2_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000001/uuid-002", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_evaluation_stored_in_db(self, portal_client, v1_encryptor):
        client, db_path = portal_client
        body = _make_ingest_body("evaluation", self._EVAL_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000002/uuid-003", json=body)
        record_id = resp.json()["record_id"]

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM evaluation_results WHERE record_id=?", (record_id,)).fetchone()
        con.close()

        assert row is not None
        assert row["prompt_id"] == "test-prompt-001"
        dims = json.loads(row["ethical_dimensions"])
        assert len(dims) == 1
        assert dims[0]["dimension_name"] == "Bias & Fairness"


# ── Telemetry ingest ──────────────────────────────────────────────────────────

class TestTelemetryIngest:
    _TELEMETRY_DATA = {
        "app_dependencies": [{"name": "azuresql", "duration": 42}],
        "app_exceptions": [],
        "app_availability_results": [],
    }

    def test_telemetry_accepted(self, portal_client, v1_encryptor):
        client, _ = portal_client
        body = _make_ingest_body("telemetry", self._TELEMETRY_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000003/uuid-004", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_telemetry_stored_in_db(self, portal_client, v1_encryptor):
        client, db_path = portal_client
        body = _make_ingest_body("telemetry", self._TELEMETRY_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000004/uuid-005", json=body)
        record_id = resp.json()["record_id"]

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM telemetry_records WHERE record_id=?", (record_id,)).fetchone()
        con.close()

        assert row is not None
        raw = json.loads(row["raw_telemetry"])
        assert "app_dependencies" in raw


# ── Calibration ingest ────────────────────────────────────────────────────────

class TestCalibrationIngest:
    _CALIB_DATA = {
        "calibration_responses": [
            {"prompt_id": "gp-med-001", "response_text": "This is myocardial infarction."}
        ]
    }

    def test_calibration_accepted(self, portal_client, v1_encryptor):
        client, _ = portal_client
        body = _make_ingest_body("calibration", self._CALIB_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000005/uuid-006", json=body)
        assert resp.status_code == 200

    def test_calibration_stored_in_db(self, portal_client, v1_encryptor):
        client, db_path = portal_client
        body = _make_ingest_body("calibration", self._CALIB_DATA, v1_encryptor)
        resp = client.put("/v1/demo-client/gpt-4o-test/20250101T000006/uuid-007", json=body)
        record_id = resp.json()["record_id"]

        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM calibration_records WHERE record_id=?", (record_id,)).fetchone()
        con.close()

        assert row is not None
        responses = json.loads(row["responses"])
        assert responses[0]["prompt_id"] == "gp-med-001"


# ── Error paths ───────────────────────────────────────────────────────────────

class TestIngestErrors:
    def test_invalid_base64_returns_422(self, portal_client):
        client, _ = portal_client
        resp = client.put(
            "/v1/demo-client/test/20250101T000000/uuid-err",
            json={
                "model_name": "m", "model_version": "v", "model_environment": "e",
                "model_purpose": "p", "log_generated_at": "2025-01-01T00:00:00+00:00",
                "model_data_logs": "!!!not-valid-base64!!!",
                "connector_logs": "",
                "log_type": "evaluation",
            },
        )
        assert resp.status_code == 422
        assert "Decryption failed" in resp.json()["detail"]

    def test_wrong_key_encrypted_returns_422(self, portal_client, tmp_path):
        """Payload encrypted with a different public key cannot be decrypted."""
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        other_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pub_pem = other_key.public_key().public_bytes(
            encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
            format=__import__("cryptography").hazmat.primitives.serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        enc = Encryptor(public_key=other_pub_pem)
        client, _ = portal_client
        body = _make_ingest_body("evaluation", {"prompt_id": "x"}, enc)
        resp = client.put("/v1/demo-client/test/20250101T000000/uuid-wrongkey", json=body)
        assert resp.status_code == 422

    def test_missing_log_type_returns_422(self, portal_client):
        client, _ = portal_client
        resp = client.put(
            "/v1/demo-client/test/20250101T000000/uuid-notype",
            json={
                "model_name": "m", "model_version": "v", "model_environment": "e",
                "model_purpose": "p", "log_generated_at": "2025-01-01T00:00:00+00:00",
                "model_data_logs": "dGVzdA==",
                "log_type": "invalid_type",
            },
        )
        assert resp.status_code == 422
