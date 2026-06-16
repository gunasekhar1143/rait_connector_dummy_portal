"""Pydantic V2 isolated settings — no os.environ side effects.

The legacy rait_connector/config.py runs a @model_validator that writes Azure
credentials into os.environ on every instantiation, polluting the process
environment. This module keeps settings local to each Settings() instance.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Registry / ingest URLs
    rait_api_url: str = "http://localhost:8001"
    rait_ingest_url: str = "http://localhost:8000"

    # Client credentials
    rait_client_id: str = "demo-client"
    rait_client_secret: str = "demo-secret"

    # Model identity (used when building ingest payloads)
    model_name: str = "gpt-4o-poc"
    model_version: str = "2024-08-06"
    model_environment: str = "development"
    model_purpose: str = "poc-demo"

    # Service tuning
    telemetry_sync_interval: float = 86400.0  # 1 day
    calibration_timeout: float = 30.0
    calibration_interval: float = 86400.0  # 1 day

    # ── Azure OpenAI (LLM response generation + quality evaluators e.g. Coherence) ──
    # Leave all empty → stubs are used instead.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-12-01-preview"

    # ── Azure AI Project (safety evaluators: HateUnfairness, CodeVulnerability) ──
    # Can be a full endpoint URL OR subscription/resource-group/project triple.
    azure_ai_project_url: str = ""       # e.g. https://{name}.services.ai.azure.com/api/projects/{proj}
    azure_subscription_id: str = ""
    azure_resource_group: str = ""
    azure_project_name: str = ""

    # ── Azure AD service-principal (optional — omit when using API-key auth) ──
    azure_client_id: str = ""
    azure_tenant_id: str = ""
    azure_client_secret: str = ""

    # ── Azure Log Analytics (telemetry fetch) ──
    azure_log_analytics_workspace_id: str = ""

    # ── Derived availability flags ─────────────────────────────────────────────

    @property
    def has_azure_openai(self) -> bool:
        """True when Azure OpenAI endpoint + API key are both set."""
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def has_azure_ai_project(self) -> bool:
        """True when enough Azure AI Project credentials are present."""
        return bool(
            self.azure_ai_project_url
            or (self.azure_subscription_id and self.azure_resource_group and self.azure_project_name)
        )

    @property
    def has_azure(self) -> bool:
        """True when any Azure integration is available."""
        return self.has_azure_openai or self.has_azure_ai_project

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
