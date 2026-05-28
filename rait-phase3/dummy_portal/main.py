"""Dummy Portal FastAPI application."""
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import init_db
from .decryption import DecryptionEngine
from .routers import dimensions, health, ingest, records, scheduler_status, telemetry, ui
from .telemetry_setup import setup_otel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_STATIC_DIR    = Path(__file__).parent / "ui" / "static"
_TEMPLATES_DIR = Path(__file__).parent / "ui" / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(settings.sqlite_db_path)

    app.state.db_path          = settings.sqlite_db_path
    app.state.decryption_engine = DecryptionEngine.from_pem_path(settings.rsa_private_key_path)
    app.state.scheduler_status = []
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["tojson"] = lambda v, indent=None: json.dumps(v, indent=indent, default=str)
    app.state.templates = templates

    setup_otel(exporter=settings.otel_exporter)
    logger.info("Dummy Portal started — DB: %s", settings.sqlite_db_path)
    yield


app = FastAPI(title="RAIT Dummy Portal", version="1.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# JSON API routes
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(records.router)
app.include_router(dimensions.router)
app.include_router(telemetry.router)
app.include_router(scheduler_status.router)

# HTML routes (registered last so /records/{id} doesn't shadow /api/records)
app.include_router(ui.router)
