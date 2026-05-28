# RAIT Phase 3 — Dummy Portal PoC

A fully local PoC of the RAIT (Responsible AI Testing) evaluation pipeline.  
No Azure credentials required — all evaluations use the built-in stub evaluator.

## Architecture

```
Driver Script
└─ rait_connector.RAITClient
     RAIT_API_URL    → http://localhost:8001   (Mock Registry)
     RAIT_INGEST_URL → http://localhost:8000   (Dummy Portal)
```

**Mock Registry** (port 8001): simulates all RAIT API endpoints — token auth, RSA public key, enabled metrics (DB-driven), calibration prompts.

**Dummy Portal** (port 8000): receives encrypted payloads, decrypts with RSA private key, stores in SQLite, renders a live dashboard with ethical dimension scores.

## Prerequisites

- Python 3.11+
- The `rait_connector` package installed in `../venv/` (already present)

## Setup

### 1. Install dependencies

```bash
cd rait-phase3
pip install -e ".[dev]"
# or install into the existing venv:
..\venv\Scripts\pip install fastapi uvicorn[standard] jinja2 python-multipart \
    aiosqlite pydantic-settings python-dotenv httpx requests pytest pytest-asyncio anyio \
    opentelemetry-sdk opentelemetry-instrumentation-fastapi
```

### 2. Configure environment

```bash
cp .env.example .env
# .env is pre-configured for local PoC — no changes needed for stub mode
```

### 3. Generate RSA key pair

```bash
python scripts/generate_keys.py
```

This creates `keys/rsa_private.pem` and `keys/rsa_public.pem`.  
**The private key is gitignored.** Generate it fresh on each machine.

## Running

Open **three terminals** in `rait-phase3/`:

**Terminal 1 — Mock Registry:**
```bash
..\venv\Scripts\uvicorn mock_registry.main:app --port 8001 --reload
```

**Terminal 2 — Dummy Portal:**
```bash
..\venv\Scripts\uvicorn dummy_portal.main:app --port 8000 --reload
```

**Terminal 3 — Demo:**
```bash
python scripts/demo_full_poc.py
```

Open **http://localhost:8000** in your browser to see the live dashboard.

## Individual Driver Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_evaluation.py` | Evaluate all 50 golden prompts |
| `scripts/run_telemetry.py`  | Post synthetic telemetry data |
| `scripts/run_calibration.py`| Post calibration responses |
| `scripts/demo_full_poc.py`  | All three flows in sequence |

All scripts load `.env` automatically and use `STUB_MODE=1` by default.

## Tests

```bash
# Unit + integration (no services required)
pytest tests/unit/ tests/integration/

# Functional (requires both services running)
pytest tests/functional/ -m functional
```

Expected output: **79 unit/integration tests + 7 functional tests = 86 total, 0 failures**.

## Dashboard

| URL | Description |
|-----|-------------|
| `http://localhost:8000/` | Live dashboard — dimension cards + record table |
| `http://localhost:8000/records/{id}` | Per-record drilldown |
| `http://localhost:8000/api/dimensions/summary` | JSON dimension scores |
| `http://localhost:8000/api/records` | JSON record list |
| `http://localhost:8000/health` | Health + record count |
| `http://localhost:8001/health` | Mock Registry health |

## Ethical Dimensions

| Dimension | Metric | Aggregation |
|-----------|--------|-------------|
| Bias & Fairness | Hate and Unfairness (Azure) | Weighted scorecard (70% high-risk) |
| Explainability & Transparency | Coherence (Azure) | Average |
| Security & Adversarial Robustness | Code Vulnerability (Azure) | MIN gate (threshold 0.5) |

## Real Azure Evaluators (Option A)

Set these in `.env` and run with `STUB_MODE=0`:

```ini
AZURE_OPENAI_ENDPOINT=https://...openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_SUBSCRIPTION_ID=...
AZURE_RESOURCE_GROUP=...
AZURE_PROJECT_NAME=...
AZURE_AI_PROJECT_URL=...
```

## Project Layout

```
rait-phase3/
├── .claude/agents/        # Custom sub-agents for implementation tasks
├── .claude/commands/      # Custom slash commands (/scaffold-fastapi, etc.)
├── dummy_portal/          # FastAPI ingestor service (port 8000)
├── mock_registry/         # FastAPI mock RAIT API (port 8001)
├── rait_connector_patches/ # v0.5.0 compatibility patches
├── scripts/               # Driver scripts
├── tests/                 # unit/, integration/, functional/
└── keys/                  # RSA key pair (rsa_private.pem gitignored)
```
