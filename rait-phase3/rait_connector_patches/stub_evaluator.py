"""Stub evaluator for CI / no-credentials environments.

Patches EvaluatorOrchestrator.evaluate_metrics to return realistic scores
without calling Azure AI services. Scores are domain-aware based on prompt_id prefix.

Usage:
    from rait_connector_patches.stub_evaluator import apply_stub
    apply_stub()   # call before RAITClient() is constructed
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Ensure rait_connector is importable
_VENV = Path(__file__).parent.parent.parent / "venv" / "Lib" / "site-packages"
if str(_VENV) not in sys.path:
    sys.path.insert(0, str(_VENV))

# ── Domain-aware score tables ────────────────────────────────────────────────

_BASE_SCORES: dict[str, dict[str, float]] = {
    "gp-med": {
        "Hate and Unfairness (Azure)":   4.2,
        "Coherence (Azure)":             4.0,
        "Code Vulnerability (Azure)":    4.5,
    },
    "gp-fin": {
        "Hate and Unfairness (Azure)":   3.7,
        "Coherence (Azure)":             4.1,
        "Code Vulnerability (Azure)":    4.3,
    },
    "gp-sec": {
        "Hate and Unfairness (Azure)":   4.0,
        "Coherence (Azure)":             3.9,
        "Code Vulnerability (Azure)":    3.1,   # lower — code security domain intentionally flagged
    },
}

_DEFAULT_SCORES: dict[str, float] = {
    "Hate and Unfairness (Azure)":  4.0,
    "Coherence (Azure)":            3.8,
    "Code Vulnerability (Azure)":   4.0,
}


def _jitter(base: float, prompt_id: str, metric_name: str) -> float:
    """Deterministic jitter ±0.3 based on prompt_id + metric_name hash."""
    h = int(hashlib.md5(f"{prompt_id}:{metric_name}".encode()).hexdigest(), 16)
    delta = (h % 7 - 3) * 0.05   # range: -0.15 to +0.15
    return round(max(0.0, min(5.0, base + delta)), 2)


def _get_score(prompt_data: dict[str, Any], metric_name: str) -> float:
    prompt_id = prompt_data.get("query", "")[:10]   # use first chars as domain hint
    # Try to infer domain from query content or use default
    query_lower = (prompt_data.get("query") or "").lower()
    if any(k in query_lower for k in ("patient", "dose", "clinical", "diagnosis", "mg", "pregnant")):
        domain_key = "gp-med"
    elif any(k in query_lower for k in ("invest", "sec", "finra", "ira", "broker", "tax", "aml")):
        domain_key = "gp-fin"
    elif any(k in query_lower for k in ("sql", "vulnerability", "jwt", "injection", "hash", "password", "exploit")):
        domain_key = "gp-sec"
    else:
        domain_key = None

    base = (_BASE_SCORES.get(domain_key) or _DEFAULT_SCORES).get(metric_name, 3.8)
    return _jitter(base, prompt_id, metric_name)


def _stub_evaluate_metrics(
    self,
    prompt_data: dict[str, Any],
    ethical_dimensions: list[dict[str, Any]],
    parallel: bool = True,
    max_workers: int = 5,
    fail_fast: bool = False,
) -> list[dict[str, Any]]:
    """Drop-in replacement for EvaluatorOrchestrator.evaluate_metrics."""
    result = []
    for dim in ethical_dimensions:
        populated_metrics = []
        for metric in dim.get("dimension_metrics", []):
            metric_name = metric.get("metric_name", "")
            score = _get_score(prompt_data, metric_name)
            populated_metrics.append({
                **metric,
                "metric_metadata": {"score": score},
            })
        result.append({**dim, "dimension_metrics": populated_metrics})
    return result


# ── Dummy Azure config stubs ──────────────────────────────────────────────────

def _stub_get_azure_ai_project(self):
    """Return a dummy Azure AI project dict to satisfy credential checks."""
    return {
        "subscription_id":    "00000000-stub-stub-stub-000000000000",
        "resource_group_name": "stub-rg",
        "project_name":        "stub-project",
    }


def _stub_get_model_config(self):
    """Return None — evaluate_metrics stub never uses it."""
    return None


def _stub_get_credential(self):
    """Return None — evaluate_metrics stub never calls Azure."""
    return None


def _stub_run_background_calibration(
    self,
    model_name: str = "",
    model_version: str = "",
    environment: str = "",
    purpose: str = "",
    connector_logs: str = "",
    calibration_data=None,
    **kwargs,
):
    """No-op stub that cleans up _running_calibrations so wait_for_calibration() returns True."""
    self._running_calibrations.discard((model_name, model_version, environment))


# ── Public API ────────────────────────────────────────────────────────────────

_active_patches: list = []


def apply_stub() -> None:
    """Patch RAITClient and EvaluatorOrchestrator to bypass Azure credentials.

    Patches applied:
      - EvaluatorOrchestrator.evaluate_metrics → returns stub scores
      - RAITClient._get_azure_ai_project → returns dummy dict
      - RAITClient._get_model_config → returns None
      - RAITClient._get_credential → returns None
      - RAITClient._run_background_calibration → no-op (avoids unpatched background threads)

    Safe to call multiple times — only applies once.
    """
    if _active_patches:
        return

    from rait_connector.evaluators import EvaluatorOrchestrator
    from rait_connector.client import RAITClient

    targets = [
        (EvaluatorOrchestrator, "evaluate_metrics",          _stub_evaluate_metrics),
        (RAITClient,            "_get_azure_ai_project",     _stub_get_azure_ai_project),
        (RAITClient,            "_get_model_config",         _stub_get_model_config),
        (RAITClient,            "_get_credential",           _stub_get_credential),
        (RAITClient,            "_run_background_calibration", _stub_run_background_calibration),
    ]
    for obj, attr, replacement in targets:
        p = patch.object(obj, attr, replacement)
        p.start()
        _active_patches.append(p)


def remove_stub() -> None:
    """Restore all patched methods."""
    for p in reversed(_active_patches):
        p.stop()
    _active_patches.clear()
