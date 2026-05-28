"""Router for /api/dimensions/summary: DB-driven ethical dimension scores."""
import logging
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from ..dependencies import db_dependency
from ..models.schemas import DimensionSummary
from ..services.query_service import QueryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/dimensions/summary", response_model=DimensionSummary)
async def get_dimension_summary(
    model_name: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO 8601 datetime — only records received after this"),
    db: aiosqlite.Connection = Depends(db_dependency),
) -> DimensionSummary:
    return await QueryService(db).get_dimension_summary(model_name=model_name, since=since)
