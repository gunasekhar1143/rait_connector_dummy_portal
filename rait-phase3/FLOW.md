# Phase 3 — Dummy Portal: Complete Implementation Flow

> **Purpose of this document:** Explain to any new team member what was built, why, and how every file fits into the system — in the exact order it was created. No line-by-line explanation; focus on files, classes, functions, and their roles.

---

## 1. What Was the Task?

The **Architecture Transformation Proposal** defines 5 phases for evolving `rait_connector` into an enterprise-grade AI safety engine.

**Phase 3 — "Integration & Governance Setup"** requires:

| Requirement (from Proposal) | What We Built |
|-----------------------------|---------------|
| Dummy Portal as a mock RAIT ingestor | `dummy_portal/` FastAPI service on port 8000 |
| v2-capable decryption engine (RSA-OAEP + AES-GCM, `0x02` version byte) | `dummy_portal/decryption.py` |
| Dashboard to visualise ethical dimension scores | `dummy_portal/ui/` (Jinja2 + vanilla JS) |
| Metric Registry mocking (3 ethical dimensions → 3 Azure AI metrics) | `mock_registry/` FastAPI service on port 8001 |
| 50 "Golden Prompts" across medical, financial, safety-critical domains | `mock_registry/data/calibration_prompts.json` |

There is **no production system yet** — everything the `rait_connector` library calls must be simulated locally.

---

## 2. System Architecture (Big Picture)

```
Driver Script (scripts/)
│   load_dotenv() → RAIT_API_URL=localhost:8001, RAIT_INGEST_URL=localhost:8000
│   EncryptorV2 patch → all payloads get 0x02 version byte
│   Stub evaluator patch → bypasses Azure AI credential checks
│
├── rait_connector.RAITClient
│       │
│       │  Auth + config calls
│       ▼
│   Mock Registry  (port 8001)          ← simulates production RAIT API
│       POST /api/model-registry/token/
│       GET  /api/model-registry/public-key/
│       GET  /api/model-registry/enabled-metrics/  ← reads from registry.db
│       GET  /api/calibrator/calibration-run-prompts/
│
│       │  Encrypted payload
│       ▼
│   Dummy Portal  (port 8000)           ← the main Phase 3 deliverable
│       PUT  /v1/{key}                  ← receives encrypted payloads
│       GET  /api/dimensions/summary    ← aggregated ethical scores
│       GET  /                          ← live HTML dashboard
│
└── SQLite databases
        mock_registry/registry.db  → dimension/metric config
        dummy_portal/portal.db     → all ingest records + scores
```

---

## 3. Pre-Work: Understanding the Codebase

Before writing a single line, two explorations were done:

