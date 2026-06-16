"""Thin RAITClient facade — Phase 2 service-oriented composition.

The legacy RAITClient is a god object (~1000 lines) that combines authentication,
evaluation, telemetry, and calibration in a single synchronous class. This facade
decomposes it into focused services and delegates all calls.

Every public method here is a thin async delegator — zero business logic.
All logic lives in the respective service module.

Usage:
    from src.client import RAITClient
    from src.config import Settings

    client = RAITClient()
    result = await client.evaluate(
        prompt_id="gp-med-001",
        query="...",
        response="...",
    )
"""
from .config import Settings
from .services.auth_service import AuthService
from .services.calibration_scheduler import CalibrationScheduler
from .services.evaluation_service import EvaluationService
from .services.telemetry_service import TelemetryService


class RAITClient:
    """Service-oriented async RAITClient facade."""

    def __init__(self, config: Settings | None = None, azure_evaluator=None) -> None:
        cfg = config or Settings()
        self.auth = AuthService(cfg)
        self.eval = EvaluationService(self.auth, cfg, azure_evaluator=azure_evaluator)
        self.telemetry = TelemetryService(self.auth, cfg)
        self.calibration = CalibrationScheduler(self.auth, cfg)

    async def evaluate(self, **kwargs) -> dict:
        """Evaluate a prompt via asyncio.gather parallel dispatch."""
        return await self.eval.run(**kwargs)

    async def sync_telemetry(self) -> list[dict]:
        """Fetch and upload one batch of telemetry records."""
        return await self.telemetry.sync_once()

    async def start_calibration(self, run_id: str | None = None) -> str:
        """Start a background calibration cycle. Returns run_id immediately."""
        return await self.calibration.start(run_id)

    async def wait_for_calibration(self, timeout: float | None = None) -> bool:
        """Block until the current calibration cycle completes or times out."""
        return await self.calibration.wait_complete(timeout)
