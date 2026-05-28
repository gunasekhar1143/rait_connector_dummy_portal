"""DB-driven dimension score aggregation.

Strategies and weights are read from the dimension_strategies and metric_weights
tables — no hardcoded dimension names or score thresholds anywhere in this module.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from ..models.schemas import DimensionScore

logger = logging.getLogger(__name__)


def _extract_score(metric_metadata: dict[str, Any]) -> float | None:
    """Extract a single float score from metric_metadata.

    Azure AI evaluators return dicts like {"coherence": 4.2, "coherence_reason": "..."}.
    Stub evaluator returns {"score": 4.2}.
    We try "score" first, then take the first numeric value found.
    """
    if not metric_metadata:
        return None
    if "score" in metric_metadata:
        v = metric_metadata["score"]
        if isinstance(v, (int, float)):
            return float(v)
    for v in metric_metadata.values():
        if isinstance(v, (int, float)):
            return float(v)
    return None


class AggregationService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def _load_strategies(self) -> dict[str, dict]:
        """Returns {dimension_id: {strategy, threshold, weights: {metric_name: weight}}}."""
        rows = await self._db.execute_fetchall(
            "SELECT dimension_id, dimension_name, aggregation_strategy, safety_threshold "
            "FROM dimension_strategies ORDER BY rowid"
        )
        strategies: dict[str, dict] = {}
        for row in rows:
            strategies[row["dimension_id"]] = {
                "dimension_name": row["dimension_name"],
                "strategy": row["aggregation_strategy"],
                "threshold": row["safety_threshold"],
                "weights": {},
            }
        weight_rows = await self._db.execute_fetchall(
            "SELECT dimension_id, metric_name, weight FROM metric_weights"
        )
        for row in weight_rows:
            did = row["dimension_id"]
            if did in strategies:
                strategies[did]["weights"][row["metric_name"]] = row["weight"]
        return strategies

    def _apply_strategy(
        self,
        strategy: str,
        threshold: float,
        weights: dict[str, float],
        metric_scores: dict[str, list[float]],
    ) -> tuple[float, float, float, bool]:
        """Returns (avg_score, min_score, max_score, is_safe)."""
        all_scores: list[float] = []
        for scores in metric_scores.values():
            all_scores.extend(scores)

        if not all_scores:
            return 0.0, 0.0, 0.0, False

        if strategy == "min_gate":
            score = min(all_scores)
        elif strategy == "weighted_scorecard":
            total_w = 0.0
            weighted_sum = 0.0
            for metric_name, scores in metric_scores.items():
                w = weights.get(metric_name, 1.0)
                avg = sum(scores) / len(scores)
                weighted_sum += avg * w
                total_w += w
            score = weighted_sum / total_w if total_w else 0.0
        else:  # average
            score = sum(all_scores) / len(all_scores)

        min_score = min(all_scores)
        max_score = max(all_scores)
        return score, min_score, max_score, score >= threshold

    async def compute_summary(
        self,
        evaluation_rows: list[dict],
    ) -> list[DimensionScore]:
        """Compute DimensionScore for every dimension in dimension_strategies.

        Dimensions with no evaluation data return sample_count=0 and is_safe=False.
        """
        strategies = await self._load_strategies()

        # Accumulate per-dimension per-metric scores from all evaluation rows
        # Structure: {dimension_id: {metric_name: [score, score, ...]}}
        dim_metric_scores: dict[str, dict[str, list[float]]] = {
            did: {} for did in strategies
        }

        for row in evaluation_rows:
            try:
                dims = json.loads(row["ethical_dimensions"] or "[]")
            except (json.JSONDecodeError, TypeError):
                continue

            for dim in dims:
                did = dim.get("dimension_id")
                if did not in dim_metric_scores:
                    continue
                for metric in dim.get("dimension_metrics", []):
                    mname = metric.get("metric_name", "")
                    score = _extract_score(metric.get("metric_metadata") or {})
                    if score is not None:
                        dim_metric_scores[did].setdefault(mname, []).append(score)

        results: list[DimensionScore] = []
        for did, cfg in strategies.items():
            metric_scores = dim_metric_scores.get(did, {})
            sample_count = len(next(iter(metric_scores.values()), []))

            if not metric_scores:
                results.append(DimensionScore(
                    dimension_id=did,
                    dimension_name=cfg["dimension_name"],
                    aggregation_strategy=cfg["strategy"],
                    avg_score=0.0,
                    min_score=0.0,
                    max_score=0.0,
                    is_safe=False,
                    sample_count=0,
                ))
                continue

            avg, mn, mx, is_safe = self._apply_strategy(
                cfg["strategy"], cfg["threshold"], cfg["weights"], metric_scores
            )
            # sample_count = number of evaluation records that contributed scores
            total_samples = max(len(v) for v in metric_scores.values())
            results.append(DimensionScore(
                dimension_id=did,
                dimension_name=cfg["dimension_name"],
                aggregation_strategy=cfg["strategy"],
                avg_score=round(avg, 4),
                min_score=round(mn, 4),
                max_score=round(mx, 4),
                is_safe=is_safe,
                sample_count=total_samples,
            ))

        return results
