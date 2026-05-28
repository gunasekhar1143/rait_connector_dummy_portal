"""Router for PUT /v1/{key:path}: receives encrypted evaluation/telemetry/calibration payloads."""
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request

from ..decryption import DecryptionError
from ..dependencies import db_dependency, get_decryption_engine
from ..models.schemas import IngestPayload, IngestResponse
from ..services.ingest_service import IngestService
from ..telemetry_setup import get_tracer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.put("/v1/{key:path}")
async def ingest(
    key: str,
    payload: IngestPayload,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dependency),
) -> IngestResponse:
    tracer = get_tracer()
    key_suffix = key.split("/")[-1]   # last UUID segment — safe to log

    with tracer.start_as_current_span("ingest.receive") as span:
        span.set_attribute("model_name", payload.model_name)
        span.set_attribute("log_type",   payload.log_type)
        span.set_attribute("key_suffix", key_suffix)

        engine = get_decryption_engine(request)
        service = IngestService(db=db, engine=engine)

        try:
            with tracer.start_as_current_span("ingest.decrypt") as decrypt_span:
                decrypt_span.set_attribute("version", "v2" if payload.model_data_logs and _is_v2(payload.model_data_logs) else "v1")
                record_id = await service.process(key, payload)
                decrypt_span.set_attribute("record_id", record_id)
        except DecryptionError as exc:
            try:
                from opentelemetry.trace import StatusCode
                span.set_status(StatusCode.ERROR)
                span.record_exception(exc)
            except ImportError:
                pass
            logger.warning("Decryption failed for key=%s: %s", key, exc)
            raise HTTPException(status_code=422, detail=f"Decryption failed: {exc}")
        except Exception as exc:
            try:
                from opentelemetry.trace import StatusCode
                span.set_status(StatusCode.ERROR)
                span.record_exception(exc)
            except ImportError:
                pass
            logger.exception("Unexpected error processing ingest key=%s", key)
            raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(status="accepted", record_id=record_id)


def _is_v2(b64: str) -> bool:
    import base64
    try:
        return base64.b64decode(b64[:4])[0] == 0x02
    except Exception:
        return False
