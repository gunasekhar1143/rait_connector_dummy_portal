"""Router for /api/calibrator/: calibration run prompts and response submission."""
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..models.schemas import (
    CalibrationRunResponse,
    CalibrationRunPrompt,
    PromptResponseItem,
    StatusResponse,
    UpdateResponsesRequest,
)

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


@router.get("/calibration-run-prompts/")
async def get_calibration_run_prompts(
    request: Request,
    _: str = Depends(_require_auth),
):
    """Returns {"data": {"calibration_run_id": ..., "prompts": [...]}}."""
    run_id = str(uuid.uuid4())
    request.app.state.registry_state.create_run(run_id)
    prompts = request.app.state.calibration_prompts
    return {
        "data": {
            "calibration_run_id": run_id,
            "prompts": [{"prompt_id": p["prompt_id"], "prompt_text": p["prompt_text"]} for p in prompts],
        }
    }


@router.get("/get-prompts-response/")
async def get_prompts_response(
    request: Request,
    calibration_run_id: Optional[str] = Query(default=None),
    _: str = Depends(_require_auth),
):
    """Returns {"data": [{"prompts": [...]}]} — connector flattens group.get("prompts", [])."""
    prompts = request.app.state.calibration_prompts
    items = [
        {
            "prompt_response_id": p["prompt_id"],
            "prompt_text": p["prompt_text"],
            "model_response": "",
        }
        for p in prompts
    ]
    return {"data": [{"prompts": items}]}


@router.post("/update-prompts-response/")
async def update_prompts_response(
    body: UpdateResponsesRequest,
    request: Request,
    _: str = Depends(_require_auth),
) -> StatusResponse:
    state = request.app.state.registry_state
    responses = [r.model_dump() for r in body.responses]
    # Mark all pending calibration runs complete (connector doesn't send run_id back)
    state.complete_all_pending_runs(responses)
    logger.info("Received %d calibration responses", len(responses))
    return StatusResponse()
