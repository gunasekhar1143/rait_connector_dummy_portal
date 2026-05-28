"""Router for /api/model-registry/: public-key and enabled-metrics (DB-driven)."""
import logging
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..models.schemas import DimensionItem, MetricItem, PublicKeyData, PublicKeyResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_auth(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.removeprefix("Bearer ")
    client_id = request.app.state.registry_state.validate_token(token)
    if client_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return client_id


@router.get("/public-key/")
async def get_public_key(
    request: Request,
    _: str = Depends(_require_auth),
) -> PublicKeyResponse:
    pem = request.app.state.key_manager.get_public_key_pem()
    return PublicKeyResponse(data=PublicKeyData(public_key=pem))


@router.get("/enabled-metrics/")
async def get_enabled_metrics(
    request: Request,
    model_name: Optional[str] = Query(default=None),
    model_version: Optional[str] = Query(default=None),
    model_environment: Optional[str] = Query(default=None),
    _: str = Depends(_require_auth),
):
    """Returns {"data": [...dimensions...]} — connector calls data.get("data", [])."""
    db_path: str = request.app.state.db_path
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """
            SELECT d.dimension_id, d.dimension_name,
                   m.metric_id, m.metric_name
            FROM dimensions d
            JOIN dimension_metrics dm ON dm.dimension_id = d.dimension_id
            JOIN metrics m ON m.metric_id = dm.metric_id
            ORDER BY d.display_order, m.metric_name
            """
        )

    dims: dict[str, dict] = {}
    for row in rows:
        did = row["dimension_id"]
        if did not in dims:
            dims[did] = {
                "dimension_id": did,
                "dimension_name": row["dimension_name"],
                "dimension_metrics": [],
            }
        dims[did]["dimension_metrics"].append(
            {"metric_id": row["metric_id"], "metric_name": row["metric_name"]}
        )
    return {"data": list(dims.values())}


@router.get("/calibration-prompts/")
async def get_calibration_prompts(
    request: Request,
    _: str = Depends(_require_auth),
):
    """Returns {"data": [...prompts...]} — connector calls data.get("data", [])."""
    prompts = request.app.state.calibration_prompts
    return {
        "data": [{"prompt_id": p["prompt_id"], "prompt_text": p["prompt_text"]} for p in prompts]
    }
