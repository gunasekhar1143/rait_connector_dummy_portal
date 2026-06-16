# Plan: Integrate Dummy Portal with RAIT Connector (Single-Module Dummy Evaluator)

## Context

The current evaluation flow lives entirely outside the portal — driver scripts monkey-patch `rait_connector`, call `RAITClient.evaluate()`, which calls Azure AI evaluators, encrypts results, and POSTs to the portal's ingest endpoint. The portal is a passive receiver.

The goal is to make the **Dummy Portal an active initiator**: expose a `POST /api/evaluate` endpoint that calls `RAITClient.evaluate()` internally, but with Azure evaluator calls replaced by a Dummy Evaluator Stub that returns the **exact same dict contract** as the real Azure SDK. Everything stays in one new file. The existing ingest, decryption, aggregation, DB, and dashboard remain unchanged.

---

## Current Flow (for reference)

```
External Driver Script
  load_dotenv() → RAIT_API_URL=:8001, RAIT_INGEST_URL=:8000
  Monkey-patch: _rc_module.Encryptor = EncryptorV2
  Monkey-patch: stub_evaluator.apply_stub()
  RAITClient.evaluate(prompt_id, query, response, ...)
    → get_enabled_metrics()   → Mock Registry :8001
    → EvaluatorOrchestrator.evaluate_metrics()
         → create_evaluator(metric_name) → Azure SDK class (STUBBED by stub_evaluator)
         → evaluator(query, response) → {"score": float}   ← stub format (not Azure-exact)
    → _post_evaluation() → encrypt → PUT /v1/{key} → Portal :8000
    → Portal stores in DB → dashboard reads aggregated scores
```

**Intercept point confirmed**: `create_evaluator()` in `rait_connector/evaluators/registry.py` is a free function that maps metric names to Azure evaluator instances. Replacing it is the minimal, cleanest patch — the orchestrator's parallelism, error handling, and `_update_metric_result()` all continue untouched.

---

## Target Flow

```
POST /api/evaluate  (new endpoint on Dummy Portal)
  → Apply dummy-evaluator patch (once at module load, not per-request)
  → Build RAITClient(rait_api_url=:8001, rait_ingest_url=:8000)
  → run_in_executor(client.evaluate(...))   ← RAITClient is sync
       → get_enabled_metrics()   → Mock Registry :8001
       → EvaluatorOrchestrator.evaluate_metrics()
            → create_evaluator(metric_name) → DummyEvaluator()  ← NEW
            → dummy_evaluator(query, response) → exact Azure dict   ← NEW
       → _post_evaluation() → encrypt → PUT /v1/{key} → Portal (self-call to :8000)
  → Return evaluation result JSON to caller
```

The portal calls its own ingest endpoint — this is intentional and correct. `RAIT_INGEST_URL` already points to `http://localhost:8000` in `.env`.

---

## Exact Azure Evaluator Return Contracts

Each dummy class must return this exact shape so future swap-in of real Azure classes is a one-line change.

