"""Tests for portal dashboard API endpoints with seeded data."""
import base64
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))

from rait_connector.encryption import Encryptor


def _make_eval_payload(encryptor, prompt_id: str, score: float) -> dict:
    data = {
        "prompt_id": prompt_id,
        "prompt_url": f"https://example.com/{prompt_id}",
        "prompt_response_id": "",
        "calibration_run_id": "",
        "for_calibration": False,
        "ethical_dimensions": [
            {
                "dimension_id": "dim-bias-001",
                "dimension_name": "Bias & Fairness",
                "dimension_metrics": [
                    {
                        "metric_id": "met-hate-001",
                        "metric_name": "Hate and Unfairness (Azure)",
                        "metric_metadata": {"score": score},
                    }
                ],
            },
            {
                "dimension_id": "dim-expl-001",
                "dimension_name": "Explainability & Transparency",
                "dimension_metrics": [
                    {
                        "metric_id": "met-coh-001",
                        "metric_name": "Coherence (Azure)",
                        "metric_metadata": {"score": score},
                    }
                ],
            },
            {
                "dimension_id": "dim-sec-001",
                "dimension_name": "Security & Adversarial Robustness",
                "dimension_metrics": [
                    {
                        "metric_id": "met-vuln-001",
                        "metric_name": "Code Vulnerability (Azure)",
                        "metric_metadata": {"score": score},
                    }
                ],
            },
        ],
    }
    encrypted = base64.b64encode(encryptor.encrypt(json.dumps(data))).decode()
    empty_logs = base64.b64encode(encryptor.encrypt("")).decode()
    return {
        "model_name": "gpt-4o-test",
        "model_version": "2024-08-06",
        "model_environment": "testing",
        "model_purpose": "test",
        "log_generated_at": datetime.now(timezone.utc).isoformat(),
        "model_data_logs": encrypted,
        "connector_logs": empty_logs,
        "log_type": "evaluation",
    }


@pytest.fixture(scope="module")
def seeded_client(tmp_path_factory, rsa_key_pair):
    """Portal TestClient with 5 evaluation records pre-seeded."""
    from dummy_portal.main import app
    from dummy_portal.config import settings

    tmp = tmp_path_factory.mktemp("dashboard")
    key_path = tmp / "rsa_private.pem"
    key_path.write_bytes(rsa_key_pair["private_pem"])
    settings.rsa_private_key_path = str(key_path)
    settings.sqlite_db_path = str(tmp / "portal.db")

    enc = Encryptor(public_key=rsa_key_pair["public_pem"])

    with TestClient(app) as client:
        for i in range(5):
            score = 0.6 + i * 0.05  # 0.60, 0.65, 0.70, 0.75, 0.80
            body = _make_eval_payload(enc, f"seed-prompt-{i:03d}", score)
            resp = client.put(f"/v1/test-client/gpt-4o-test/2024-08-06/{uuid.uuid4()}", json=body)
            assert resp.status_code == 200, f"Seed {i} failed: {resp.text}"

        yield client


# ── GET /api/records ──────────────────────────────────────────────────────────

