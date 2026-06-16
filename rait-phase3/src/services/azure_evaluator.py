"""Azure AI Evaluator wrapper — one evaluator instance per metric, run in thread pool.

The azure-ai-evaluation SDK evaluators are synchronous blocking calls; we run each
one in asyncio's default thread pool via run_in_executor so they don't block the
event loop.

Metric → evaluator mapping:

  Metric name                       Evaluator class             Score key             Needs
  ────────────────────────────────  ──────────────────────────  ────────────────────  ──────────────────────
  Hate and Unfairness (Azure)       HateUnfairnessEvaluator     hate_unfairness_score  AI Project + credential
  Coherence (Azure)                 CoherenceEvaluator          coherence_score        Azure OpenAI model_config
  Code Vulnerability (Azure)        CodeVulnerabilityEvaluator  code_vulnerability_score AI Project + credential

Output normalisation:
  Raw Azure dict is stored as-is (e.g. {"hate_unfairness": "Medium", "hate_unfairness_score": 4, ...}).
  A "score" key is added equal to the Azure numeric score so that:
    - AggregationService._extract_score() finds it on the "score" fast-path
    - MetricClassifier.enrich_ethical_dimensions() can feed it to predict()
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

logger = logging.getLogger(__name__)

# ── Per-metric descriptor ─────────────────────────────────────────────────────
# (azure_score_key, needs_ai_project, needs_openai)
_METRIC_DESCRIPTORS: dict[str, tuple[str, bool, bool]] = {
    "Hate and Unfairness (Azure)": ("hate_unfairness_score",    True,  False),
    "Coherence (Azure)":           ("coherence",                False, True),
    "Code Vulnerability (Azure)":  ("code_vulnerability_score", True,  False),
}


class AzureEvaluatorService:
    """Initialises one Azure AI evaluator per metric and exposes an async evaluate()."""

    def __init__(self, config) -> None:
        self._config = config
        self._evaluators: dict[str, tuple[Any, str]] = {}  # metric → (evaluator, score_key)
        self._setup()

    # ── Setup helpers ─────────────────────────────────────────────────────────

    def _credential(self):
        """Return Azure credential: ClientSecretCredential if SP vars set, else DefaultAzureCredential."""
        cfg = self._config
        if cfg.azure_client_id and cfg.azure_tenant_id and cfg.azure_client_secret:
            from azure.identity import ClientSecretCredential
            return ClientSecretCredential(
                tenant_id=cfg.azure_tenant_id,
                client_id=cfg.azure_client_id,
                client_secret=cfg.azure_client_secret,
            )
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential()

    def _azure_ai_project(self):
        """Return AI project as URL string or dict depending on what's configured."""
        cfg = self._config
        if cfg.azure_ai_project_url:
            return cfg.azure_ai_project_url
        return {
            "subscription_id":     cfg.azure_subscription_id,
            "resource_group_name": cfg.azure_resource_group,
            "project_name":        cfg.azure_project_name,
        }

    def _model_config(self) -> dict:
        cfg = self._config
        return {
            "azure_endpoint":    cfg.azure_openai_endpoint,
            "api_key":           cfg.azure_openai_api_key,
            "azure_deployment":  cfg.azure_openai_deployment,
            "api_version":       cfg.azure_openai_api_version,
        }

    def _setup(self) -> None:
        from azure.ai.evaluation import (
            HateUnfairnessEvaluator,
            CoherenceEvaluator,
            CodeVulnerabilityEvaluator,
        )

        _cls_map = {
            "Hate and Unfairness (Azure)": HateUnfairnessEvaluator,
            "Coherence (Azure)":           CoherenceEvaluator,
            "Code Vulnerability (Azure)":  CodeVulnerabilityEvaluator,
        }

        for metric_name, (score_key, needs_project, needs_openai) in _METRIC_DESCRIPTORS.items():
            cls = _cls_map[metric_name]
            try:
                if needs_project and self._config.has_azure_ai_project:
                    evaluator = cls(
                        credential=self._credential(),
                        azure_ai_project=self._azure_ai_project(),
                    )
                    self._evaluators[metric_name] = (evaluator, score_key)
                    logger.info("Azure evaluator ready: %s", metric_name)
                elif needs_openai and self._config.has_azure_openai:
                    evaluator = cls(model_config=self._model_config())
                    self._evaluators[metric_name] = (evaluator, score_key)
                    logger.info("Azure evaluator ready: %s", metric_name)
                else:
                    logger.debug(
                        "Azure evaluator skipped (credentials absent): %s", metric_name
                    )
            except Exception:
                logger.warning(
                    "Azure evaluator failed to initialise for %s — will use stub",
                    metric_name, exc_info=True,
                )

    # ── Public API ────────────────────────────────────────────────────────────

    def has_evaluator(self, metric_name: str) -> bool:
        return metric_name in self._evaluators

    async def evaluate(self, metric_name: str, query: str, response: str) -> dict[str, Any]:
        """Run the Azure evaluator for metric_name in a thread; returns normalised dict.

        Raises KeyError if no evaluator is registered for metric_name.
        """
        evaluator, score_key = self._evaluators[metric_name]
        loop = asyncio.get_running_loop()
        raw: dict = await loop.run_in_executor(
            None,
            partial(evaluator, query=query, response=response),
        )
        # Add "score" key so AggregationService and LR classifier both find it.
        score_val = raw.get(score_key)
        if score_val is not None:
            raw["score"] = float(score_val)
        elif "code_vulnerability_label" in raw:
            # CodeVulnerabilityEvaluator returns a boolean label, not a numeric score.
            # Map to 0-5 scale: no vulnerability → 5.0 (safe, above 2.5 threshold),
            # has vulnerability → 0.0 (unsafe, below 2.5 threshold).
            label = str(raw.get("code_vulnerability_label", "")).lower()
            raw["score"] = 0.0 if label in ("true", "1", "yes") else 5.0
        return raw
