"""Router for /api/telemetry: list raw telemetry records."""
import logging
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from ..dependencies import db_dependency
from ..models.schemas import TelemetryRecord
from ..services.query_service import QueryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/telemetry", response_model=List[TelemetryRecord])
async def list_telemetry(
    model_name: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(db_dependency),
) -> List[TelemetryRecord]:
    return await QueryService(db).list_telemetry(model_name=model_name, since=since, limit=limit)
