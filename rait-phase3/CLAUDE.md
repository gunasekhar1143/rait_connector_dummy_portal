# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the services

`rait_connector` (v0.8.0) lives in `../venv/` and is not on PyPI. Both services must be started from the `rait-phase3/` directory so relative paths resolve correctly.

```bash
# Terminal 1 — Mock Registry (must start first; generates RSA key pair on first boot)
../venv/Scripts/uvicorn mock_registry.main:app --port 8001 --reload

# Terminal 2 — Dummy Portal
../venv/Scripts/uvicorn dummy_portal.main:app --port 8000 --reload

# Terminal 3 — populate data (requires both services running)
../venv/Scripts/python scripts/demo_full_poc.py
```

Environment variables (copy `.env.example` → `.env`, defaults work for stub mode):

```
RAIT_API_URL=http://localhost:8001
RAIT_INGEST_URL=http://localhost:8000
RAIT_CLIENT_ID=demo-client
RAIT_CLIENT_SECRET=demo-secret
```

## Running tests

```bash
# Unit + integration (no live services needed)
../venv/Scripts/pytest tests/unit/ tests/integration/

# Single test file
../venv/Scripts/pytest tests/unit/test_decryption_v2.py

# Single test
../venv/Scripts/pytest tests/unit/test_decryption_v2.py::TestV2Roundtrip::test_roundtrip

# Functional tests (requires both services running)
../venv/Scripts/pytest tests/functional/ -m functional
```

## Architecture

Two FastAPI services + a shared `rait_connector_patches/` compatibility layer.

```
Driver Script (scripts/)
  └─ RAITClient (rait_connector, installed in ../venv/)
        ├─ Auth/config calls → Mock Registry  :8001
        └─ Encrypted payload → Dummy Portal   :8000
```

### Mock Registry (`mock_registry/`, port 8001)
Simulates the production RAIT API. On startup, `KeyManager.ensure_keys_exist()` generates an RSA-2048 key pair into `keys/` if absent. Serves the public key to `rait_connector` and validates bearer tokens in memory via `RegistryState`. All metric/dimension config is DB-driven (`registry.db`) — seeded once via `INSERT OR IGNORE` in `database.py`.

### Dummy Portal (`dummy_portal/`, port 8000)
The main deliverable. On startup, loads `keys/rsa_private.pem` into `app.state.decryption_engine` (shared across requests). Ingest endpoint `PUT /v1/{key}` decrypts payloads and routes them into one of four sub-tables (`evaluation_results`, `telemetry_records`, `calibration_records`, `ingest_records`). The dashboard at `GET /` and `GET /api/dimensions/summary` compute ethical scores dynamically from the DB using the aggregation strategy stored per-dimension (`min_gate` / `weighted_scorecard` / `average`).

### `rait_connector_patches/`
Three patches applied **before** any `rait_connector` import in driver scripts:
- `encryptor_v2.py` — `EncryptorV2` subclass that prepends `b'\x02'` (version byte) to every encrypted payload. The portal's `DecryptionEngine` checks byte 0 to route v1 vs v2 decryption.
- `stub_evaluator.py` — monkey-patches `EvaluatorOrchestrator.evaluate_metrics` to return domain-aware scores (medical/financial/security) without Azure credentials. Apply with `apply_stub()` before constructing `RAITClient`.
- `async_wrapper.py` — Phase 4 prep only; not used in Phase 3.

### Critical ordering in driver scripts
```python
from dotenv import load_dotenv
load_dotenv()          # MUST be before all other imports

import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2   # patch before RAITClient()
```
`rait_connector.config` reads `RAIT_*` and `AZURE_*` env vars at **module scope on import**, so `.env` must be loaded first.

### Encryption format
`rait_connector` encrypts as: `[4B key_len little-endian][RSA-encrypted AES key][12B nonce][16B GCM tag][ciphertext]`. `EncryptorV2` prepends `b'\x02'`. `DecryptionEngine._decrypt_package()` in `dummy_portal/decryption.py` mirrors this exactly — endianness is `little-endian` (confirmed from connector source).

### Database layout
- `keys/` — shared RSA key pair (`rsa_private.pem` gitignored, regenerate with `scripts/generate_keys.py`)
- `mock_registry/registry.db` — dimensions, metrics, dimension_metrics, token state
- `dummy_portal/portal.db` — ingest_records, evaluation_results, telemetry_records, calibration_records, dimension_strategies, metric_weights

Both DBs use `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;` and are seeded idempotently (`INSERT OR IGNORE`) on every startup.

### Dependency injection pattern (Dummy Portal)
`DecryptionEngine` is instantiated once at startup and stored in `app.state`. All routers access it via `Depends(get_decryption_engine)` from `dependencies.py`. The DB connection is a per-request async generator via `Depends(db_dependency)`.

## Docker

```bash
# Build and start both services (from rait-phase3/)
docker compose up --build

# Run the demo to populate data
docker compose --profile demo run --rm demo
```

Build context is the parent `RAIT/` directory (to access `../venv/Lib/site-packages/rait_connector/`). The `mock-registry` service must be healthy before `dummy-portal` starts (it generates the RSA keys into the shared `keys` volume).
