from pydantic_settings import BaseSettings, SettingsConfigDict


class PortalSettings(BaseSettings):
    rsa_private_key_path: str = "keys/rsa_private.pem"
    sqlite_db_path: str = "dummy_portal/portal.db"
    port: int = 8000
    otel_exporter: str = "console"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PORTAL_", extra="ignore")


settings = PortalSettings()
