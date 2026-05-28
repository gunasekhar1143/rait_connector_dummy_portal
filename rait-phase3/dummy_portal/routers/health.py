"""Router for GET /health."""
import logging

import aiosqlite
from fastapi import APIRouter, Depends, Request

from ..dependencies import db_dependency

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(request: Request, db: aiosqlite.Connection = Depends(db_dependency)):
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM ingest_records")
    row = await cursor.fetchone()
    record_count = row[0] if row else 0
    return {"status": "ok", "db": "ok", "record_count": record_count}
