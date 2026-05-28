"""Tests for AggregationService: all three strategies, boundary conditions, score extraction."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"))

from dummy_portal.services.aggregation_service import AggregationService, _extract_score


# ── Score extraction ──────────────────────────────────────────────────────────

class TestExtractScore:
    def test_score_key(self):
        assert _extract_score({"score": 4.2}) == pytest.approx(4.2)

    def test_azure_evaluator_key(self):
        assert _extract_score({"coherence": 3.8, "coherence_reason": "good"}) == pytest.approx(3.8)

    def test_score_takes_priority_over_other_numeric(self):
        assert _extract_score({"other": 1.0, "score": 4.5}) == pytest.approx(4.5)

    def test_empty_dict_returns_none(self):
        assert _extract_score({}) is None

    def test_none_returns_none(self):
        assert _extract_score(None) is None

    def test_string_values_skipped(self):
        assert _extract_score({"reason": "text", "score": 3.0}) == pytest.approx(3.0)

    def test_integer_score_cast_to_float(self):
        assert isinstance(_extract_score({"score": 4}), float)


# ── AggregationService strategies ────────────────────────────────────────────

def _make_eval_row(dimension_id: str, metric_name: str, score: float) -> dict:
    dims = [
        {
            "dimension_id": dimension_id,
            "dimension_name": "Test Dimension",
            "dimension_metrics": [
                {
                    "metric_id": "met-001",
                    "metric_name": metric_name,
                    "metric_metadata": {"score": score},
                }
            ],
        }
    ]
    return {"ethical_dimensions": json.dumps(dims)}


@pytest.fixture
def db_with_strategies(tmp_path):
    """Synchronous SQLite fixture with seeded dimension strategies."""
    db_path = str(tmp_path / "test.db")
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE dimension_strategies (
            dimension_id TEXT PRIMARY KEY,
            dimension_name TEXT NOT NULL,
            aggregation_strategy TEXT NOT NULL,
            safety_threshold REAL NOT NULL DEFAULT 0.5
        );
        CREATE TABLE metric_weights (
            dimension_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            risk_tier TEXT NOT NULL DEFAULT 'standard',
            PRIMARY KEY (dimension_id, metric_name)
        );
        INSERT INTO dimension_strategies VALUES ('dim-min',  'Security',      'min_gate',           0.5);
        INSERT INTO dimension_strategies VALUES ('dim-avg',  'Explainability','average',             0.5);
        INSERT INTO dimension_strategies VALUES ('dim-wsc',  'Bias',          'weighted_scorecard',  0.5);
        INSERT INTO metric_weights VALUES ('dim-wsc', 'Metric-A', 0.7, 'high_risk');
        INSERT INTO metric_weights VALUES ('dim-wsc', 'Metric-B', 0.3, 'stylistic');
    """)
    con.commit()
    con.close()
    return db_path


@pytest.mark.asyncio
class TestMinGate:
    async def test_min_gate_passes_when_all_above_threshold(self, db_with_strategies):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_eval_row("dim-min", "Metric-X", s) for s in [0.6, 0.8, 0.9]]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-min")
        assert dim.is_safe is True
        assert dim.avg_score == pytest.approx(0.6)  # min gate score = min = 0.6

    async def test_min_gate_fails_when_any_below_threshold(self, db_with_strategies):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_eval_row("dim-min", "Metric-X", s) for s in [0.3, 0.8]]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-min")
        assert dim.is_safe is False
        assert dim.avg_score == pytest.approx(0.3)  # min = 0.3

    @pytest.mark.parametrize("score,expected_safe", [
        (0.499, False),
        (0.500, True),
        (0.501, True),
    ])
    async def test_min_gate_boundary(self, db_with_strategies, score, expected_safe):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_eval_row("dim-min", "Metric-X", score)]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-min")
        assert dim.is_safe is expected_safe


@pytest.mark.asyncio
class TestAverage:
    async def test_average_of_known_values(self, db_with_strategies):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_eval_row("dim-avg", "Metric-X", s) for s in [0.4, 0.6]]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-avg")
        assert dim.avg_score == pytest.approx(0.5)
        assert dim.is_safe is True  # 0.5 >= 0.5

    @pytest.mark.parametrize("score,expected_safe", [
        (0.499, False),
        (0.500, True),
    ])
    async def test_average_boundary(self, db_with_strategies, score, expected_safe):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_eval_row("dim-avg", "Metric-X", score)]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-avg")
        assert dim.is_safe is expected_safe


@pytest.mark.asyncio
class TestWeightedScorecard:
    async def test_weighted_scorecard_known_result(self, db_with_strategies):
        """Metric-A weight=0.7, Metric-B weight=0.3. Scores 1.0 and 0.0 → 0.7*1.0 + 0.3*0.0 / (0.7+0.3) = 0.7."""
        import aiosqlite

        def _make_two_metric_row(score_a: float, score_b: float) -> dict:
            dims = [{
                "dimension_id": "dim-wsc",
                "dimension_name": "Bias",
                "dimension_metrics": [
                    {"metric_id": "m1", "metric_name": "Metric-A", "metric_metadata": {"score": score_a}},
                    {"metric_id": "m2", "metric_name": "Metric-B", "metric_metadata": {"score": score_b}},
                ],
            }]
            return {"ethical_dimensions": json.dumps(dims)}

        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            rows = [_make_two_metric_row(1.0, 0.0)]
            results = await svc.compute_summary(rows)
        dim = next(d for d in results if d.dimension_id == "dim-wsc")
        assert dim.avg_score == pytest.approx(0.7, abs=0.001)
        assert dim.is_safe is True


@pytest.mark.asyncio
class TestNoData:
    async def test_dimension_with_no_records_returns_safe_false(self, db_with_strategies):
        import aiosqlite
        async with aiosqlite.connect(db_with_strategies) as db:
            db.row_factory = aiosqlite.Row
            svc = AggregationService(db)
            results = await svc.compute_summary([])  # no evaluation rows
        for dim in results:
            assert dim.sample_count == 0
            assert dim.is_safe is False
            assert dim.avg_score == 0.0
