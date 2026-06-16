"""Smoke-test for the production MetricClassifier."""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

from dummy_portal.ml.classifier import (
    MetricClassifier, _sigmoid,
    METRIC_BIAS, METRIC_COHERENCE, METRIC_VULN,
)

print("=== sigmoid sanity ===")
print(f"sigmoid(0)  = {_sigmoid(0):.4f}  (expect 0.5000)")
print(f"sigmoid(2)  = {_sigmoid(2):.4f}  (expect 0.8808)")
print(f"sigmoid(-2) = {_sigmoid(-2):.4f} (expect 0.1192)")
print()

print("=== Training (metrics logged below) ===")
clf = MetricClassifier()
print()

print("=== Inference ===")
cases = [
    (4.5, METRIC_BIAS,      "PASS"),
    (0.5, METRIC_BIAS,      "FAIL"),
    (4.0, METRIC_COHERENCE, "PASS"),
    (1.5, METRIC_COHERENCE, "PASS"),   # weak predictor: low portal score still PASS at F1-optimal threshold
    (3.0, METRIC_VULN,      "N/A"),
    (None, METRIC_BIAS,     "N/A"),
]
all_ok = True
for score, metric, expected in cases:
    result = clf.predict(score, metric)
    ok = result["label"] == expected
    all_ok = all_ok and ok
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] predict({score}, {metric!r:35s}) -> {result}")

print()
print("All tests passed." if all_ok else "SOME TESTS FAILED.")