### 3a. Reading `rait_connector` (installed package)
**Path:** `C:\Users\HC User\Downloads\RAIT\venv\Lib\site-packages\rait_connector\`

Key facts discovered:
- `encryption.py` → `Encryptor.encrypt()` packs bytes as `[4B key_len **little-endian**][enc_aes_key][12B nonce][16B GCM tag][ciphertext]`
- `auth.py` → `get_token()` sends **JSON body** `{"client_id": ..., "client_secret": ...}` (not OAuth2 form)
- `client.py` → `EvaluatorOrchestrator.evaluate_metrics()` is the method to patch for stub mode
- `config.py` → `settings = Settings()` runs at **module scope** — reads all `RAIT_*` and `AZURE_*` env vars on import

These facts directly shaped `decryption.py`, `mock_registry/routers/auth.py`, and `stub_evaluator.py`.

### 3b. Reading the Architecture Transformation Proposal
Key facts extracted:
- Exactly 3 ethical dimensions with their aggregation strategies (min_gate / weighted_scorecard / average)
- `0x02` version byte requirement for v2 encryption format
- 50 Golden Prompts across medical, financial, safety-critical domains
- Three-tier test structure: unit / integration / functional

---

## 4. Sequential File Creation — Milestone by Milestone

---

### MILESTONE 1 — Foundation + RSA Keys + Decrypt Roundtrip

**Goal:** Get the project structure in place and prove encryption works before building anything else.

---

#### `scripts/generate_keys.py`
**What it does:** Generates an RSA-2048 key pair.
- `generate_keys()` — creates `keys/rsa_private.pem` (chmod 600) and `keys/rsa_public.pem`
- Run once, files are gitignored (except public key)

---

#### `dummy_portal/decryption.py`  ← **Highest-risk file, built first**
**What it does:** Decrypts payloads sent by `rait_connector`.

| Class / Method | Role |
|---------------|------|
| `DecryptionError` | Custom exception — raised on any decryption failure |
| `DecryptionEngine` | Main class holding the RSA private key |
| `DecryptionEngine.from_pem_path()` | Class method — loads private key from disk, validates key size ≥ 2048 bits |
| `DecryptionEngine.decrypt()` | Entry point — base64-decodes payload, checks first byte for `0x02` (v2) or treats as v1, routes accordingly |
| `DecryptionEngine._decrypt_package()` | Core logic — unpacks `[4B key_len LE][enc_aes_key][nonce][tag][ciphertext]`, RSA-decrypts the AES key, AES-GCM decrypts the payload |

**Why built first:** The entire portal is useless if it cannot decrypt incoming payloads. The endianness of `key_len` (`little-endian`, confirmed from `rait_connector` source) had to be verified before anything else.

---

#### `rait_connector_patches/encryptor_v2.py`
**What it does:** Makes `rait_connector` emit v2-format payloads.

| Class / Method | Role |
|---------------|------|
| `EncryptorV2(Encryptor)` | Subclass of the connector's `Encryptor` |
| `EncryptorV2.encrypt()` | Prepends `b'\x02'` to all encrypted output — driver scripts monkey-patch this class in before evaluation |

---

#### `tests/unit/test_decryption_v2.py`  ← **M1 acceptance gate**
**What it does:** Proves the roundtrip works using the real connector's `Encryptor`.

| Test Class | What it checks |
|-----------|----------------|
| `TestV1Roundtrip` | Encrypt with `Encryptor` → decrypt with `DecryptionEngine` → original plaintext |
| `TestV2Roundtrip` | Encrypt with `EncryptorV2` → first byte is `0x02` → decrypt → original plaintext |
| `TestDecryptionErrors` | Invalid base64, truncated payload, wrong private key all raise `DecryptionError` |

---

### MILESTONE 2 — Mock Registry (All 7 Endpoints + DB-Driven Metrics)

**Goal:** Give `rait_connector` a fully working RAIT API to talk to, with metrics stored in a database rather than hardcoded.

---

#### `mock_registry/database.py`
**What it does:** Creates and seeds `registry.db` with 3 normalized tables.

| Function | Role |
|---------|------|
| `init_db()` | Creates tables, enables WAL mode and foreign keys, calls `_seed()` |
| `_seed()` | INSERT OR IGNORE into `dimensions`, `metrics`, `dimension_metrics` — idempotent, safe to call on every startup |

**Tables created:**
- `dimensions` — dimension_id, dimension_name, aggregation_strategy, safety_threshold, display_order
- `metrics` — metric_id, metric_name, description
- `dimension_metrics` — dimension_id + metric_id + weight + risk_tier (many-to-many join table)

---

#### `mock_registry/seed_data.py`
**What it does:** Holds Python constants for the 3 dimensions and 3 metrics.
- `SEED_DIMENSIONS` — 3 tuples: Bias & Fairness (weighted_scorecard), Explainability (average), Security (min_gate)
- `SEED_METRICS` — metric names must **exactly match** `rait_connector.constants.Metric` enum strings (e.g. `"Hate and Unfairness (Azure)"`)
- `SEED_DIMENSION_METRICS` — links with weights (Bias→0.7 high_risk, others→1.0 standard)

---

#### `mock_registry/key_manager.py`
**What it does:** Generates or loads the RSA key pair for the registry.
- `KeyManager.ensure_keys_exist()` — generates 2048-bit RSA pair if not present
- `KeyManager.get_public_key_pem()` — returns the public key PEM string served to `rait_connector`

---

#### `mock_registry/state.py`
**What it does:** In-memory runtime state (no DB needed for this).

| Class | Role |
|-------|------|
| `RegistryState` | Holds token store + calibration run tracking |
| `store_token()` | Saves `{token → (client_id, expires_at)}` |
| `validate_token()` | Checks token exists and has not expired — returns `client_id` or `None` |
| `create_run()` | Registers a new calibration run ID |
| `complete_all_pending_runs()` | Marks all open runs complete (called after `update-prompts-response`) |

---

#### `mock_registry/routers/auth.py`
**Endpoint:** `POST /api/model-registry/token/`
- `get_token()` — accepts `{"client_id", "client_secret"}` JSON body (not form data — confirmed from connector source), issues a random bearer token, stores it in `RegistryState`

---

#### `mock_registry/routers/registry.py`
**Endpoints:** `GET /public-key/`, `GET /enabled-metrics/`, `GET /calibration-prompts/`
- `get_public_key()` — returns RSA public key PEM from `KeyManager`
- `get_enabled_metrics()` — runs a JOIN across `dimensions + dimension_metrics + metrics` tables → returns `{"data": [...]}` envelope (connector calls `data.get("data", [])`)
- `get_calibration_prompts()` — returns all 50 prompts wrapped in `{"data": [...]}`

---

#### `mock_registry/routers/calibrator.py`
**Endpoints:** `GET /calibration-run-prompts/`, `GET /get-prompts-response/`, `POST /update-prompts-response/`
- `get_calibration_run_prompts()` — generates UUID run_id, returns `{"data": {"calibration_run_id": ..., "prompts": [...]}}`
- `get_prompts_response()` — returns `{"data": [{"prompts": [...]}]}` (connector flattens group arrays)
- `update_prompts_response()` — calls `state.complete_all_pending_runs()`, returns `{"status_code": 200}`

---

#### `mock_registry/data/calibration_prompts.json`
**50 golden prompts:**
- 17 medical (`gp-med-*`) — clinical decisions, medication, diagnosis
- 17 financial (`gp-fin-*`) — investment advice, regulatory compliance, fraud
- 16 security (`gp-sec-*`) — SQL injection, JWT vulnerabilities, code security

---

#### `mock_registry/main.py`
**What it does:** FastAPI app entry point for the registry.
- `lifespan()` — initialises key pair, seeds `registry.db`, loads calibration prompts, attaches everything to `app.state`
- Routes: `auth.router` → `/api/model-registry`, `registry.router` → `/api/model-registry`, `calibrator.router` → `/api/calibrator`

---

#### `tests/integration/test_mock_registry.py`  ← **M2 acceptance gate**
18 tests covering: token issuance, auth middleware (401 on missing/expired), public key validity, DB-driven metrics, 50 prompts, all calibrator endpoints.

---

### MILESTONE 3 — Ingest Endpoint + Storage

**Goal:** Accept real encrypted payloads from `rait_connector`, decrypt them, and persist to DB.

---

#### `dummy_portal/database.py`
**What it does:** Creates and seeds `portal.db` with 6 tables.

| Function | Role |
|---------|------|
| `init_db()` | Creates all tables, enables WAL mode + foreign keys, seeds strategy tables |
| `get_db()` | Async generator yielding an `aiosqlite.Connection` — used as FastAPI dependency |

**Tables created:**
- `dimension_strategies` — portal's local copy of aggregation rules (does not call registry at runtime)
- `metric_weights` — portal's local copy of metric weights
- `ingest_records` — one row per encrypted payload received (the master log)
- `evaluation_results` — parsed evaluation data linked to `ingest_records`
- `telemetry_records` — parsed Azure Monitor telemetry blobs
- `calibration_records` — parsed calibration response arrays

---

#### `dummy_portal/services/ingest_service.py`
**What it does:** Orchestrates the full receive → decrypt → parse → store pipeline.

| Method | Role |
|--------|------|
| `process()` | Entry point — calls decrypt, inserts `ingest_records` row, routes to sub-table |
| `_store_record()` | Inserts into `ingest_records`, returns `lastrowid` |
| `_store_evaluation()` | Parses `ethical_dimensions` from payload, inserts into `evaluation_results` |
| `_store_telemetry()` | Stores raw Azure Monitor JSON into `telemetry_records` |
| `_store_calibration()` | Stores `calibration_responses` array into `calibration_records` |

---

#### `dummy_portal/routers/ingest.py`
**Endpoint:** `PUT /v1/{key:path}`

| Function | Role |
|---------|------|
| `ingest()` | FastAPI route — creates `DecryptionEngine` from `app.state`, creates `IngestService`, calls `service.process()`, returns `{status, record_id}` or raises HTTP 422 on decryption failure |
| `_is_v2()` | Helper — peeks at base64 payload to detect v2 (byte 0 = 0x02) for OTel span attribute |

Also wraps the call in **OpenTelemetry spans**: `ingest.receive` and `ingest.decrypt` with `model_name`, `log_type`, `version` attributes.

---

#### `rait_connector_patches/stub_evaluator.py`
**What it does:** Patches 5 methods on `RAITClient` and `EvaluatorOrchestrator` so evaluations work without Azure credentials.

| Function | Role |
|---------|------|
| `apply_stub()` | Applies all 5 patches using `unittest.mock.patch.object` |
| `remove_stub()` | Reverses all patches |
| `_stub_evaluate_metrics()` | Returns fake `ethical_dimensions` with domain-aware scores (medical/financial/security) |
| `_stub_get_azure_ai_project()` | Returns dummy dict to satisfy credential check |
| `_stub_get_model_config()` | Returns `None` — never used by the stub evaluator |
| `_stub_get_credential()` | Returns `None` |
| `_stub_run_background_calibration()` | No-op that removes the model key from `_running_calibrations` so `wait_for_calibration()` returns `True` immediately |
| `_get_score()` | Generates deterministic jitter scores based on query content (medical/financial/security domain detection) |

---

#### `tests/integration/test_ingest_endpoint.py`  ← **M3 acceptance gate**
10 tests: v1 roundtrip, v2 roundtrip, all 3 log types stored in correct sub-tables, invalid base64 → 422, wrong key → 422.

---

### MILESTONE 4 — Dashboard API + DB-Driven Aggregation

**Goal:** Expose all data through a JSON REST API. The aggregation strategy for each dimension must come from the database — no hardcoded `if dimension_name == "Bias"` logic anywhere.

---

#### `dummy_portal/services/aggregation_service.py`
**What it does:** Reads aggregation config from DB and computes dimension scores.

| Method | Role |
|--------|------|
| `_load_strategies()` | Queries `dimension_strategies` + `metric_weights` → returns `{dimension_id: {strategy, threshold, weights}}` |
| `_apply_strategy()` | Applies `min_gate` / `weighted_scorecard` / `average` to a dict of `{metric_name: [scores]}` → returns `(avg, min, max, is_safe)` |
| `compute_summary()` | Takes a list of evaluation DB rows, extracts scores per dimension per metric, calls `_apply_strategy()` for each dimension, returns `List[DimensionScore]` |
| `_extract_score()` | Module-level helper — extracts a float from `metric_metadata` dict; tries `"score"` key first, then first numeric value (handles both stub and real Azure evaluator output) |

---

#### `dummy_portal/services/query_service.py`
**What it does:** All database read operations for the API layer.

| Method | Role |
|--------|------|
| `list_records()` | Paginated query on `ingest_records` with optional `log_type` / `model_name` filters |
| `get_record()` | Fetches one `ingest_records` row + deserialises `decrypted_payload` JSON |
| `get_dimension_summary()` | Joins `evaluation_results` + `ingest_records`, calls `AggregationService.compute_summary()`, returns `DimensionSummary` |
| `list_telemetry()` | Joins `telemetry_records` + `ingest_records`, deserialises `raw_telemetry` JSON |
| `_build_where()` | Builds SQL `WHERE` clause dynamically from optional filters; accepts `alias=""` for direct queries or `alias="ir"` for JOIN queries |

---

#### `dummy_portal/routers/records.py`
**Endpoints:** `GET /api/records`, `GET /api/records/{record_id}`
- `list_records()` — calls `QueryService.list_records()`, supports `log_type`, `model_name`, `skip`, `limit`
- `get_record()` — calls `QueryService.get_record()`, raises 404 if not found

---

#### `dummy_portal/routers/dimensions.py`
**Endpoint:** `GET /api/dimensions/summary`
- `get_dimension_summary()` — calls `QueryService.get_dimension_summary()`, returns `DimensionSummary` with all 3 (or more) dimensions from DB

---

#### `dummy_portal/routers/telemetry.py`
**Endpoint:** `GET /api/telemetry`
- `list_telemetry()` — calls `QueryService.list_telemetry()`, returns list of `TelemetryRecord`

---

#### `dummy_portal/routers/scheduler_status.py`
**Endpoints:** `POST /api/scheduler/status`, `GET /api/scheduler/status`
- **Push model:** driver scripts call `scheduler.status()` and POST the JSON here after each tick
- `push_scheduler_status()` — stores job list in `app.state.scheduler_status`
- `get_scheduler_status()` — returns last stored list

---

#### `dummy_portal/models/schemas.py`
**What it does:** All Pydantic v2 models for request/response validation.

| Model | Used for |
|-------|---------|
| `IngestPayload` | Validates incoming `PUT /v1/{key}` body |
| `IngestResponse` | Response from ingest: `{status, record_id}` |
| `RecordSummary` | One row in the record list |
| `RecordDetail` | Full record with `decrypted_payload` |
| `RecordList` | Paginated `{items, total}` wrapper |
| `DimensionScore` | One dimension with `avg_score`, `min_score`, `max_score`, `is_safe`, `sample_count` |
| `DimensionSummary` | List of `DimensionScore` + `evaluated_at` + `total_records` |
| `TelemetryRecord` | One telemetry entry with `raw_telemetry` dict |
| `SchedulerJob` | One scheduler job: `{id, trigger, next_run, is_executing}` |

---

#### `tests/unit/test_aggregation.py` + `tests/unit/test_is_safe.py`  ← **M4 acceptance gate**
27 tests: score extraction from dict, all 3 strategies with real DB fixtures, boundary at exactly 0.5, weighted scorecard with known weights.

#### `tests/integration/test_dashboard_api.py`
17 tests: seed 5 records → verify `sample_count=5`, pagination, 404 on missing record, scheduler push/pull.

---

### MILESTONE 5 — Jinja2 Dashboard UI

**Goal:** Render a live HTML dashboard driven entirely from the database — no hardcoded dimension names.

---

#### `dummy_portal/ui/templates/base.html`
Jinja2 base layout — header, container div, `{% block content %}` and `{% block scripts %}` slots.

#### `dummy_portal/ui/templates/dashboard.html`
**What it does:** Main dashboard page.
- `{% for dim in dimensions %}` — iterates the `dimensions` list from `QueryService`; adding a 4th DB row causes a 4th card with zero HTML changes
- Each `<article>` has `data-dimension-id="{{ dim.dimension_id }}"` — used by JS to update in-place without page reload
- `<tbody id="records-tbody">` — records table updated by JS polling

#### `dummy_portal/ui/templates/record_detail.html`
**What it does:** Per-record drilldown.
- Shows model metadata grid
- Renders per-metric scores in a table for evaluation records
- Collapsible `<details>` blocks for raw decrypted payload and connector logs

#### `dummy_portal/ui/static/js/dashboard.js`
**What it does:** Auto-refresh logic.
- `refreshDimensions()` — `fetch("/api/dimensions/summary")` → updates each card by `data-dimension-id`
- `refreshRecords()` — `fetch("/api/records?limit=20")` → rebuilds `records-tbody` innerHTML
- `refreshDashboard()` — calls both, updates `#refresh-status` element
- `setInterval(refreshDashboard, 10000)` — runs every 10 seconds

