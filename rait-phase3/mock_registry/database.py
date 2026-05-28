"""Registry DB init and seeding."""
import aiosqlite

from .seed_data import SEED_DIMENSION_METRICS, SEED_DIMENSIONS, SEED_METRICS

_CREATE_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Ethical dimensions with aggregation config
CREATE TABLE IF NOT EXISTS dimensions (
    dimension_id        TEXT PRIMARY KEY,
    dimension_name      TEXT NOT NULL UNIQUE,
    aggregation_strategy TEXT NOT NULL,
    safety_threshold    REAL NOT NULL DEFAULT 0.5,
    display_order       INTEGER NOT NULL DEFAULT 0
);

-- Individual metrics (metric_name must match rait_connector Metric enum strings)
CREATE TABLE IF NOT EXISTS metrics (
    metric_id   TEXT PRIMARY KEY,
    metric_name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- Many-to-many: dimension ↔ metric with weight and risk tier
CREATE TABLE IF NOT EXISTS dimension_metrics (
    dimension_id TEXT NOT NULL REFERENCES dimensions(dimension_id),
    metric_id    TEXT NOT NULL REFERENCES metrics(metric_id),
    weight       REAL NOT NULL DEFAULT 1.0,
    risk_tier    TEXT NOT NULL DEFAULT 'standard',
    PRIMARY KEY (dimension_id, metric_id)
);

CREATE INDEX IF NOT EXISTS idx_dm_dimension ON dimension_metrics(dimension_id);
CREATE INDEX IF NOT EXISTS idx_dm_metric    ON dimension_metrics(metric_id);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_SQL)
        await _seed(db)
        await db.commit()


async def _seed(db: aiosqlite.Connection) -> None:
    await db.executemany(
        "INSERT OR IGNORE INTO dimensions VALUES (?,?,?,?,?)", SEED_DIMENSIONS
    )
    await db.executemany(
        "INSERT OR IGNORE INTO metrics VALUES (?,?,?)", SEED_METRICS
    )
    await db.executemany(
        "INSERT OR IGNORE INTO dimension_metrics VALUES (?,?,?,?)", SEED_DIMENSION_METRICS
    )
