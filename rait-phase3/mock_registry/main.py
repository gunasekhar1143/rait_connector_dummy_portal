"""Mock Registry FastAPI application."""
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .config import settings
from .database import init_db
from .key_manager import KeyManager
from .routers import auth, calibrator, registry
from .state import RegistryState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_PROMPTS_PATH = Path(__file__).parent / "data" / "calibration_prompts.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    key_mgr = KeyManager(settings.rsa_key_dir)
    key_mgr.ensure_keys_exist()

    await init_db(settings.db_path)

    prompts = json.loads(_PROMPTS_PATH.read_text()) if _PROMPTS_PATH.exists() else []

    app.state.key_manager = key_mgr
    app.state.registry_state = RegistryState(token_ttl=settings.token_ttl_seconds)
    app.state.db_path = settings.db_path
    app.state.calibration_prompts = prompts

    logger.info("Mock Registry started — %d calibration prompts loaded", len(prompts))
    yield


app = FastAPI(title="RAIT Mock Registry", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router,       prefix="/api/model-registry")
app.include_router(registry.router,   prefix="/api/model-registry")
app.include_router(calibrator.router, prefix="/api/calibrator")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-registry"}
