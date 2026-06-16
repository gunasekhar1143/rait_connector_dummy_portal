# Phase 2 Implementation Plan — Core Modernization

## Scope Decision
- **All code stays inside `rait-phase3/`** — new `src/` subdirectory added within the existing structure
- **EncryptorV2 is sufficient for the PoC** — `decryption.py` already handles v2 format; AEAD/HardenedEncryptor skipped
- **Protocols.py is optional** — add only if implementation slows without interface clarity
- **Build-then-wire strategy** — build and test each service standalone first, wire into Dummy Portal after

## Status

| Step | File | Status |
|------|------|--------|
| 1 | `src/config.py` | DONE |
| 2 | `src/services/auth_service.py` | DONE |
| 3 | `src/services/evaluation_service.py` | DONE |
| 4 | `src/security/kql_builder.py` | DONE |
| 5 | `src/services/telemetry_service.py` | DONE |
| 6 | `src/services/calibration_scheduler.py` | DONE |
| 7 | `src/client.py` | DONE |
| 8 | `tests/functional/demo_parallel_execution.py` | DONE |
| 9 | Wire into `dummy_portal/main.py` + `scheduler_status.py` | DONE |

All 79 unit + integration tests passing. Benchmark: asyncio.gather ~0.51s vs ThreadPoolExecutor ~1.00s (2.0x faster).

---

## New Directory Structure (inside existing `rait-phase3/`)

```
rait-phase3/src/
├── __init__.py
├── config.py                        # Pydantic V2 BaseSettings, no os.environ side effects
├── client.py                        # Thin RAITClient facade
├── security/
│   ├── __init__.py
│   └── kql_builder.py              # Parameterized KQL (for TelemetryService)
└── services/
    ├── __init__.py
    ├── auth_service.py             # Async token lifecycle (httpx)
    ├── evaluation_service.py       # asyncio.gather parallel dispatch — core demo
    ├── telemetry_service.py        # Async batched sync, asyncio.sleep loop
    └── calibration_scheduler.py   # asyncio.Event replacing threading.Lock
```

Modified existing files:
- `dummy_portal/main.py` — Phase 2 services wired into lifespan
- `dummy_portal/routers/scheduler_status.py` — real CalibrationScheduler state + POST /api/scheduler/calibration/start
- `tests/integration/test_dashboard_api.py` — updated for new scheduler status response shape

---

## What Each Module Does

### `src/config.py`
Pydantic V2 `BaseSettings` with per-instance isolation. No `os.environ` side effects.

**Key change from legacy:** Legacy `rait_connector/config.py` runs a `@model_validator` that calls
`os.environ["AZURE_CLIENT_ID"] = ...` on every instantiation (global side effect). New config stays
local to the instance.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    rait_api_url: str = "http://localhost:8001"
    rait_ingest_url: str = "http://localhost:8000"
    rait_client_id: str = "demo-client"
    rait_client_secret: str = "demo-secret"
    telemetry_sync_interval: float = 60.0
    calibration_timeout: float = 30.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

---

### `src/services/auth_service.py`
Async token lifecycle with `httpx.AsyncClient`, proactive 30-second refresh buffer.

```python
class AuthService:
    async def ensure_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at - 30:
            return self._token
        # fetch new token via POST /api/model-registry/token/
        ...
```

---

### `src/services/evaluation_service.py`
**The central Phase 2 artifact** — `asyncio.gather` replaces `ThreadPoolExecutor`.

```
Legacy (rait_connector v0.8.0):
    ThreadPoolExecutor → 3 OS threads → ~1.0s for 3 x 0.5s evaluations

Revised (this module):
    asyncio.gather → 1 thread, 3 concurrent tasks → ~0.5s for 3 x 0.5s evaluations
```

- Fetches public key + enabled metrics from registry concurrently
- Runs all metric evaluators via `asyncio.gather`
- Builds `ethical_dimensions` payload (compatible with portal aggregation)
- Encrypts with v2 wire format (RSA-OAEP + AES-256-GCM, 0x02 version byte)
- POSTs to portal ingest endpoint

---

### `src/security/kql_builder.py`
Parameterized KQL builder — replaces f-string interpolation.

```python
# Legacy (brittle, injection risk):
query = f"AppRequests | where AppId == '{app_id}'"

# Revised (parameterized, escaped):
query = KQLBuilder().table("AppRequests").filter("AppId", app_id).time_range(60).build()
```

---

### `src/services/telemetry_service.py`
Async batched telemetry sync — `asyncio.sleep` loop replaces polling daemon thread.

```
Legacy: daemon thread calls fetch_telemetry() in blocking loop (consumes OS thread)
Revised: asyncio.sleep yields to event loop (no thread consumed)
```

- `sync_once()` — one fetch + upload cycle
- `sync_loop()` — runs as an asyncio.Task in portal lifespan
- Produces structured JSON logs showing asyncio context switches (Phase 4 evidence)

---

### `src/services/calibration_scheduler.py`
Async cooperative calibration — eliminates `threading.Lock` race conditions (R1).

```
Legacy: threading.Lock + _running_calibrations set → check-then-act race
Revised: asyncio.Event → set() is atomic within event loop → no race
```

- `start(run_id)` — kicks off calibration task, returns immediately
- `wait_complete(timeout)` — awaits asyncio.Event with timeout
- Full calibration cycle: fetch prompts → generate stub responses → post to registry → ingest to portal

---

### `src/client.py`
Thin `RAITClient` facade — zero business logic, pure service composition.

```python
class RAITClient:
    def __init__(self, config=None):
        cfg = config or Settings()
        self.auth = AuthService(cfg)
        self.eval = EvaluationService(self.auth, cfg)
        self.telemetry = TelemetryService(self.auth, cfg)
        self.calibration = CalibrationScheduler(self.auth, cfg)

    async def evaluate(self, **kwargs) -> dict:
        return await self.eval.run(**kwargs)
```

---

### `tests/functional/demo_parallel_execution.py`
Phase 4 + Phase 5 primary artifact — proves the architectural shift.

```
Result (actual measured):
  asyncio.gather (9 tasks, 0.5s each):   0.507s  (modernized)
  ThreadPoolExecutor (9 tasks, 0.5s ea):  1.004s  (legacy pattern)
  asyncio path is 2.0x faster in wall time
```

Run with: `../venv/Scripts/python tests/functional/demo_parallel_execution.py`

---

## Remaining Work (Phase 4 + Phase 5)

### Phase 4 — Verification (requires live services)
1. Start both services and run full flow benchmark:
   ```
   ../venv/Scripts/uvicorn mock_registry.main:app --port 8001
   ../venv/Scripts/uvicorn dummy_portal.main:app --port 8000
   ../venv/Scripts/python tests/functional/demo_parallel_execution.py
   ```
2. Run 50 Golden Prompts via `POST /api/generate-and-evaluate`
3. Capture OTel traces from console exporter
4. Verify dashboard at `http://localhost:8000` shows all 3 dimension scores

### Phase 5 — Architecture Walk-through
1. Use `PHASE2_PLAN.md` (this file) as the anchor document for the narrative
2. Live demo flow:
   - Trigger `POST /api/evaluate` with a Golden Prompt
   - Show encrypted v2 payload hitting portal (`PUT /v1/{key}`)
   - Show decrypted metric in `GET /api/records`
   - Show aggregated Ethical Dimension scores on dashboard

### Phase 1 — Infrastructure (lowest priority for PoC)
- IaC templates (Terraform/Bicep for Azure AI Project, OpenAI, Log Analytics)
- CI/CD pipeline (`.github/workflows/ci.yml`)
