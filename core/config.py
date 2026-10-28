from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://ledger:ledger@localhost:5434/ledger"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    environment: str = "development"

    # Shared secret between the Next.js server and this API.
    # Empty means "no authenticated users accepted" (fail closed).
    internal_secret: str = ""

    upload_rate_limit_per_minute: int = 10
    read_rate_limit_per_minute: int = 60
    metric_write_rate_limit_per_minute: int = 30


settings = Settings()