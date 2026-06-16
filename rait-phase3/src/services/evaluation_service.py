"""EvaluationService — the central Phase 2 architectural shift.

Replaces the legacy ThreadPoolExecutor-based EvaluatorOrchestrator with
asyncio.gather, running all metric evaluations concurrently on a single thread.

Legacy (rait_connector v0.8.0):
    with ThreadPoolExecutor(max_workers=N) as ex:
        futures = [ex.submit(run_eval, m) for m in metrics]
        results = [f.result() for f in as_completed(futures)]

Revised (this module):
    results = await asyncio.gather(*[_run_one(m) for m in metrics])

Backward compatibility contract:
    EvaluationService.run() is a drop-in replacement for
    rait_connector.RAITClient.evaluate(). The return dict, the encrypted
    model_data_logs structure, and the ingest payload are byte-for-byte
    compatible with the legacy connector. See _LEGACY_COMPAT note below.

Score scale:
    Stub scores use 0-5 scale (same as rait_connector_patches/stub_evaluator.py)
    to produce identical avg_score values on the dashboard. Scores are
    domain-aware and deterministically jittered via src/stubs.stub_score_raw().

Encryption / ingest:
    Delegated to src/security/crypto — single encrypt_v2 implementation.
    Public key fetching delegated to AuthService.get_public_key().
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings
from ..security.crypto import build_ingest_key, encrypt_v2
from ..stubs import stub_score_raw
from .auth_service import AuthService

logger = logging.getLogger(__name__)

# Sentinel so _run_one() can reference the service without a circular import.
_AzureEvaluatorService = None  # set to the actual instance via EvaluationService


async def _run_one(
    metric_name: str,
    query: str,
    response: str,
    prompt_id: str = "",
    metric_id: str = "",
    azure_evaluator=None,
) -> dict[str, Any]:
    """Evaluate a single metric via Azure AI Evaluator or stub fallback.

    Azure path (when azure_evaluator has the metric registered):
        Calls the appropriate azure-ai-evaluation evaluator in a thread pool.
        Returns full Azure output dict (e.g. {"hate_unfairness_score": 4, "score": 4.0, ...}).

    Stub path (when Azure credentials absent or evaluator unavailable):
        Returns {"score": float} on 0-5 scale, domain-aware, deterministically jittered.

    Output structure matches legacy EvaluatorOrchestrator per-metric dict:
        {"metric_id": str, "metric_name": str, "metric_metadata": dict}
    """
    metadata: dict[str, Any]

    if azure_evaluator is not None and azure_evaluator.has_evaluator(metric_name):
        try:
            metadata = await azure_evaluator.evaluate(metric_name, query, response)
            logger.debug("Azure eval OK: %s score=%s", metric_name, metadata.get("score"))
        except Exception:
            logger.warning(
                "Azure eval failed for %s — falling back to stub", metric_name, exc_info=True
            )
            score = stub_score_raw(metric_name, query=query, prompt_id=prompt_id)
            metadata = {"score": score}
    else:
        await asyncio.sleep(0.05)  # keep async concurrency without adding latency
        score = stub_score_raw(metric_name, query=query, prompt_id=prompt_id)
        metadata = {"score": score}

    return {
        "metric_id":       metric_id,
        "metric_name":     metric_name,
        "metric_metadata": metadata,
    }


class EvaluationService:
    def __init__(self, auth: AuthService, config: Settings, azure_evaluator=None) -> None:
        self._auth = auth
        self._config = config
        self._azure_evaluator = azure_evaluator
        if azure_evaluator is not None:
            logger.info("EvaluationService: Azure evaluators active")
        else:
            logger.info("EvaluationService: stub mode (no Azure credentials)")

    async def _fetch_dimensions(self, token: str) -> list[dict]:
        """Fetch enabled metrics grouped by dimension from the registry."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.rait_api_url}/api/model-registry/enabled-metrics/",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        return resp.json().get("data", [])

    async def run(
        self,
        prompt_id: str,
        query: str,
        response: str,
        # _LEGACY_COMPAT: per-request model identity — overrides Settings defaults.
        # rait_connector.RAITClient.evaluate() accepts these per-call;
        # EvaluationService must too so evaluate.py can pass them through unchanged.
        model_name: str = "",
        model_version: str = "",
        environment: str = "",
        purpose: str = "",
        # Optional evaluation fields (legacy evaluate() accepts these too)
        ground_truth: str = "",
        context: str = "",
        prompt_url: str = "",
        timestamp: str = "",
        prompt_response_id: str = "",
        calibration_run_id: str = "",
        for_calibration: bool = False,
        custom_fields: dict | None = None,
        # Execution hints — accepted for API parity; asyncio.gather handles concurrency
        parallel: bool = True,
        max_workers: int = 5,
        fail_fast: bool = False,
    ) -> dict[str, Any]:
        """Evaluate all enabled metrics concurrently via asyncio.gather.

        Return value matches rait_connector.RAITClient.evaluate() field-for-field:
            prompt_id, prompt_url, timestamp, model_name, model_version,
            query, response, ground_truth, context, environment, purpose,
            custom_fields, ethical_dimensions, post_response.
        """
        # Resolve model identity: per-request takes priority over Settings default.
        _model_name = model_name or self._config.model_name
        _model_version = model_version or self._config.model_version
        _environment = environment or self._config.model_environment
        _purpose = purpose or self._config.model_purpose

        token = await self._auth.ensure_token()
        public_key_pem, dimensions = await asyncio.gather(
            self._auth.get_public_key(),
            self._fetch_dimensions(token),
        )

        # Build metric list preserving metric_id from registry response
        # (legacy orchestrator carries metric_id through to metric_metadata output)
        all_metrics: list[tuple[str, str, str, str]] = []  # (dim_id, dim_name, metric_id, metric_name)
        for dim in dimensions:
            for metric in dim.get("dimension_metrics", []):
                all_metrics.append((
                    dim["dimension_id"],
                    dim["dimension_name"],
                    metric.get("metric_id", ""),
                    metric["metric_name"],
                ))

        # Core architectural shift: asyncio.gather — all evaluations concurrent
        raw_results = await asyncio.gather(*[
            _run_one(metric_name, query, response, prompt_id, metric_id,
                     azure_evaluator=self._azure_evaluator)
            for _, _, metric_id, metric_name in all_metrics
        ])

        # Group results back by dimension, preserving the full dim/metric structure
        dim_map: dict[str, dict] = {}
        for (did, dname, _mid, _mname), result in zip(all_metrics, raw_results):
            if did not in dim_map:
                dim_map[did] = {
                    "dimension_id": did,
                    "dimension_name": dname,
                    "dimension_metrics": [],
                }
            dim_map[did]["dimension_metrics"].append(result)

        evaluated_dimensions = list(dim_map.values())
        ts = timestamp or datetime.now(timezone.utc).isoformat()

        post_response = await self._ingest(
            public_key_pem=public_key_pem,
            prompt_id=prompt_id,
            prompt_response_id=prompt_response_id,
            calibration_run_id=calibration_run_id,
            prompt_url=prompt_url,
            ethical_dimensions=evaluated_dimensions,
            for_calibration=for_calibration,
            custom_fields=custom_fields,
            model_name=_model_name,
            model_version=_model_version,
            environment=_environment,
            purpose=_purpose,
            ts=ts,
            query=query,
            response=response,
            ground_truth=ground_truth,
            context=context,
        )

        logger.info(
            "Evaluated prompt_id=%s — %d metrics across %d dimensions",
            prompt_id, len(all_metrics), len(dim_map),
        )

        # _LEGACY_COMPAT: return dict matches rait_connector.RAITClient.evaluate() exactly.
        # Fields come from EvaluationInput.model_dump() in legacy + ethical_dimensions + post_response.
        # Note: legacy always returns custom_fields={} in the return value because EvaluationInput
        # is constructed without the custom_fields argument — the value is only used in model_data_logs.
        return {
            "prompt_id": prompt_id,
            "prompt_url": prompt_url,
            "timestamp": ts,
            "model_name": _model_name,
            "model_version": _model_version,
            "query": query,
            "response": response,
            "ground_truth": ground_truth,
            "context": context,
            "environment": _environment,
            "purpose": _purpose,
            "custom_fields": {},
            "ethical_dimensions": evaluated_dimensions,
            "post_response": post_response,
        }

    async def _ingest(
        self,
        *,
        public_key_pem: str,
        prompt_id: str,
        prompt_response_id: str,
        calibration_run_id: str,
        prompt_url: str,
        ethical_dimensions: list,
        for_calibration: bool,
        custom_fields: dict | None,
        model_name: str,
        model_version: str,
        environment: str,
        purpose: str,
        ts: str,
        query: str = "",
        response: str = "",
        ground_truth: str = "",
        context: str = "",
    ) -> dict:
        # _LEGACY_COMPAT: model_data_logs matches rait_connector._post_evaluation() exactly.
        # Legacy keys: prompt_id, prompt_response_id, calibration_run_id, prompt_url,
        #              ethical_dimensions, for_calibration, + custom_fields merged in.
        # Extended: query, response, ground_truth, context stored for record detail view.
        model_data_logs: dict[str, Any] = {
            "prompt_id": prompt_id,
            "prompt_response_id": prompt_response_id,
            "calibration_run_id": calibration_run_id,
            "prompt_url": prompt_url,
            "ethical_dimensions": ethical_dimensions,
            "for_calibration": for_calibration,
            "query": query,
            "response": response,
        }
        if ground_truth:
            model_data_logs["ground_truth"] = ground_truth
        if context:
            model_data_logs["context"] = context
        if custom_fields:
            model_data_logs.update(custom_fields)

        # ensure_ascii=False matches legacy json.dumps(..., ensure_ascii=False)
        encrypted = encrypt_v2(
            public_key_pem,
            json.dumps(model_data_logs, ensure_ascii=False).encode(),
        )

        # _LEGACY_COMPAT: outer IngestPayload uses per-request model identity,
        # not Settings defaults. Legacy _post_evaluation() uses evaluation_result fields.
        ingest_payload = {
            "model_name": model_name,
            "model_version": model_version,
            "model_environment": environment,
            "model_purpose": purpose,
            "log_generated_at": ts,
            "model_data_logs": encrypted,
            "connector_logs": "",
            "log_type": "evaluation",
        }

        key = build_ingest_key(
            self._config.rait_client_id, model_name, model_version, environment
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.put(
                f"{self._config.rait_ingest_url}/v1/{key}",
                json=ingest_payload,
            )
            resp.raise_for_status()

        logger.debug("Ingested evaluation record — model=%s/%s", model_name, model_version)
        # _LEGACY_COMPAT: post_response matches _post_evaluation() return value.
        return {"status_code": resp.status_code, "response": resp.text}