| Metric (from Metric enum) | Azure Class | Dummy return dict |
|---|---|---|
| `HATE_AND_UNFAIRNESS_AZURE` | HateUnfairnessEvaluator | `{"hate_unfairness": "Low", "hate_unfairness_score": 2, "hate_unfairness_reason": str}` |
| `UNGROUNDED_ATTRIBUTES_AZURE` | UngroundedAttributesEvaluator | `{"ungrounded_attributes": "Low", "ungrounded_attributes_score": 1, "ungrounded_attributes_reason": str}` |
| `CONTENT_SAFETY_AZURE` | ContentSafetyEvaluator | `{"content_safety": "Safe", "content_safety_score": 0, "content_safety_reason": str}` |
| `PROTECTED_MATERIALS_AZURE` | ProtectedMaterialEvaluator | `{"protected_material_label": False, "protected_material_reason": str}` |
| `CODE_VULNERABILITY_AZURE` | CodeVulnerabilityEvaluator | `{"code_vulnerability": "Safe", "code_vulnerability_score": 0, "code_vulnerability_reason": str}` |
| `COHERENCE_AZURE` | CoherenceEvaluator | `{"coherence": 4.0, "coherence_reason": str}` |
| `FLUENCY_AZURE` | FluencyEvaluator | `{"fluency": 4.0, "fluency_reason": str}` |
| `QA_AZURE` | QAEvaluator | `{"qa": 4.0, "qa_reason": str}` |
| `SIMILARITY_AZURE` | SimilarityEvaluator | `{"similarity": 4.0, "similarity_reason": str}` |
| `RETRIEVAL_AZURE` | RetrievalEvaluator | `{"retrieval": 4.0, "retrieval_reason": str}` |
| `GROUNDEDNESS_AZURE` | GroundednessEvaluator | `{"groundedness": 4.0, "groundedness_reason": str}` |
| `GROUNDEDNESS_PRO_AZURE` | GroundednessProEvaluator | `{"groundedness_pro_label": True, "groundedness_pro_reason": str}` |
| `RELEVANCE_AZURE` | RelevanceEvaluator | `{"relevance": 4.0, "relevance_reason": str}` |
| `RESPONSE_COMPLETENESS_AZURE` | ResponseCompletenessEvaluator | `{"response_completeness": 4.0, "response_completeness_reason": str}` |
| `F1_SCORE_AZURE` | F1ScoreEvaluator | `{"f1_score": 0.85}` |
| `BLEU_AZURE` | BleuScoreEvaluator | `{"bleu_score": 0.72}` |
| `GLEU_AZURE` | GleuScoreEvaluator | `{"gleu_score": 0.68}` |
| `ROUGE_AZURE` | RougeScoreEvaluator | `{"rouge_score": 0.75}` |
| `METEOR_AZURE` | MeteorScoreEvaluator | `{"meteor_score": 0.70}` |
| `SEXUAL_AZURE` | SexualEvaluator | `{"sexual": "Safe", "sexual_score": 0, "sexual_reason": str}` |
| `VIOLENCE_AZURE` | ViolenceEvaluator | `{"violence": "Safe", "violence_score": 0, "violence_reason": str}` |
| `SELF_HARM_AZURE` | SelfHarmEvaluator | `{"self_harm": "Safe", "self_harm_score": 0, "self_harm_reason": str}` |

**Aggregation compatibility**: `aggregation_service._extract_score()` tries key `"score"` first, then any numeric value. All the above dicts contain at least one numeric value, so aggregation works correctly.

**Score ranges**: Safety evaluators use 0–7 integer severity scores. Quality evaluators use 1.0–5.0 floats. Statistical evaluators use 0.0–1.0 floats. Stubs use mid-range defaults for each type.

---

## Files to Change

### 1. CREATE `dummy_portal/routers/evaluate.py` (the single module)

Five sections in order:

**Section 1** — 22 `Stub<AzureClassName>` evaluator classes, each with `__call__(self, *, query, response, context="", ground_truth="") -> dict` returning the exact Azure contract from the table above.

**Section 2** — `_STUB_EVALUATOR_REGISTRY: dict[str, type]` mapping all 22 metric name strings → stub class, plus `StubFallbackEvaluator` for unknown metrics.

**Section 3** — Module-level patch (applied once at import):
```python
import rait_connector.evaluators.registry as _eval_registry
_original_create_evaluator = _eval_registry.create_evaluator

def _create_stub_evaluator(metric_name, model_config=None, azure_ai_project=None, credential=None):
    cls = _STUB_EVALUATOR_REGISTRY.get(metric_name, StubFallbackEvaluator)
    return cls()

def restore_real_evaluators():
    _eval_registry.create_evaluator = _original_create_evaluator

_eval_registry.create_evaluator = _create_stub_evaluator
```

