"""Router for /api/evaluate — migrated to src.client.RAITClient (Phase 2).

Exposes:
  POST /api/evaluate              — evaluate a prompt/response pair
  POST /api/generate-and-evaluate — generate a stub response, then evaluate it

Internal evaluation path:
  Legacy (removed):  rait_connector.RAITClient.evaluate() + 6 module-level patches
                     + run_in_executor wrapper + 22 StubXxxEvaluator classes
  Current (Phase 2): src.client.RAITClient.evaluate()
                        -> EvaluationService.run()  (asyncio.gather, no threads)
                        -> AuthService              (async token + public-key cache)
                        -> src.security.crypto      (single encrypt_v2 implementation)
                        -> PUT /v1/{key}            (httpx, no thread pool)

Endpoint URLs, request/response models, DB schema, and dashboard integration are
unchanged. The migration is internal to this file only.
"""
import json as _json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..dependencies import db_dependency

logger = logging.getLogger(__name__)

# ── Stub response generator (kept for POST /api/generate-and-evaluate) ───────
# Generates domain-aware stub LLM responses from query text.
# Separate from the stub evaluator system in src/stubs — this concerns
# response generation, not score generation.

_MEDICAL_KEYWORDS = {
    "patient", "dose", "dosage", "treatment", "diagnosis", "clinical",
    "drug", "medication", "hospital", "surgery", "symptom", "disease",
    "therapy", "prescription", "antibiotic", "vaccine", "insulin",
    "stroke", "sepsis", "cancer", "infection", "physician", "nurse",
}
_FINANCE_KEYWORDS = {
    "investment", "portfolio", "tax", "ira", "401k", "client", "financial",
    "broker", "fiduciary", "sec", "finra", "annuity", "fund", "equity",
    "margin", "cryptocurrency", "roth", "retirement", "advisor", "suitability",
}
_SECURITY_KEYWORDS = {
    "vulnerability", "exploit", "sql", "injection", "xss", "cve", "attack",
    "authentication", "encryption", "firewall", "malware", "phishing",
    "penetration", "owasp", "patch", "cybersecurity", "breach", "threat",
}

_STUB_RESPONSES = {
    "medical": (
        "Based on clinical guidelines, the recommended management includes immediate "
        "assessment of vital signs, appropriate diagnostic workup, and evidence-based "
        "treatment protocols. Always consult with a qualified healthcare provider."
    ),
    "financial": (
        "Under applicable securities regulations and fiduciary standards, the appropriate "
        "approach requires full disclosure of material risks, suitability assessment, and "
        "compliance with regulatory requirements including Regulation Best Interest."
    ),
    "security": (
        "The identified security concern represents a significant vulnerability. "
        "Immediate remediation steps include input validation, parameterised queries, "
        "and following OWASP secure coding guidelines. Perform a security audit."
    ),
    "general": (
        "This query requires careful consideration of relevant domain expertise, "
        "regulatory requirements, and ethical guidelines. Please consult appropriate "
        "subject matter experts before taking action."
    ),
}


class StubResponseGenerator:
    """Generates a domain-aware stub response from a query without calling an LLM."""

    def __call__(self, query: str) -> str:
        tokens = set(query.lower().split())
        if tokens & _MEDICAL_KEYWORDS:
            return _STUB_RESPONSES["medical"]
        if tokens & _FINANCE_KEYWORDS:
            return _STUB_RESPONSES["financial"]
        if tokens & _SECURITY_KEYWORDS:
            return _STUB_RESPONSES["security"]
        return _STUB_RESPONSES["general"]


async def _azure_generate_response(query: str, settings) -> str:
    """Call Azure OpenAI to generate a response for query. Requires has_azure_openai=True."""
    from openai import AsyncAzureOpenAI
    client = AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    completion = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[{"role": "user", "content": query}],
        max_tokens=512,
        temperature=0.3,
    )
    return completion.choices[0].message.content or ""


async def _generate_response(query: str, request: Request) -> str:
    """Return an LLM response: Azure OpenAI if credentials present, else stub."""
    settings = getattr(request.app.state, "modern_settings", None)
    if settings is not None and settings.has_azure_openai:
        try:
            return await _azure_generate_response(query, settings)
        except Exception:
            logger.warning("Azure OpenAI generation failed — falling back to stub", exc_info=True)
    return _stub_generator(query)


# ── Request models ────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    query: str
    prompt_id: str = ""           # auto-generated UUID if blank
    prompt_response_id: str = ""  # auto-generated UUID if blank
    response: str = ""            # stub generator fills if blank
    model_name: str = ""          # falls back to config
    model_version: str = ""
    environment: str = ""
    purpose: str = ""
    prompt_url: str = ""
    timestamp: str = ""
    ground_truth: str = ""
    context: str = ""
    parallel: bool = True
    max_workers: int = 5


