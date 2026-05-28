"""Router for /api/scheduler/status: push model for Scheduler state from driver scripts."""
import logging
from typing import List

from fastapi import APIRouter, Request

from ..models.schemas import SchedulerJob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/scheduler/status")
async def push_scheduler_status(jobs: List[SchedulerJob], request: Request) -> dict:
    """Driver scripts POST scheduler.status() here after each tick."""
    request.app.state.scheduler_status = [j.model_dump() for j in jobs]
    logger.info("Scheduler status updated: %d jobs", len(jobs))
    return {"status": "ok", "job_count": len(jobs)}


@router.get("/scheduler/status")
async def get_scheduler_status(request: Request) -> List[dict]:
    """Return last pushed scheduler status, or empty list if never pushed."""
    return request.app.state.scheduler_status