#### `dummy_portal/ui/static/css/dashboard.css`
- CSS Grid 3-column layout for dimension cards (collapses to 2→1 on mobile)
- `.badge.safe` → `#2ecc71` (green), `.badge.unsafe` → `#e74c3c` (red)
- `article.dimension-card.safe` → green left border, `.unsafe` → red left border

---

#### `dummy_portal/routers/ui.py`
**Endpoints:** `GET /`, `GET /records/{record_id}`

| Function | Role |
|---------|------|
| `dashboard()` | Calls `QueryService.get_dimension_summary()` + `list_records(limit=20)`, renders `dashboard.html` via Jinja2 |
| `record_detail()` | Calls `QueryService.get_record()`, renders `record_detail.html`; 404 if not found |
| `_get_templates()` | Helper — fetches `Jinja2Templates` from `app.state` (set in lifespan) |

---

#### `dummy_portal/telemetry_setup.py`
**What it does:** OpenTelemetry setup (gracefully no-ops if SDK not installed).

| Function | Role |
|---------|------|
| `setup_otel()` | Creates `TracerProvider` with `ConsoleSpanExporter`, registers it globally |
| `get_tracer()` | Returns active tracer or `_NullTracer` if OTel is unavailable |
| `_NullTracer` / `_NullSpan` | Drop-in no-ops so instrumented code works even without the SDK |

