"""Stub evaluator for CI / no-credentials environments.

Patches EvaluatorOrchestrator.evaluate_metrics to return realistic scores
without calling Azure AI services.

Scoring data (BASE_SCORES, DEFAULT_SCORES, domain detection, jitter) is
imported from src/stubs — the canonical single source of truth for stub data
shared with the Phase 2 async service layer (src/services/evaluation_service.py).

This module is temporary migration scaffolding for the legacy RAITClient
(rait_connector v0.8.0). When the legacy connector is retired in favour of
src/client.py, this file will be removed. The scoring data in src/stubs
will remain as the sole implementation.

Usage:
    from rait_connector_patches.stub_evaluator import apply_stub
    apply_stub()   # call before RAITClient() is constructed
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Ensure rait_connector and src/ are both importable
_ROOT = Path(__file__).parent.parent
_VENV = _ROOT.parent / "venv" / "Lib" / "site-packages"
for p in [str(_ROOT), str(_VENV)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Import scoring data from the canonical source in src/stubs
from src.stubs import (  # noqa: E402
    BASE_SCORES as _BASE_SCORES,
    DEFAULT_SCORES as _DEFAULT_SCORES,
    _jitter,
    _infer_domain,
)


def _get_score(prompt_data: dict[str, Any], metric_name: str) -> float:
    """Return a domain-aware stub score (0-5 scale) for use in the legacy pipeline."""
    query = prompt_data.get("query") or ""
    prompt_id = query[:10]  # first chars as a rough domain hint
    domain_key = _infer_domain(query)
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
    return {
        "subscription_id":     "00000000-stub-stub-stub-000000000000",
        "resource_group_name": "stub-rg",
        "project_name":        "stub-project",
    }


def _stub_get_model_config(self):
    return None


def _stub_get_credential(self):
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

    Safe to call multiple times — only applies once.
    """
    if _active_patches:
        return

    from rait_connector.evaluators import EvaluatorOrchestrator
    from rait_connector.client import RAITClient

    targets = [
        (EvaluatorOrchestrator, "evaluate_metrics",            _stub_evaluate_metrics),
        (RAITClient,            "_get_azure_ai_project",       _stub_get_azure_ai_project),
        (RAITClient,            "_get_model_config",           _stub_get_model_config),
        (RAITClient,            "_get_credential",             _stub_get_credential),
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
