"""Portal DB init, table creation, and dimension strategy seeding."""
from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite

# ── Seed data (must mirror mock_registry/seed_data.py) ───────────────────────

PORTAL_STRATEGY_SEED = [
    # (dimension_id, dimension_name, aggregation_strategy, safety_threshold)
    ("dim-bias-001", "Bias & Fairness",                  "weighted_scorecard", 0.5),
    ("dim-expl-001", "Explainability & Transparency",    "average",            0.5),
    ("dim-sec-001",  "Security & Adversarial Robustness","min_gate",           0.5),
]

PORTAL_WEIGHT_SEED = [
    # (dimension_id, metric_name, weight, risk_tier)
    ("dim-bias-001", "Hate and Unfairness (Azure)", 0.7, "high_risk"),
    ("dim-expl-001", "Coherence (Azure)",            1.0, "standard"),
    ("dim-sec-001",  "Code Vulnerability (Azure)",   1.0, "standard"),
]

# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Dimension aggregation strategies (DB-driven; no hardcoded logic in service layer)
CREATE TABLE IF NOT EXISTS dimension_strategies (
    dimension_id         TEXT PRIMARY KEY,
    dimension_name       TEXT NOT NULL,
    aggregation_strategy TEXT NOT NULL,
    safety_threshold     REAL NOT NULL DEFAULT 0.5
);

-- Per-metric weights used by weighted_scorecard strategy
CREATE TABLE IF NOT EXISTS metric_weights (
    dimension_id TEXT NOT NULL REFERENCES dimension_strategies(dimension_id),
    metric_name  TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    risk_tier    TEXT NOT NULL DEFAULT 'standard',
    PRIMARY KEY (dimension_id, metric_name)
);

-- One row per encrypted ingest payload received at PUT /v1/{key}
CREATE TABLE IF NOT EXISTS ingest_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_key           TEXT NOT NULL,
    model_name        TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    model_environment TEXT NOT NULL,
    model_purpose     TEXT NOT NULL,
    log_type          TEXT NOT NULL,
    log_generated_at  TEXT NOT NULL,
    received_at       TEXT NOT NULL,
    decrypted_payload TEXT,
    connector_logs    TEXT
);

-- Evaluation results parsed from evaluation ingest records
CREATE TABLE IF NOT EXISTS evaluation_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id          INTEGER NOT NULL REFERENCES ingest_records(id),
    prompt_id          TEXT NOT NULL,
    prompt_url         TEXT,
    eval_timestamp     TEXT,
    query              TEXT,
    response           TEXT,
    ground_truth       TEXT,
    context            TEXT,
    ethical_dimensions TEXT,
    post_response      TEXT
);

-- Raw telemetry blobs from telemetry ingest records
CREATE TABLE IF NOT EXISTS telemetry_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER NOT NULL REFERENCES ingest_records(id),
    raw_telemetry TEXT
);

-- Calibration responses from calibration ingest records
CREATE TABLE IF NOT EXISTS calibration_records (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id          INTEGER NOT NULL REFERENCES ingest_records(id),
    calibration_run_id TEXT,
    responses          TEXT
);

CREATE INDEX IF NOT EXISTS idx_er_record   ON evaluation_results(record_id);
CREATE INDEX IF NOT EXISTS idx_tr_record   ON telemetry_records(record_id);
CREATE INDEX IF NOT EXISTS idx_cr_record   ON calibration_records(record_id);
CREATE INDEX IF NOT EXISTS idx_ir_log_type ON ingest_records(log_type);
CREATE INDEX IF NOT EXISTS idx_ir_model    ON ingest_records(model_name);
"""


async def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_SQL)
        await db.executemany(
            "INSERT OR IGNORE INTO dimension_strategies VALUES (?,?,?,?)",
            PORTAL_STRATEGY_SEED,
        )
        await db.executemany(
            "INSERT OR IGNORE INTO metric_weights VALUES (?,?,?,?)",
            PORTAL_WEIGHT_SEED,
        )
        await db.commit()


async def get_db(db_path: str) -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
