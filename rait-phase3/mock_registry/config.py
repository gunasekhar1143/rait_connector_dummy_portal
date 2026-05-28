from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrySettings(BaseSettings):
    rsa_key_dir: str = "keys"
    db_path: str = "mock_registry/registry.db"
    port: int = 8001
    token_ttl_seconds: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_prefix="REGISTRY_", extra="ignore")


settings = RegistrySettings()
