"""Dummy Portal FastAPI application."""
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import init_db
from .decryption import DecryptionEngine
from .ml.classifier import MetricClassifier
from .routers import dimensions, evaluate, health, ingest, records, scheduler_status, telemetry, ui
from .telemetry_setup import setup_otel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_STATIC_DIR    = Path(__file__).parent / "ui" / "static"
_TEMPLATES_DIR = Path(__file__).parent / "ui" / "templates"
_SRC_DIR       = Path(__file__).parent.parent / "src"
if str(_SRC_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR.parent))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(settings.sqlite_db_path)

    app.state.db_path           = settings.sqlite_db_path
    app.state.decryption_engine = DecryptionEngine.from_pem_path(settings.rsa_private_key_path)
    app.state.metric_classifier = MetricClassifier()
    app.state.scheduler_status  = []
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["tojson"] = lambda v, indent=None: json.dumps(v, indent=indent, default=str)
    _strategy_labels = {"min_gate": "Min Gate", "weighted_scorecard": "Weighted", "average": "Average"}
    _strategy_tooltips = {
        "min_gate": "Fails if any metric falls below the safety threshold",
        "weighted_scorecard": "Weighted average of metrics by risk tier",
        "average": "Simple mean of all metric scores",
    }
    templates.env.filters["strategy_label"]   = lambda v: _strategy_labels.get(v, v)
    templates.env.filters["strategy_tooltip"] = lambda v: _strategy_tooltips.get(v, v)
    app.state.templates = templates

    setup_otel(exporter=settings.otel_exporter)

    # Phase 2 services — imported lazily so portal starts even if src/ has issues
    try:
        from src.config import Settings as ModernSettings
        from src.client import RAITClient as ModernRAITClient

        _cfg = ModernSettings()

        # Azure AI evaluators — created only when credentials are present
        _azure_evaluator = None
        if _cfg.has_azure:
            try:
                from src.services.azure_evaluator import AzureEvaluatorService
                _azure_evaluator = AzureEvaluatorService(_cfg)
                logger.info("Azure evaluators initialised")
            except Exception:
                logger.warning("Azure evaluator init failed — continuing in stub mode", exc_info=True)

        _modern_client = ModernRAITClient(_cfg, azure_evaluator=_azure_evaluator)

        # Store settings and azure evaluator for router access
        app.state.modern_settings      = _cfg
        app.state.azure_evaluator      = _azure_evaluator

        # Expose the full client (used by evaluate.py after migration)
        app.state.modern_rait_client    = _modern_client
        app.state.calibration_scheduler = _modern_client.calibration
        app.state.telemetry_service     = _modern_client.telemetry

        # Start background telemetry sync loop as an asyncio Task
        app.state.telemetry_task = asyncio.create_task(
            _modern_client.telemetry.sync_loop(),
            name="telemetry-sync-loop",
        )
        # Start periodic calibration loop as an asyncio Task
        app.state.calibration_task = asyncio.create_task(
            _modern_client.calibration.schedule_loop(),
            name="calibration-schedule-loop",
        )
        logger.info("Phase 2 services started (ModernRAITClient + CalibrationScheduler + TelemetryService)")
    except Exception:
        logger.warning("Phase 2 services unavailable — portal runs in Phase 3 stub mode", exc_info=True)
        app.state.modern_settings      = None
        app.state.azure_evaluator      = None
        app.state.modern_rait_client    = None
        app.state.calibration_scheduler = None
        app.state.telemetry_service     = None
        app.state.telemetry_task        = None
        app.state.calibration_task      = None

    logger.info("Dummy Portal started — DB: %s", settings.sqlite_db_path)
    yield

    # Graceful shutdown: cancel background loops
    for task in (
        getattr(app.state, "telemetry_task", None),
        getattr(app.state, "calibration_task", None),
    ):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="RAIT Dummy Portal", version="1.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# JSON API routes
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(records.router)
app.include_router(dimensions.router)
app.include_router(telemetry.router)
app.include_router(scheduler_status.router)
app.include_router(evaluate.router)

# HTML routes (registered last so /records/{id} doesn't shadow /api/records)
app.include_router(ui.router)
