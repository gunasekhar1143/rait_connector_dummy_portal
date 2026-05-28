"""DB read helpers for the dashboard API."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from ..models.schemas import DimensionSummary, RecordDetail, RecordList, RecordSummary, TelemetryRecord
from .aggregation_service import AggregationService


class QueryService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def list_records(
        self,
        log_type: Optional[str] = None,
        model_name: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> RecordList:
        where, params = _build_where(log_type=log_type, model_name=model_name)  # no alias
        count_rows = await self._db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM ingest_records{where}", params
        )
        total = count_rows[0]["cnt"] if count_rows else 0

        rows = await self._db.execute_fetchall(
            f"SELECT id, raw_key, model_name, model_version, model_environment, "
            f"log_type, log_generated_at, received_at "
            f"FROM ingest_records{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, skip],
        )
        items = [
            RecordSummary(
                record_id=r["id"],
                model_name=r["model_name"],
                model_version=r["model_version"],
                model_environment=r["model_environment"],
                log_type=r["log_type"],
                log_generated_at=r["log_generated_at"],
                received_at=r["received_at"],
            )
            for r in rows
        ]
        return RecordList(items=items, total=total)

    async def get_record(self, record_id: int) -> Optional[RecordDetail]:
        rows = await self._db.execute_fetchall(
            "SELECT * FROM ingest_records WHERE id=?", [record_id]
        )
        if not rows:
            return None
        r = rows[0]
        payload = None
        if r["decrypted_payload"]:
            try:
                payload = json.loads(r["decrypted_payload"])
            except (json.JSONDecodeError, TypeError):
                payload = None
        return RecordDetail(
            record_id=r["id"],
            model_name=r["model_name"],
            model_version=r["model_version"],
            model_environment=r["model_environment"],
            log_type=r["log_type"],
            log_generated_at=r["log_generated_at"],
            received_at=r["received_at"],
            decrypted_payload=payload,
            connector_logs=r["connector_logs"] or None,
        )

    async def get_dimension_summary(
        self,
        model_name: Optional[str] = None,
        since: Optional[str] = None,
    ) -> DimensionSummary:
        where_join, params = _build_where(log_type="evaluation", model_name=model_name, since=since, alias="ir")
        eval_rows = await self._db.execute_fetchall(
            f"SELECT er.ethical_dimensions "
            f"FROM evaluation_results er "
            f"JOIN ingest_records ir ON ir.id = er.record_id{where_join}",
            params,
        )

        where_direct, count_params = _build_where(log_type="evaluation", model_name=model_name, since=since)
        total_rows = await self._db.execute_fetchall(
            f"SELECT COUNT(*) as cnt FROM ingest_records{where_direct}", count_params
        )
        total = total_rows[0]["cnt"] if total_rows else 0

        agg = AggregationService(self._db)
        dimensions = await agg.compute_summary(eval_rows)

        return DimensionSummary(
            dimensions=dimensions,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            total_records=total,
        )

    async def list_telemetry(
        self,
        model_name: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> list[TelemetryRecord]:
        where, params = _build_where(log_type="telemetry", model_name=model_name, since=since, alias="ir")
        rows = await self._db.execute_fetchall(
            f"SELECT ir.id, ir.model_name, ir.received_at, tr.raw_telemetry "
            f"FROM telemetry_records tr "
            f"JOIN ingest_records ir ON ir.id = tr.record_id{where} "
            f"ORDER BY ir.id DESC LIMIT ?",
            params + [limit],
        )
        result = []
        for r in rows:
            raw = None
            if r["raw_telemetry"]:
                try:
                    raw = json.loads(r["raw_telemetry"])
                except (json.JSONDecodeError, TypeError):
                    raw = None
            result.append(TelemetryRecord(
                record_id=r["id"],
                model_name=r["model_name"],
                received_at=r["received_at"],
                raw_telemetry=raw,
            ))
        return result


def _build_where(
    log_type: Optional[str] = None,
    model_name: Optional[str] = None,
    since: Optional[str] = None,
    alias: str = "",          # "ir" for JOIN queries; "" for direct ingest_records queries
) -> tuple[str, list]:
    prefix = f"{alias}." if alias else ""
    clauses, params = [], []
    if log_type:
        clauses.append(f"{prefix}log_type=?")
        params.append(log_type)
    if model_name:
        clauses.append(f"{prefix}model_name=?")
        params.append(model_name)
    if since:
        clauses.append(f"{prefix}received_at >= ?")
        params.append(since)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params
