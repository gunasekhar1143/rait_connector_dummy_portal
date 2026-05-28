from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


class IngestPayload(BaseModel):
    model_name: str
    model_version: str
    model_environment: str
    model_purpose: str
    log_generated_at: str
    model_data_logs: str
    connector_logs: str = ""
    log_type: Literal["evaluation", "telemetry", "calibration"]


class IngestResponse(BaseModel):
    status: str
    record_id: int


class RecordSummary(BaseModel):
    record_id: int
    model_name: str
    model_version: str
    model_environment: str
    log_type: str
    log_generated_at: str
    received_at: str


class RecordDetail(RecordSummary):
    decrypted_payload: Optional[Dict[str, Any]] = None
    connector_logs: Optional[str] = None


class RecordList(BaseModel):
    items: List[RecordSummary]
    total: int


class DimensionScore(BaseModel):
    dimension_id: str
    dimension_name: str
    aggregation_strategy: str
    avg_score: float
    min_score: float
    max_score: float
    is_safe: bool
    sample_count: int


class DimensionSummary(BaseModel):
    dimensions: List[DimensionScore]
    evaluated_at: str
    total_records: int


class TelemetryRecord(BaseModel):
    record_id: int
    model_name: str
    received_at: str
    raw_telemetry: Optional[Dict[str, Any]] = None


class SchedulerJob(BaseModel):
    id: str
    trigger: str
    next_run: Optional[str] = None
    is_executing: bool = False
