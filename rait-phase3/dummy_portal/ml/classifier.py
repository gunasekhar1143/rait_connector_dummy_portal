"""LR PASS/FAIL classifiers — one model per metric, trained from CSV datasets.

Training pipeline (per metric):
  1. Load CSV  →  apply threshold  →  binary labels  (y=1 means FAIL)
  2. 5-fold stratified CV with cross_val_predict  →  out-of-fold probabilities
  3. precision_recall_curve  →  F1-optimal probability threshold
  4. Fit LogisticRegression on all data (raw Azure scores, no scaler)
  5. Log: P(FAIL) = sigmoid(a * score + b), baseline vs LR F1, confusion matrix

Feature scales (must match at training AND inference):
  Bias      — Azure Hate/Unfairness score 0-7 (from bias_metric_scores.csv)
  Coherence — Azure Coherence score      1-5 (from coherence_metric_scores.csv)

Inference:
  predict_proba  →  sigmoid probability  →  compare vs stored F1-optimal threshold
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict

logger = logging.getLogger(__name__)

_DATA_DIR    = Path(__file__).parent.parent.parent / "data"
_MIN_SAMPLES = 20
_CV_FOLDS    = 5

METRIC_BIAS      = "Hate and Unfairness (Azure)"
METRIC_COHERENCE = "Coherence (Azure)"
METRIC_VULN      = "Code Vulnerability (Azure)"


# ── Helper types ──────────────────────────────────────────────────────────────

@dataclass
class _MetricModel:
    """Fitted model bundle for one metric."""
    model:     LogisticRegression  # trained directly on raw scores, no scaler
    threshold: float               # F1-optimal probability threshold found via CV


# ── Step 1: Data loading (one function per metric) ────────────────────────────

def _load_bias_data() -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None]:
    """Merge human labels + portal scores, return (X, y, pred_baseline) or (None, None, None).

    X  = raw Azure Hate/Unfairness score (0-7 scale) from bias_metric_scores.csv
    y  = jigsaw_toxicity > 0.5 proxy label (bias_gold_label not populated in dataset)
    baseline = score >= 4  (midpoint of 0-7 Azure scale; mirrors reference project)
    """
    labels_path = _DATA_DIR / "bias" / "bias_sample.csv"
    scores_path = _DATA_DIR / "bias" / "bias_metric_scores.csv"

    for p in (labels_path, scores_path):
        if not p.exists():
            logger.warning("Bias file not found at %s — %s skipped", p, METRIC_BIAS)
            return None, None, None

    labels = pd.read_csv(labels_path, encoding="utf-8", encoding_errors="replace")[
        ["record_id", "jigsaw_toxicity"]
    ]
    scores = pd.read_csv(scores_path)
    scores = scores[scores["status"] == "ok"][["record_id", "score"]]
    df     = labels.merge(scores, on="record_id").dropna(subset=["jigsaw_toxicity", "score"])

    if len(df) < _MIN_SAMPLES:
        logger.warning("Bias merged dataset too small (%d rows) — %s skipped", len(df), METRIC_BIAS)
        return None, None, None

    score_vals    = df["score"].astype(float).values          # Azure 0-7 scale
    y             = (df["jigsaw_toxicity"].astype(float).values > 0.5).astype(int)  # y=1 → FAIL
    X             = score_vals.reshape(-1, 1)                  # raw Azure score, no scaler
    pred_baseline = (score_vals >= 4.0).astype(int)           # simple threshold baseline (ref: score >= 4)
    return X, y, pred_baseline


def _load_coherence_data() -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None]:
    """Merge human labels + portal scores, return (X, y, pred_baseline) or (None, None, None)."""
    labels_path = _DATA_DIR / "coherence" / "coherence_sample.csv"
    scores_path = _DATA_DIR / "coherence" / "coherence_metric_scores.csv"

    for p in (labels_path, scores_path):
        if not p.exists():
            logger.warning("Coherence file not found at %s — %s skipped", p, METRIC_COHERENCE)
            return None, None, None

    labels = pd.read_csv(labels_path)[["record_id", "coherence_gold"]]
    scores = pd.read_csv(scores_path)
    scores = scores[scores["status"] == "ok"][["record_id", "score"]]
    df     = labels.merge(scores, on="record_id").dropna(subset=["coherence_gold", "score"])

    if len(df) < _MIN_SAMPLES:
        logger.warning("Coherence merged dataset too small (%d rows) — %s skipped", len(df), METRIC_COHERENCE)
        return None, None, None

    score_vals    = df["score"].astype(float).values
    y             = (df["coherence_gold"].astype(float).values < 3.0).astype(int)  # y=1 → FAIL
    X             = score_vals.reshape(-1, 1)                                        # raw 1-5, no normalization
    pred_baseline = (score_vals < 3.0).astype(int)                                  # simple score < 3 baseline
    return X, y, pred_baseline


# ── Step 2: Sigmoid (explicit for transparency) ───────────────────────────────

def _sigmoid(z: float) -> float:
    """Logistic sigmoid: 1 / (1 + e^{-z}). Applied internally by predict_proba."""
    return 1.0 / (1.0 + math.exp(-z))


# ── Step 3: Find F1-optimal threshold from OOF probabilities ─────────────────

def _find_optimal_threshold(y_true: np.ndarray, oof_proba: np.ndarray) -> float:
    """Sweep all thresholds via precision_recall_curve; return the one with best F1."""
    prec, rec, thresholds = precision_recall_curve(y_true, oof_proba)
    f1s      = 2.0 * prec * rec / (prec + rec + 1e-12)
    best_idx = int(f1s[:-1].argmax())
    return float(thresholds[best_idx])


# ── Step 4: Evaluate OOF predictions and log all metrics ─────────────────────

def _evaluate_and_log(
    metric_name:       str,
    y:                 np.ndarray,
    oof_proba:         np.ndarray,
    pred_baseline:     np.ndarray,
    optimal_threshold: float,
    coef:              float,
    intercept:         float,
) -> None:
    """Compute TP/FP/TN/FN, Precision, Recall, F1, Accuracy, ROC-AUC and log them."""
    pred_optimal = (oof_proba >= optimal_threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y, pred_optimal).ravel()

    prec_val = precision_score(y, pred_optimal, zero_division=0)
    rec_val  = recall_score(y, pred_optimal, zero_division=0)
    f1_opt   = f1_score(y, pred_optimal, zero_division=0)
    f1_base  = f1_score(y, pred_baseline, zero_division=0)
    acc_val  = accuracy_score(y, pred_optimal)
    roc_auc  = roc_auc_score(y, oof_proba)

    logger.info(
        "\n"
        "+===================================================+\n"
        "  Metric : %s\n"
        "+===================================================+\n"
        "  Dataset   : %d samples  |  %d FAIL  |  %d PASS\n"
        "  Sigmoid   : P(FAIL) = sigmoid(%.4f * score + %.4f)\n"
        "              [sigmoid(z) = 1 / (1 + e^(-z))]\n"
        "  CV Folds  : %d-fold stratified\n"
        "  Threshold : %.3f  (F1-optimal via precision_recall_curve)\n"
        "----------------------------------------------------\n"
        "  Baseline F1 (score-threshold rule) : %.3f\n"
        "  LR F1       (OOF, thr=%.3f)      : %.3f\n"
        "  ROC-AUC                             : %.3f\n"
        "----------------------------------------------------\n"
        "  Confusion Matrix (OOF, thr=%.3f)\n"
        "              Pred FAIL   Pred PASS\n"
        "  True FAIL     TP=%4d      FN=%4d\n"
        "  True PASS     FP=%4d      TN=%4d\n"
        "----------------------------------------------------\n"
        "  Precision : %.3f\n"
        "  Recall    : %.3f\n"
        "  F1 Score  : %.3f\n"
        "  Accuracy  : %.3f\n"
        "+===================================================+",
        metric_name,
        len(y), int(y.sum()), len(y) - int(y.sum()),
        coef, intercept,
        _CV_FOLDS,
        optimal_threshold,
        f1_base,
        optimal_threshold, f1_opt,
        roc_auc,
        optimal_threshold,
        tp, fn,
        fp, tn,
        prec_val, rec_val, f1_opt, acc_val,
    )


# ── Step 5: Full training pipeline (CV eval → threshold → final fit) ──────────

def _fit(
    X:             np.ndarray,
    y:             np.ndarray,
    metric_name:   str,
    pred_baseline: np.ndarray,
) -> _MetricModel:
    """Run 5-fold CV for evaluation, find optimal threshold, fit final model."""
    cv = StratifiedKFold(n_splits=_CV_FOLDS, shuffle=True, random_state=42)

    oof_proba: np.ndarray = cross_val_predict(
        LogisticRegression(random_state=42, max_iter=1000),
        X, y, cv=cv, method="predict_proba",
    )[:, 1]

    optimal_threshold = _find_optimal_threshold(y, oof_proba)

    model = LogisticRegression(random_state=42, max_iter=1000)
    model.fit(X, y)

    coef      = float(model.coef_[0, 0])
    intercept = float(model.intercept_[0])

    _evaluate_and_log(metric_name, y, oof_proba, pred_baseline, optimal_threshold, coef, intercept)

    return _MetricModel(model=model, threshold=optimal_threshold)


# ── Classifier: orchestrates loading + fitting per metric ─────────────────────

class MetricClassifier:
    """Trains one LR classifier per metric at construction time."""

    def __init__(self) -> None:
        self._models: dict[str, _MetricModel] = {}
        self._train_bias()
        self._train_coherence()

    def _train_bias(self) -> None:
        X, y, pred_baseline = _load_bias_data()
        if X is not None:
            self._models[METRIC_BIAS] = _fit(X, y, METRIC_BIAS, pred_baseline)

    def _train_coherence(self) -> None:
        X, y, pred_baseline = _load_coherence_data()
        if X is not None:
            self._models[METRIC_COHERENCE] = _fit(X, y, METRIC_COHERENCE, pred_baseline)

    def predict(self, score: float | None, metric_name: str) -> dict:
        """Return {"label": "PASS"|"FAIL"|"N/A", "probability": float|None}."""
        entry = self._models.get(metric_name)
        if entry is None or score is None:
            return {"label": "N/A", "probability": None}

        # Both models trained on raw Azure scores (bias 0-7, coherence 1-5) — no normalization.
        x = np.array([[float(score)]])

        prob = float(entry.model.predict_proba(x)[0][1])  # P(FAIL)
        return {
            "label":       "FAIL" if prob >= entry.threshold else "PASS",
            "probability": round(prob, 3),
        }

    def enrich_ethical_dimensions(self, dims: list) -> list:
        """Add 'prediction' key to every metric dict in an ethical_dimensions list."""
        for dim in dims:
            for metric in dim.get("dimension_metrics", []):
                score = (metric.get("metric_metadata") or {}).get("score")
                metric["prediction"] = self.predict(score, metric.get("metric_name", ""))
        return dims