Also apply EncryptorV2 patch here (portal's DecryptionEngine expects 0x02 version byte):
```python
import rait_connector.client as _rc_module
from rait_connector_patches.encryptor_v2 import EncryptorV2
_rc_module.Encryptor = EncryptorV2
```

**Section 4** — `EvaluateRequest` Pydantic model:
```python
class EvaluateRequest(BaseModel):
    prompt_id: str
    query: str
    response: str
    model_name: str
    model_version: str
    environment: str
    purpose: str
    prompt_url: str = ""
    timestamp: str = ""   # defaults to UTC now if blank
    ground_truth: str = ""
    context: str = ""
    parallel: bool = True
    max_workers: int = 5
```

**Section 5** — FastAPI router:
```python
router = APIRouter(prefix="/api", tags=["evaluate"])

@router.post("/evaluate")
async def evaluate(req: EvaluateRequest):
    client = RAITClient()
    ts = req.timestamp or datetime.now(timezone.utc).isoformat()
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.evaluate(
            prompt_id=req.prompt_id, prompt_url=req.prompt_url,
            timestamp=ts, model_name=req.model_name,
            model_version=req.model_version, query=req.query,
            response=req.response, environment=req.environment,
            purpose=req.purpose, ground_truth=req.ground_truth,
            context=req.context, parallel=req.parallel,
            max_workers=req.max_workers,
        )
    )
    return result
```

### 2. MODIFY `dummy_portal/main.py`

```python
from .routers import evaluate          # ← add after existing router imports
...
app.include_router(evaluate.router)    # ← add before app.include_router(ui.router)
```

---

## Important Constraints

- `rait_connector.config.settings` reads env vars at **module import**. `.env` must be loaded first — add `load_dotenv()` at top of `evaluate.py` before any `rait_connector` import.
- `RAITClient` is synchronous (uses `requests`) — must be called via `run_in_executor`.
- Portal self-calls its own `/v1/{key}` ingest endpoint — safe, separate HTTP connection.
- `restore_real_evaluators()` is exposed for test teardown.

---

## End-to-End Flow Confirmation

```
POST /api/evaluate (new)
  → RAITClient.evaluate()
       → DummyEvaluator()            ← returns exact Azure dict format
       → _post_evaluation()
            → EncryptorV2.encrypt()  ← RSA-OAEP + AES-GCM + 0x02 version byte
            → PUT /v1/{key}          ← portal's own existing ingest endpoint
                 → DecryptionEngine  ← unchanged
                 → IngestService     ← unchanged
                 → evaluation_results table ← unchanged
  → GET /api/dimensions/summary → same aggregation → same dashboard
```

---

## Verification

```bash
# 1. Start services
../venv/Scripts/uvicorn mock_registry.main:app --port 8001
../venv/Scripts/uvicorn dummy_portal.main:app --port 8000

# 2. Note current record count
curl -s http://localhost:8000/health

# 3. Call new endpoint
curl -s -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{"prompt_id":"test-001","query":"What is 2+2?","response":"4","model_name":"test-model","model_version":"1.0","environment":"testing","purpose":"integration-test"}'
# Expect: ethical_dimensions populated, post_response.status_code=200

# 4. Confirm record stored
curl -s http://localhost:8000/health          # record_count + 1
curl -s http://localhost:8000/api/dimensions/summary  # sample_count increased
```

**Unit tests** — `tests/unit/test_dummy_evaluators.py`: assert each Stub class returns exact dict shape, no live services needed.

**Integration tests** — `tests/integration/test_evaluate_endpoint.py`: POST via TestClient, assert ethical_dimensions populated, record in DB, aggregation scores non-empty.

---

## Future Swap to Real Azure Evaluators

1. Remove `_eval_registry.create_evaluator = _create_stub_evaluator` (or call `restore_real_evaluators()`)
2. Set Azure env vars in `.env`
3. No other changes needed — router, DB, aggregation, dashboard all unchanged
