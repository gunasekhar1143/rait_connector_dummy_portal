"""CalibrationScheduler — async cooperative background calibration.

Eliminates the primary Race Condition risk (R1) identified in the Architecture
Transformation Proposal: the legacy connector uses threading.Lock +
_running_calibrations (a shared mutable set) to track in-flight calibration
threads. This creates a check-then-act race condition between threads.

Legacy (rait_connector v0.8.0):
    # _running_calibrations: set protected by threading.Lock
    with self._calibration_lock:
        if run_id in self._running_calibrations:
            return  # race: another thread may reach here simultaneously
        self._running_calibrations.add(run_id)
    thread = threading.Thread(target=self._run_background_calibration, ...)
    thread.start()

Revised (this module):
    # asyncio.Event — single event loop, no shared mutable state, no race
    self._done.clear()
    asyncio.get_event_loop().create_task(self._run_cycle(run_id))
    # _done.set() called inside _run_cycle — atomic, deterministic, no race

Domain responses:
    Delegated to src/stubs.stub_text_response() — the canonical source shared
    with scripts/run_calibration.py. Previously copy-pasted here.

Encryption / ingest:
    Delegated to src/security/crypto — the single _encrypt_v2 implementation.
    Public key fetching delegated to AuthService.get_public_key().
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

from ..config import Settings
from ..security.crypto import build_ingest_key, build_ingest_payload, encrypt_v2
from ..stubs import stub_score_raw, stub_text_response
from .auth_service import AuthService

logger = logging.getLogger(__name__)


class CalibrationScheduler:
    """Single-run async calibration scheduler.

    Call start() to kick off a calibration cycle. The cycle fetches prompts,
    generates stub responses, posts them back to the registry, then ingests the
    result into the portal. asyncio.Event signals completion — no polling, no race.
    """

    def __init__(self, auth: AuthService, config: Settings) -> None:
        self._auth = auth
        self._config = config
        self._done: asyncio.Event = asyncio.Event()
        self._active_run_id: str | None = None
        self._last_result: dict | None = None

    async def start(self, run_id: str | None = None) -> str:
        """Start a calibration cycle. Returns the run_id. Does not block."""
        run_id = run_id or str(uuid.uuid4())
        self._active_run_id = run_id
        self._done.clear()
        asyncio.get_event_loop().create_task(
            self._run_cycle(run_id), name=f"calibration-{run_id[:8]}"
        )
        logger.info("Calibration cycle started run_id=%s", run_id)
        return run_id

    async def schedule_loop(self, interval: float | None = None) -> None:
        """Run calibration cycles on a fixed interval. Designed to run as asyncio.Task.

        Mirrors TelemetryService.sync_loop() — starts automatically at portal boot,
        runs every calibration_interval seconds, handles errors without crashing.
        """
        _interval = interval if interval is not None else self._config.calibration_interval
        while True:
            try:
                run_id = await self.start()
                await self.wait_complete(timeout=self._config.calibration_timeout)
                logger.info("Scheduled calibration complete run_id=%s", run_id)
            except Exception:
                logger.exception(
                    "Scheduled calibration failed; will retry in %.0fs", _interval
                )
            await asyncio.sleep(_interval)

    async def wait_complete(self, timeout: float | None = None) -> bool:
        """Wait for the current calibration cycle to finish. Returns True on success."""
        t = timeout if timeout is not None else self._config.calibration_timeout
        try:
            await asyncio.wait_for(self._done.wait(), timeout=t)
            return True
        except asyncio.TimeoutError:
            logger.warning("Calibration wait timed out after %.0fs", t)
            return False

    @property
    def is_running(self) -> bool:
        return self._active_run_id is not None and not self._done.is_set()

    @property
    def last_result(self) -> dict | None:
        return self._last_result

    async def _run_cycle(self, run_id: str) -> None:
        try:
            token = await self._auth.ensure_token()
            public_key_pem = await self._auth.get_public_key()

            # Step 1: Fetch prompts and enabled metrics concurrently
            async with httpx.AsyncClient(timeout=15.0) as client:
                prompts_resp, metrics_resp = await asyncio.gather(
                    client.get(
                        f"{self._config.rait_api_url}/api/calibrator/calibration-run-prompts/",
                        headers={"Authorization": f"Bearer {token}"},
                    ),
                    client.get(
                        f"{self._config.rait_api_url}/api/model-registry/enabled-metrics/",
                        headers={"Authorization": f"Bearer {token}"},
                    ),
                )
                prompts_resp.raise_for_status()
                metrics_resp.raise_for_status()

            calibration_data = prompts_resp.json()["data"]
            registry_run_id = calibration_data["calibration_run_id"]
            prompts = calibration_data["prompts"]

            # Flatten all metric names from the dimension/metric tree
            metric_names = [
                m["metric_name"]
                for dim in metrics_resp.json().get("data", [])
                for m in dim.get("dimension_metrics", [])
            ]
            logger.info(
                "Fetched %d prompts, %d metrics (registry_run_id=%s)",
                len(prompts), len(metric_names), registry_run_id,
            )

            # Step 2: Build registry responses (clean fields only) and
            #         ingest responses (same + per-prompt metric scores).
            # prompt_response_id is a fresh UUID per response — not the prompt_id —
            # so multiple calibration runs for the same prompt are distinguishable.
            registry_responses = [
                {
                    "prompt_response_id": str(uuid.uuid4()),
                    "prompt_text": p["prompt_text"],
                    "model_response": stub_text_response(p["prompt_id"]),
                }
                for p in prompts
            ]
            ingest_responses = [
                {
                    **r,
                    "metric_scores": {
                        name: stub_score_raw(name, prompt_id=p["prompt_id"])
                        for name in metric_names
                    },
                }
                for r, p in zip(registry_responses, prompts)
            ]

            # Step 3: Post clean responses to registry
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self._config.rait_api_url}/api/calibrator/update-prompts-response/",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"responses": registry_responses},
                )
                resp.raise_for_status()

            # Step 4: Ingest full responses (with metric_scores) into portal
            ts = datetime.now(timezone.utc).isoformat()
            payload_data = {
                "calibration_run_id": registry_run_id,
                "calibration_responses": ingest_responses,
                "prompt_count": len(prompts),
            }
            encrypted = encrypt_v2(public_key_pem, json.dumps(payload_data).encode())
            payload = build_ingest_payload(self._config, encrypted, ts, "calibration")
            key = build_ingest_key(
                self._config.rait_client_id,
                self._config.model_name,
                self._config.model_version,
                self._config.model_environment,
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.put(
                    f"{self._config.rait_ingest_url}/v1/{key}",
                    json=payload,
                )
                resp.raise_for_status()

            self._last_result = {
                "run_id": run_id,
                "registry_run_id": registry_run_id,
                "response_count": len(ingest_responses),
                "metric_count": len(metric_names),
            }
            logger.info(
                "Calibration cycle complete run_id=%s — %d responses, %d metrics each",
                run_id, len(ingest_responses), len(metric_names),
            )

        except Exception:
            logger.exception("Calibration cycle failed run_id=%s", run_id)
            self._last_result = {"run_id": run_id, "error": True}
        finally:
            # asyncio.Event.set() is atomic within the event loop — no race condition
            self._done.set()