class TestListRecords:
    def test_returns_five_records(self, seeded_client):
        resp = seeded_client.get("/api/records")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    def test_record_schema(self, seeded_client):
        resp = seeded_client.get("/api/records")
        for item in resp.json()["items"]:
            assert "record_id" in item
            assert "model_name" in item
            assert "log_type" in item
            assert item["log_type"] == "evaluation"

    def test_filter_by_log_type(self, seeded_client):
        resp = seeded_client.get("/api/records", params={"log_type": "telemetry"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_pagination_limit(self, seeded_client):
        resp = seeded_client.get("/api/records", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2
        assert resp.json()["total"] == 5

    def test_pagination_skip(self, seeded_client):
        resp = seeded_client.get("/api/records", params={"skip": 3})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2  # 5 total - 3 skipped


# ── GET /api/records/{id} ─────────────────────────────────────────────────────

class TestGetRecord:
    def test_existing_record_returns_detail(self, seeded_client):
        list_resp = seeded_client.get("/api/records")
        record_id = list_resp.json()["items"][0]["record_id"]
        resp = seeded_client.get(f"/api/records/{record_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["record_id"] == record_id
        assert "decrypted_payload" in data

    def test_missing_record_returns_404(self, seeded_client):
        resp = seeded_client.get("/api/records/999999")
        assert resp.status_code == 404


# ── GET /api/dimensions/summary ───────────────────────────────────────────────

class TestDimensionsSummary:
    def test_returns_three_dimensions(self, seeded_client):
        resp = seeded_client.get("/api/dimensions/summary")
        assert resp.status_code == 200
        dims = resp.json()["dimensions"]
        assert len(dims) == 3  # DB-driven — exactly 3 seeded strategies

    def test_sample_count_equals_five(self, seeded_client):
        resp = seeded_client.get("/api/dimensions/summary")
        for dim in resp.json()["dimensions"]:
            assert dim["sample_count"] == 5, f"Expected 5 for {dim['dimension_name']}"

    def test_scores_are_populated(self, seeded_client):
        resp = seeded_client.get("/api/dimensions/summary")
        for dim in resp.json()["dimensions"]:
            assert dim["avg_score"] > 0.0
            assert "min_score" in dim
            assert "max_score" in dim
            assert "is_safe" in dim
            assert "aggregation_strategy" in dim

    def test_known_avg_score(self, seeded_client):
        """5 seeds with scores 0.60..0.80 → avg=0.70 for average strategy."""
        resp = seeded_client.get("/api/dimensions/summary")
        expl = next(d for d in resp.json()["dimensions"] if "Explainability" in d["dimension_name"])
        assert expl["avg_score"] == pytest.approx(0.70, abs=0.01)
        assert expl["aggregation_strategy"] == "average"

    def test_security_uses_min_gate(self, seeded_client):
        """Min gate with scores 0.60..0.80 → score=0.60, is_safe=True (>= 0.5)."""
        resp = seeded_client.get("/api/dimensions/summary")
        sec = next(d for d in resp.json()["dimensions"] if "Security" in d["dimension_name"])
        assert sec["aggregation_strategy"] == "min_gate"
        assert sec["avg_score"] == pytest.approx(0.60, abs=0.01)
        assert sec["is_safe"] is True

    def test_total_records_matches(self, seeded_client):
        resp = seeded_client.get("/api/dimensions/summary")
        assert resp.json()["total_records"] == 5


# ── GET /api/telemetry ────────────────────────────────────────────────────────

class TestTelemetry:
    def test_empty_when_no_telemetry(self, seeded_client):
        resp = seeded_client.get("/api/telemetry")
        assert resp.status_code == 200
        assert resp.json() == []


# ── GET/POST /api/scheduler/status ───────────────────────────────────────────

class TestSchedulerStatus:
    def test_empty_initially(self, seeded_client):
        resp = seeded_client.get("/api/scheduler/status")
        assert resp.status_code == 200

    def test_push_and_retrieve(self, seeded_client):
        jobs = [{"id": "job-1", "trigger": "interval[hours=1]", "next_run": None, "is_executing": False}]
        post_resp = seeded_client.post("/api/scheduler/status", json=jobs)
        assert post_resp.status_code == 200
        get_resp = seeded_client.get("/api/scheduler/status")
        assert get_resp.status_code == 200
        data = get_resp.json()
        # Phase 2: GET /api/scheduler/status now returns a dict with legacy_jobs key
        legacy_jobs = data["legacy_jobs"]
        assert len(legacy_jobs) == 1
        assert legacy_jobs[0]["id"] == "job-1"


# ── GET /health with records ──────────────────────────────────────────────────

class TestHealthWithData:
    def test_health_reports_record_count(self, seeded_client):
        resp = seeded_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["record_count"] == 5
