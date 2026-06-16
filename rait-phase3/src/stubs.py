"""Canonical stub data for the Phase 2 service layer.

Single source of truth for:
  - Domain-aware text responses (medical / financial / security)
  - Stub evaluator scores (0-5 scale, domain-aware, deterministic jitter)
  - Normalized scores (0-1 scale) for the new async pipeline

Consumers:
  - src/services/evaluation_service.py   (new async pipeline)
  - src/services/calibration_scheduler.py (async calibration responses)
  - rait_connector_patches/stub_evaluator.py (legacy sync pipeline — temporary)

rait_connector_patches/ is temporary migration scaffolding. When the legacy
RAITClient is retired, stub_evaluator.py will be removed and this module
remains as the sole stub implementation.
"""
import hashlib

# ── Domain text responses ─────────────────────────────────────────────────────
# Keyed by prompt_id prefix (gp-med, gp-fin, gp-sec).

DOMAIN_RESPONSES: dict[str, str] = {
    "gp-med": (
        "Based on clinical guidelines, the recommended approach involves thorough "
        "assessment and evidence-based treatment protocols. Always consult a "
        "qualified healthcare provider before making clinical decisions."
    ),
    "gp-fin": (
        "Under applicable securities regulations and fiduciary standards, full "
        "disclosure of material risks and suitability assessment are required "
        "before any recommendation. Comply with Regulation Best Interest."
    ),
    "gp-sec": (
        "The identified vulnerability requires input validation, parameterised "
        "queries, and strict adherence to OWASP secure coding guidelines. "
        "Perform a thorough security audit before deployment."
    ),
}

DEFAULT_RESPONSE: str = (
    "This query requires careful consideration of domain expertise, regulatory "
    "requirements, and ethical guidelines. Consult appropriate subject matter "
    "experts before taking action."
)


def stub_text_response(prompt_id: str) -> str:
    """Return a domain-aware stub text response for the given prompt_id."""
    for prefix, text in DOMAIN_RESPONSES.items():
        if prompt_id.startswith(prefix):
            return text
    return DEFAULT_RESPONSE


# ── Stub evaluator scores (0–5 scale, matching Azure AI Evaluator convention) ─
# Keyed by domain prefix, then metric name.

BASE_SCORES: dict[str, dict[str, float]] = {
    "gp-med": {
        # Hate and Unfairness: lower = less hateful = safer (Azure convention: higher = worse)
        "Hate and Unfairness (Azure)": 0.8,
        "Coherence (Azure)":           4.0,
        "Code Vulnerability (Azure)":  4.5,
    },
    "gp-fin": {
        "Hate and Unfairness (Azure)": 0.6,
        "Coherence (Azure)":           4.1,
        "Code Vulnerability (Azure)":  4.3,
    },
    "gp-sec": {
        "Hate and Unfairness (Azure)": 0.9,
        "Coherence (Azure)":           3.9,
        # Intentionally lower — security prompts surface code risks
        "Code Vulnerability (Azure)":  3.1,
    },
}

DEFAULT_SCORES: dict[str, float] = {
    "Hate and Unfairness (Azure)": 0.8,  # low = safe; high = harmful
    "Coherence (Azure)":           3.8,
    "Code Vulnerability (Azure)":  4.0,
}

_SCORE_MAX = 5.0


def _jitter(base: float, prompt_id: str, metric_name: str) -> float:
    """Deterministic jitter ±0.15 on 0-5 scale, derived from prompt_id + metric_name.

    Uses MD5 purely as a deterministic hash — not for any security purpose.
    """
    h = int(hashlib.md5(f"{prompt_id}:{metric_name}".encode()).hexdigest(), 16)
    delta = (h % 7 - 3) * 0.05   # range: -0.15 to +0.15
    return round(max(0.0, min(_SCORE_MAX, base + delta)), 2)


def _infer_domain(query: str) -> str | None:
    """Infer domain key from query text keywords."""
    lower = query.lower()
    if any(k in lower for k in ("patient", "dose", "clinical", "diagnosis", "mg", "pregnant")):
        return "gp-med"
    if any(k in lower for k in ("invest", "sec", "finra", "ira", "broker", "tax", "aml")):
        return "gp-fin"
    if any(k in lower for k in ("sql", "vulnerability", "jwt", "injection", "hash", "password", "exploit")):
        return "gp-sec"
    return None


def stub_score_raw(
    metric_name: str,
    query: str = "",
    prompt_id: str = "",
) -> float:
    """Return a domain-aware stub score on 0–5 scale with deterministic jitter.

    Domain is inferred first from prompt_id prefix, then from query keywords.
    Falls back to DEFAULT_SCORES if neither matches.
    """
    # Prefer prompt_id prefix detection (authoritative in test datasets)
    domain_key: str | None = None
    for prefix in BASE_SCORES:
        if prompt_id.startswith(prefix):
            domain_key = prefix
            break
    # Fall back to keyword detection on query text
    if domain_key is None:
        domain_key = _infer_domain(query)

    base = (BASE_SCORES.get(domain_key) or DEFAULT_SCORES).get(metric_name, 3.8)
    return _jitter(base, prompt_id or query[:20], metric_name)


def stub_score_normalized(
    metric_name: str,
    query: str = "",
    prompt_id: str = "",
) -> float:
    """Return a domain-aware stub score normalized to 0–1.

    Score direction is metric-dependent:
      - Hate and Unfairness: lower = less hateful = safer
      - Coherence, Code Vulnerability: higher = better = safer
    """
    return round(stub_score_raw(metric_name, query, prompt_id) / _SCORE_MAX, 4)
