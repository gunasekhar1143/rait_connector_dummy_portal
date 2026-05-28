from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int = 3600
    token_type: str = "Bearer"


class PublicKeyData(BaseModel):
    public_key: str


class PublicKeyResponse(BaseModel):
    data: PublicKeyData


class MetricItem(BaseModel):
    metric_id: str
    metric_name: str


class DimensionItem(BaseModel):
    dimension_id: str
    dimension_name: str
    dimension_metrics: List[MetricItem]


class CalibrationPrompt(BaseModel):
    prompt_id: str
    prompt_text: str


class CalibrationRunPrompt(BaseModel):
    prompt_id: str
    prompt_text: str


class CalibrationRunResponse(BaseModel):
    calibration_run_id: str
    prompts: List[CalibrationRunPrompt]


class PromptResponseItem(BaseModel):
    prompt_response_id: str
    prompt_text: str
    model_response: str = ""


class UpdateResponseItem(BaseModel):
    prompt_response_id: str
    prompt_text: str
    model_response: str
    external_prompt_id: Optional[str] = None
    response_generated_at: Optional[str] = None


class UpdateResponsesRequest(BaseModel):
    model_code: str = ""
    responses: List[UpdateResponseItem]


class StatusResponse(BaseModel):
    status_code: int = 200
    response: str = "ok"