---

#### `dummy_portal/main.py`
**What it does:** FastAPI app entry point — wires everything together.

| Section | Role |
|---------|------|
| `lifespan()` | Runs at startup: `init_db()`, loads RSA private key into `app.state`, creates `Jinja2Templates`, adds `tojson` filter, calls `setup_otel()` |
| Router registration | `health` → `ingest` → `records` → `dimensions` → `telemetry` → `scheduler_status` → `ui` (HTML routes last so `/records/{id}` doesn't shadow `/api/records`) |
| Static mount | `/static` → `dummy_portal/ui/static/` |

---

### MILESTONE 6 — 50 Golden Prompts + Evaluation Flow

**Goal:** Run all 50 golden prompts through `rait_connector.evaluate_batch()` and verify the portal shows 50 evaluation records with populated dimension scores.

---

#### `scripts/run_evaluation.py`
**What it does:** Main evaluation driver.

| Function | Role |
|---------|------|
| `main()` | Orchestrates the full flow |
| `_check_services()` | HTTP health checks both services before starting |
| `_get_response()` | Returns a domain-aware stub response string based on `prompt_id` prefix |
| `_push_scheduler_status()` | POSTs `scheduler.status()` to portal after evaluation completes |

**Key ordering (mandatory):**
1. `from dotenv import load_dotenv; load_dotenv()` — first 2 lines
2. Apply `EncryptorV2` monkey-patch
3. Apply `stub_evaluator.apply_stub()`
4. Only then import `rait_connector`

---

#### `tests/functional/test_evaluation_flow.py`  ← **M6 acceptance gate**
2 functional tests (require live services): 5-prompt end-to-end → assert portal DB has ≥ 5 new records, `/api/dimensions/summary` returns 3 dimensions with `sample_count > 0`.

---

### MILESTONE 7 — Telemetry + Calibration Flows

---

#### `scripts/run_telemetry.py`
**What it does:** Posts Azure Monitor-style telemetry data to the portal.
- `_make_stub_telemetry()` — creates realistic `{AppDependencies, AppExceptions, AppAvailabilityResults}` dict
- `main()` — in stub mode bypasses `fetch_telemetry()` (requires Azure) and calls `client.post_telemetry()` directly with stub data

---

#### `scripts/run_calibration.py`
**What it does:** Fetches calibration prompts and posts stub model responses.
- `_invoke_model()` — generates a domain-aware stub response for a given prompt
- `main()` — calls `client.get_model_calibration_prompts()` → generates stub responses → calls `client.post_calibration_responses()` → `client.wait_for_calibration()`

---

#### `tests/functional/test_telemetry_flow.py`
2 functional tests: `post_telemetry()` succeeds, `GET /api/telemetry` returns ≥ 1 record.

#### `tests/functional/test_calibration_flow.py`
2 functional tests: fetch prompts → post 3 stub responses → verify calibration record in DB; `wait_for_calibration()` returns `True`.

---

### MILESTONE 8 — Full PoC Demo + OTel + README

---

#### `scripts/demo_full_poc.py`
**What it does:** Single-command demonstration of the entire Phase 3 pipeline.

| Function | Role |
|---------|------|
| `main()` | Runs all 3 flows sequentially, prints final summary table |
| `_check_services()` | Pre-flight health checks |
| `run_evaluation()` | Evaluates 10 representative prompts via `evaluate_batch()`, prints timing |
| `run_telemetry()` | Posts stub telemetry data |
| `run_calibration()` | Fetches 50 prompts, posts 10 stub responses |
| `print_summary()` | Reads portal DB directly + calls `/api/dimensions/summary`, prints a table with scores per dimension |
| `_db_counts()` | Counts rows per `log_type` directly from `portal.db` |

---

#### `rait_connector_patches/README.md`
Documents all known `rait_connector` v0.5.0 gaps and the patches applied — for the Phase 4 team.

#### `rait_connector_patches/async_wrapper.py`
Phase 4 prep only — `run_in_executor` wrappers for when the portal needs to call the connector from an async context. Not used in Phase 3.

---

## 5. Supporting Infrastructure Files

### Configuration

| File | Class | Role |
|------|-------|------|
| `mock_registry/config.py` | `RegistrySettings` | `env_prefix="REGISTRY_"` — reads `REGISTRY_*` env vars; prevents collision with connector's global `RAIT_*` reads |
| `dummy_portal/config.py` | `PortalSettings` | `env_prefix="PORTAL_"` — reads `PORTAL_*` env vars |
| `.env.example` | — | Template with all 3 namespaces: unprefixed `RAIT_*` (for connector), `REGISTRY_*`, `PORTAL_*` |

### Dependency Injection

| File | Function | Role |
|------|---------|------|
| `dummy_portal/dependencies.py` | `db_dependency()` | Async generator — yields an `aiosqlite.Connection` per request, used as `Depends(db_dependency)` in all routers |
| `dummy_portal/dependencies.py` | `get_decryption_engine()` | Returns `DecryptionEngine` from `request.app.state` — loaded once at startup, reused per request |

### `.claude/` — Project Automation

| Directory | Files | What they are |
|-----------|-------|--------------|
| `.claude/agents/` | 6 `.md` files | Custom sub-agents — `explore-connector`, `schema-designer`, `test-generator`, `security-reviewer`, `integration-verifier`, `observability-auditor` |
| `.claude/commands/` | 6 `.md` files | Custom slash commands — `/scaffold-fastapi`, `/setup-db-schema`, `/validate-encryption`, `/test-api-contracts`, `/scaffold-dashboard`, `/wire-connector` |

---

## 6. Test Summary

| Tier | Files | Count | Requires live services? |
|------|-------|-------|------------------------|
| Unit | `tests/unit/test_decryption_v2.py`, `test_aggregation.py`, `test_is_safe.py` | 34 | No |
| Integration | `tests/integration/test_mock_registry.py`, `test_ingest_endpoint.py`, `test_dashboard_api.py` | 45 | No (uses `TestClient`) |
| Functional | `tests/functional/test_evaluation_flow.py`, `test_telemetry_flow.py`, `test_calibration_flow.py` | 6 | Yes — both services must be running |
| **Total** | | **85** | |

Run unit + integration: `pytest tests/unit/ tests/integration/`  
Run functional: `pytest tests/functional/ -m functional`

---

## 7. How to Run the System

```bash
cd C:\Users\HC User\Downloads\RAIT\rait-phase3

# Step 1 — one-time key generation
..\venv\Scripts\python scripts/generate_keys.py

# Step 2 — start services (two terminals)
..\venv\Scripts\uvicorn mock_registry.main:app --port 8001   # Terminal A
..\venv\Scripts\uvicorn dummy_portal.main:app  --port 8000   # Terminal B

# Step 3 — run the full demo
set RAIT_API_URL=http://localhost:8001
set RAIT_INGEST_URL=http://localhost:8000
set RAIT_CLIENT_ID=demo-client
set RAIT_CLIENT_SECRET=demo-secret
set PYTHONIOENCODING=utf-8
..\venv\Scripts\python scripts/demo_full_poc.py

# Step 4 — open dashboard
start http://localhost:8000
```
