"""Router for /api/records: list and detail views of ingest records."""
import logging
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import db_dependency
from ..models.schemas import RecordDetail, RecordList
from ..services.query_service import QueryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/records", response_model=RecordList)
async def list_records(
    log_type: Optional[str] = Query(default=None),
    model_name: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(db_dependency),
) -> RecordList:
    return await QueryService(db).list_records(
        log_type=log_type, model_name=model_name, skip=skip, limit=limit
    )


@router.get("/records/{record_id}", response_model=RecordDetail)
async def get_record(
    record_id: int,
    db: aiosqlite.Connection = Depends(db_dependency),
) -> RecordDetail:
    record = await QueryService(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    return record
