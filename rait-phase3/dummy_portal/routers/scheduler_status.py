"""Router for /api/scheduler/status.

GET  /api/scheduler/status          — real-time state from CalibrationScheduler
POST /api/scheduler/status          — legacy push model for driver scripts
POST /api/scheduler/calibration/start  — trigger a calibration cycle
"""
import logging
from typing import List

from fastapi import APIRouter, Request

from ..models.schemas import SchedulerJob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/scheduler/status")
async def push_scheduler_status(jobs: List[SchedulerJob], request: Request) -> dict:
    """Driver scripts POST scheduler.status() here after each tick (legacy support)."""
    request.app.state.scheduler_status = [j.model_dump() for j in jobs]
    logger.info("Scheduler status updated: %d jobs", len(jobs))
    return {"status": "ok", "job_count": len(jobs)}


@router.get("/scheduler/status")
async def get_scheduler_status(request: Request) -> dict:
    """Return combined scheduler state: Phase 2 CalibrationScheduler + legacy push status."""
    sched = getattr(request.app.state, "calibration_scheduler", None)

    phase2_status: dict = {"available": False}
    if sched is not None:
        phase2_status = {
            "available": True,
            "is_running": sched.is_running,
            "active_run_id": sched._active_run_id,
            "last_result": sched.last_result,
        }

    return {
        "phase2_calibration": phase2_status,
        "legacy_jobs": request.app.state.scheduler_status,
    }


@router.post("/scheduler/calibration/start")
async def start_calibration(request: Request) -> dict:
    """Trigger a CalibrationScheduler cycle (Phase 2 service)."""
    sched = getattr(request.app.state, "calibration_scheduler", None)
    if sched is None:
        return {"status": "unavailable", "detail": "Phase 2 CalibrationScheduler not initialized"}

    run_id = await sched.start()
    return {"status": "started", "run_id": run_id}
