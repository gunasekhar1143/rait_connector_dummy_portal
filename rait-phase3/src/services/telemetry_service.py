"""TelemetryService — async batched telemetry sync.

Replaces the legacy polling thread (a dedicated daemon thread calling
fetch_telemetry() in a blocking loop). The revised model uses asyncio.sleep,
which yields control back to the event loop rather than consuming an OS thread.

Legacy (rait_connector v0.8.0):
    # A daemon thread calls this in a synchronous while loop
    def _telemetry_worker(self):
        while not self._stop_event.is_set():
            self.fetch_telemetry()  # blocks thread
            self._stop_event.wait(timeout=self.interval)

Revised (this module):
    async def sync_loop(self):
        while True:
            await self.sync_once()   # yields to event loop during I/O
            await asyncio.sleep(interval)  # yields — no thread consumed

Encryption / ingest:
    Delegated to src/security/crypto — no local _encrypt_v2 copy.
    Public key fetching delegated to AuthService.get_public_key().

KQL queries:
    Delegated to src/security/kql_builder — parameterized, no f-string interpolation.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings
from ..security.crypto import build_ingest_key, build_ingest_payload, encrypt_v2
from ..security.kql_builder import KQLBuilder
from .auth_service import AuthService

logger = logging.getLogger(__name__)


def _build_stub_telemetry(model_name: str) -> dict[str, Any]:
    """Generate a synthetic Azure Monitor-style telemetry payload (stub mode)."""
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "telemetry_type": "azure_monitor_stub",
        "timestamp": ts,
        "model_name": model_name,
        "AppRequests": [
            {
                "TimeGenerated": ts,
                "Name": f"evaluate/{model_name}",
                "DurationMs": 512,
                "ResultCode": "200",
                "Success": True,
            }
        ],
        "AppExceptions": [],
        "AppAvailabilityResults": [
            {
                "TimeGenerated": ts,
                "Name": "health-check",
                "Success": True,
                "DurationMs": 12,
            }
        ],
    }


class TelemetryService:
    """Async telemetry sync service.

    In stub mode (default), generates synthetic Azure Monitor payloads and posts
    them to the portal. In real mode, queries Azure Log Analytics using KQLBuilder
    and uploads the results.
    """

    def __init__(
        self,
        auth: AuthService,
        config: Settings,
        stub_mode: bool = True,
    ) -> None:
        self._auth = auth
        self._config = config
        self._stub_mode = stub_mode
        self._kql = KQLBuilder()

    async def sync_once(self) -> list[dict]:
        """Fetch one batch of telemetry and upload it to the portal. Returns batch."""
        public_key_pem = await self._auth.get_public_key()

        if self._stub_mode:
            batch = [_build_stub_telemetry(self._config.model_name)]
        else:
            batch = await self._fetch_real_batch()

        if batch:
            await self._upload_batch(public_key_pem, batch)
            logger.info(
                '{"event": "telemetry_sync", "batch_size": %d, "stub_mode": %s}',
                len(batch),
                self._stub_mode,
            )

        return batch

    async def sync_loop(self) -> None:
        """Run sync_once() in an asyncio loop. Designed to run as an asyncio.Task."""
        while True:
            try:
                await self.sync_once()
            except Exception:
                logger.exception(
                    "Telemetry sync failed; will retry in %.0fs",
                    self._config.telemetry_sync_interval,
                )
            await asyncio.sleep(self._config.telemetry_sync_interval)

    async def _fetch_real_batch(self) -> list[dict]:
        """Build a KQL query and fetch from Azure Log Analytics (real mode)."""
        query = (
            self._kql
            .table("AppRequests")
            .filter("AppId", self._config.model_name)
            .time_range(60)
            .limit(100)
            .build()
        )
        logger.debug("KQL query:\n%s", query)
        # Execute via azure-monitor-query SDK in a real deployment.
        # Returns empty list to keep the PoC working without Azure credentials.
        return []

    async def _upload_batch(self, public_key_pem: str, batch: list[dict]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        for record in batch:
            encrypted = encrypt_v2(public_key_pem, json.dumps(record).encode())
            payload = build_ingest_payload(self._config, encrypted, ts, "telemetry")
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
        logger.debug("Uploaded %d telemetry record(s) to portal", len(batch))
