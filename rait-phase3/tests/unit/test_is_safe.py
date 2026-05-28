"""Tests for is_safe boolean boundary on all three aggregation strategies."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dummy_portal.services.aggregation_service import AggregationService


@pytest.mark.parametrize("strategy,scores,threshold,expected_safe", [
    # min_gate
    ("min_gate",           [0.499],        0.5, False),
    ("min_gate",           [0.500],        0.5, True),
    ("min_gate",           [0.3, 0.9],     0.5, False),  # min=0.3
    ("min_gate",           [0.6, 0.9],     0.5, True),   # min=0.6
    # average
    ("average",            [0.499],        0.5, False),
    ("average",            [0.500],        0.5, True),
    ("average",            [0.4, 0.6],     0.5, True),   # avg=0.5
    ("average",            [0.3, 0.6],     0.5, False),  # avg=0.45
    # weighted_scorecard (no specific weights = uniform)
    ("weighted_scorecard", [0.499],        0.5, False),
    ("weighted_scorecard", [0.500],        0.5, True),
])
def test_is_safe_boundary(strategy, scores, threshold, expected_safe):
    metric_scores = {"Metric-X": scores}
    weights = {}
    _, _, _, is_safe = AggregationService(None)._apply_strategy(
        strategy, threshold, weights, metric_scores
    )
    assert is_safe is expected_safe
