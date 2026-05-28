"""IngestService: decrypt → parse → store by log_type."""
import json
import logging
from datetime import datetime, timezone

import aiosqlite

from ..decryption import DecryptionEngine, DecryptionError
from ..models.schemas import IngestPayload

logger = logging.getLogger(__name__)


class IngestService:
    def __init__(self, db: aiosqlite.Connection, engine: DecryptionEngine) -> None:
        self._db = db
        self._engine = engine

    async def process(self, key: str, payload: IngestPayload) -> int:
        """Decrypt, parse, store. Returns record_id."""
        # Decrypt model_data_logs
        try:
            raw = self._engine.decrypt(payload.model_data_logs)
        except DecryptionError:
            raise
        data = json.loads(raw)

        # Decrypt connector_logs (may be empty string encrypted — handle gracefully)
        logs = ""
        if payload.connector_logs:
            try:
                logs = self._engine.decrypt(payload.connector_logs).decode("utf-8", errors="replace")
            except (DecryptionError, Exception):
                logs = "<decryption failed>"

        record_id = await self._store_record(key, payload, data, logs)

        dispatch = {
            "evaluation":  self._store_evaluation,
            "telemetry":   self._store_telemetry,
            "calibration": self._store_calibration,
        }
        handler = dispatch.get(payload.log_type)
        if handler:
            await handler(record_id, payload, data)
        else:
            logger.warning("Unknown log_type: %s — stored in ingest_records only", payload.log_type)

        await self._db.commit()
        logger.info("Stored ingest record #%d log_type=%s key=%s", record_id, payload.log_type, key.split("/")[-1])
        return record_id

    async def _store_record(
        self, key: str, payload: IngestPayload, data: dict, logs: str
    ) -> int:
        cursor = await self._db.execute(
            """
            INSERT INTO ingest_records
              (raw_key, model_name, model_version, model_environment, model_purpose,
               log_type, log_generated_at, received_at, decrypted_payload, connector_logs)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                key,
                payload.model_name,
                payload.model_version,
                payload.model_environment,
                payload.model_purpose,
                payload.log_type,
                payload.log_generated_at,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(data),
                logs,
            ),
        )
        return cursor.lastrowid

    async def _store_evaluation(
        self, record_id: int, payload: IngestPayload, data: dict
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO evaluation_results
              (record_id, prompt_id, prompt_url, eval_timestamp,
               ethical_dimensions, post_response)
            VALUES (?,?,?,?,?,?)
            """,
            (
                record_id,
                data.get("prompt_id", ""),
                data.get("prompt_url", ""),
                payload.log_generated_at,
                json.dumps(data.get("ethical_dimensions", [])),
                json.dumps({"calibration_run_id": data.get("calibration_run_id", "")}),
            ),
        )

    async def _store_telemetry(
        self, record_id: int, payload: IngestPayload, data: dict
    ) -> None:
        await self._db.execute(
            "INSERT INTO telemetry_records (record_id, raw_telemetry) VALUES (?,?)",
            (record_id, json.dumps(data)),
        )

    async def _store_calibration(
        self, record_id: int, payload: IngestPayload, data: dict
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO calibration_records
              (record_id, calibration_run_id, responses)
            VALUES (?,?,?)
            """,
            (
                record_id,
                data.get("calibration_run_id", ""),
                json.dumps(data.get("calibration_responses", [])),
            ),
        )
