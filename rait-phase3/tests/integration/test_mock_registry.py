"""Tests for Mock Registry: all 7 endpoints, auth middleware, DB-driven metrics."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def registry_client(tmp_path_factory, rsa_key_pair):
    import os
    from mock_registry.main import app
    from mock_registry.config import settings

    tmp = tmp_path_factory.mktemp("registry")
    key_dir = tmp / "keys"
    key_dir.mkdir()
    (key_dir / "rsa_private.pem").write_bytes(rsa_key_pair["private_pem"])
    (key_dir / "rsa_public.pem").write_bytes(rsa_key_pair["public_pem"])

    db_path = str(tmp / "registry.db")

    # Patch settings for this test module
    settings.rsa_key_dir = str(key_dir)
    settings.db_path = db_path

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def auth_token(registry_client):
    resp = registry_client.post(
        "/api/model-registry/token/",
        json={"client_id": "test-client", "client_secret": "test-secret"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# ── Token endpoint ────────────────────────────────────────────────────────────

class TestTokenEndpoint:
    def test_returns_access_token(self, registry_client):
        resp = registry_client.post(
            "/api/model-registry/token/",
            json={"client_id": "demo-client", "client_secret": "demo-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["expires_in"] == 3600
        assert data["token_type"] == "Bearer"

    def test_empty_credentials_rejected(self, registry_client):
        resp = registry_client.post(
            "/api/model-registry/token/",
            json={"client_id": "", "client_secret": ""},
        )
        assert resp.status_code == 401


# ── Auth middleware ───────────────────────────────────────────────────────────

class TestAuthMiddleware:
    def test_no_token_returns_401(self, registry_client):
        resp = registry_client.get("/api/model-registry/public-key/")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, registry_client):
        resp = registry_client.get(
            "/api/model-registry/public-key/",
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )
        assert resp.status_code == 401

    def test_malformed_header_returns_401(self, registry_client):
        resp = registry_client.get(
            "/api/model-registry/public-key/",
            headers={"Authorization": "not-bearer-format"},
        )
        assert resp.status_code == 401


# ── Public key endpoint ───────────────────────────────────────────────────────

class TestPublicKeyEndpoint:
    def test_returns_pem(self, registry_client, auth_headers):
        resp = registry_client.get("/api/model-registry/public-key/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "public_key" in data["data"]
        assert "BEGIN PUBLIC KEY" in data["data"]["public_key"]

    def test_pem_is_valid_rsa(self, registry_client, auth_headers):
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        resp = registry_client.get("/api/model-registry/public-key/", headers=auth_headers)
        pem = resp.json()["data"]["public_key"].encode()
        key = load_pem_public_key(pem)
        assert key.key_size >= 2048


# ── Enabled metrics — DB-driven ───────────────────────────────────────────────

class TestEnabledMetrics:
    def test_returns_three_dimensions(self, registry_client, auth_headers):
        resp = registry_client.get("/api/model-registry/enabled-metrics/", headers=auth_headers)
        assert resp.status_code == 200
        dims = resp.json()["data"]   # connector reads data.get("data", [])
        assert len(dims) == 3

    def test_each_dimension_has_metrics(self, registry_client, auth_headers):
        resp = registry_client.get("/api/model-registry/enabled-metrics/", headers=auth_headers)
        for dim in resp.json()["data"]:
            assert "dimension_id" in dim
            assert "dimension_name" in dim
            assert len(dim["dimension_metrics"]) >= 1
            for m in dim["dimension_metrics"]:
                assert "metric_id" in m
                assert "metric_name" in m

    def test_metric_names_match_rait_connector_enum(self, registry_client, auth_headers):
        """metric_name values must exactly match rait_connector Metric enum strings."""
        expected = {
            "Hate and Unfairness (Azure)",
            "Coherence (Azure)",
            "Code Vulnerability (Azure)",
        }
        resp = registry_client.get("/api/model-registry/enabled-metrics/", headers=auth_headers)
        actual = {
            m["metric_name"]
            for dim in resp.json()["data"]
            for m in dim["dimension_metrics"]
        }
        assert actual == expected

    def test_accepts_model_query_params(self, registry_client, auth_headers):
        resp = registry_client.get(
            "/api/model-registry/enabled-metrics/",
            params={"model_name": "gpt-4o", "model_version": "2024-08-06"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 3  # no-op filter in Phase 3


# ── Calibration prompts ───────────────────────────────────────────────────────

class TestCalibrationPrompts:
    def test_returns_fifty_prompts(self, registry_client, auth_headers):
        resp = registry_client.get("/api/model-registry/calibration-prompts/", headers=auth_headers)
        assert resp.status_code == 200
        prompts = resp.json()["data"]   # connector reads data.get("data", [])
        assert len(prompts) == 50

    def test_prompt_schema(self, registry_client, auth_headers):
        resp = registry_client.get("/api/model-registry/calibration-prompts/", headers=auth_headers)
        for p in resp.json()["data"]:
            assert "prompt_id" in p
            assert "prompt_text" in p
            assert len(p["prompt_text"]) > 10


# ── Calibrator endpoints ──────────────────────────────────────────────────────

class TestCalibratorEndpoints:
    def test_calibration_run_prompts_returns_run_id(self, registry_client, auth_headers):
        resp = registry_client.get("/api/calibrator/calibration-run-prompts/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]   # connector reads data.get("data", {})
        assert "calibration_run_id" in data
        assert len(data["calibration_run_id"]) == 36  # UUID format
        assert len(data["prompts"]) == 50

    def test_get_prompts_response(self, registry_client, auth_headers):
        resp = registry_client.get("/api/calibrator/get-prompts-response/", headers=auth_headers)
        assert resp.status_code == 200
        groups = resp.json()["data"]  # connector flattens group.get("prompts", [])
        assert isinstance(groups, list)
        assert len(groups) == 1
        items = groups[0]["prompts"]
        assert len(items) == 50
        for item in items:
            assert "prompt_response_id" in item
            assert "prompt_text" in item

    def test_update_prompts_response(self, registry_client, auth_headers):
        resp = registry_client.post(
            "/api/calibrator/update-prompts-response/",
            headers=auth_headers,
            json={
                "model_code": "gpt-4o",
                "responses": [
                    {
                        "prompt_response_id": "gp-med-001",
                        "prompt_text": "A patient presents...",
                        "model_response": "This is myocardial infarction...",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status_code"] == 200

    def test_update_missing_body_returns_422(self, registry_client, auth_headers):
        resp = registry_client.post(
            "/api/calibrator/update-prompts-response/",
            headers=auth_headers,
            json={"bad_field": "bad_value"},
        )
        assert resp.status_code == 422


# ── Health endpoint ───────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, registry_client):
        resp = registry_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