class GenerateAndEvaluateRequest(BaseModel):
    query: str
    prompt_id: str = ""           # auto-generated UUID if blank
    prompt_response_id: str = ""  # auto-generated UUID if blank
    model_name: str = ""          # falls back to config
    model_version: str = ""
    environment: str = ""
    purpose: str = ""
    prompt_url: str = ""
    timestamp: str = ""
    ground_truth: str = ""
    context: str = ""
    parallel: bool = True
    max_workers: int = 5


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api", tags=["evaluate"])
_stub_generator = StubResponseGenerator()


def _get_client(request: Request):
    """Return the ModernRAITClient from app.state, raising 503 if unavailable."""
    client = getattr(request.app.state, "modern_rait_client", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service unavailable — Phase 2 client not initialised.",
        )
    return client


async def _backfill_evaluation_results(
    db: aiosqlite.Connection,
    result: dict,
    query: str,
    response: str,
    prompt_response_id: str,
    prompt_url: str,
    ground_truth: str,
    context: str,
) -> None:
    """Update evaluation_results with fields that EvaluationService doesn't put
    in the encrypted payload (query, response, ground_truth, context, etc.).
    Parsed record_id comes from post_response so we target the exact row."""
    try:
        post = result.get("post_response", {})
        record_id = _json.loads(post.get("response", "{}")).get("record_id")
        if not record_id:
            return
        await db.execute(
            """UPDATE evaluation_results
               SET query=?, response=?, ground_truth=?, context=?,
                   prompt_url=?, post_response=?
               WHERE record_id=?""",
            (
                query or None,
                response or None,
                ground_truth or None,
                context or None,
                prompt_url or None,
                _json.dumps({
                    "prompt_response_id": prompt_response_id,
                    "calibration_run_id": "",
                }),
                record_id,
            ),
        )
        await db.commit()
    except Exception:
        logger.warning("Could not backfill evaluation_results for record", exc_info=True)


@router.post("/evaluate")
async def evaluate(
    req: EvaluateRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dependency),
):
    """Evaluate a prompt via src.client.RAITClient (Phase 2 async path).

    Internally uses EvaluationService.run() with asyncio.gather — no thread pool,
    no module-level patches. The encrypted payload and DB record are structurally
    identical to the legacy rait_connector path.
    """
    if not req.prompt_id:
        req.prompt_id = str(_uuid.uuid4())
    if not req.prompt_response_id:
        req.prompt_response_id = str(_uuid.uuid4())
    ts = req.timestamp or datetime.now(timezone.utc).isoformat()
    response = req.response or await _generate_response(req.query, request)
    client = _get_client(request)
    try:
        result = await client.evaluate(
            prompt_id=req.prompt_id,
            prompt_response_id=req.prompt_response_id,
            prompt_url=req.prompt_url,
            timestamp=ts,
            model_name=req.model_name,
            model_version=req.model_version,
            query=req.query,
            response=response,
            environment=req.environment,
            purpose=req.purpose,
            ground_truth=req.ground_truth,
            context=req.context,
            parallel=req.parallel,
            max_workers=req.max_workers,
        )
    except Exception as exc:
        logger.exception("Evaluation failed for prompt_id=%s", req.prompt_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _backfill_evaluation_results(
        db, result,
        query=req.query,
        response=response,
        prompt_response_id=req.prompt_response_id,
        prompt_url=req.prompt_url,
        ground_truth=req.ground_truth,
        context=req.context,
    )
    return result


@router.post("/generate-and-evaluate")
async def generate_and_evaluate(
    req: GenerateAndEvaluateRequest,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dependency),
):
    """Generate a stub response for the query, then evaluate it.

    Returns the generated response alongside the full evaluation result so the
    caller can see what text was evaluated.
    """
    if not req.prompt_id:
        req.prompt_id = str(_uuid.uuid4())
    if not req.prompt_response_id:
        req.prompt_response_id = str(_uuid.uuid4())
    generated_response = await _generate_response(req.query, request)
    ts = req.timestamp or datetime.now(timezone.utc).isoformat()
    client = _get_client(request)
    try:
        evaluation = await client.evaluate(
            prompt_id=req.prompt_id,
            prompt_response_id=req.prompt_response_id,
            prompt_url=req.prompt_url,
            timestamp=ts,
            model_name=req.model_name,
            model_version=req.model_version,
            query=req.query,
            response=generated_response,
            environment=req.environment,
            purpose=req.purpose,
            ground_truth=req.ground_truth,
            context=req.context,
            parallel=req.parallel,
            max_workers=req.max_workers,
        )
    except Exception as exc:
        logger.exception("Generate-and-evaluate failed for prompt_id=%s", req.prompt_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _backfill_evaluation_results(
        db, evaluation,
        query=req.query,
        response=generated_response,
        prompt_response_id=req.prompt_response_id,
        prompt_url=req.prompt_url,
        ground_truth=req.ground_truth,
        context=req.context,
    )
    return {"generated_response": generated_response, "evaluation": evaluation}
