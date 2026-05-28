"""Router for HTML dashboard views: GET / and GET /records/{id}."""
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import db_dependency
from ..services.query_service import QueryService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: aiosqlite.Connection = Depends(db_dependency),
):
    query = QueryService(db)
    summary = await query.get_dimension_summary()
    records_page = await query.list_records(limit=20)
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "dimensions": [d.model_dump() for d in summary.dimensions],
            "records":    [r.model_dump() for r in records_page.items],
        },
    )


@router.get("/records/{record_id}", response_class=HTMLResponse)
async def record_detail(
    record_id: int,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dependency),
):
    record = await QueryService(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "record_detail.html",
        context={"record": record.model_dump()},
    )
