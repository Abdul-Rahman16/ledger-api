from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://ledger:ledger@localhost:5434/ledger"
    environment: str = "development"

    # Language models: Groq is primary, Gemini is the fallback.
    # Model ids change often. Check them with: python -m scripts.list_models
    groq_api_key: str = ""
    gemini_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 20.0
    llm_max_output_tokens: int = 2048  # reasoning models spend part of this on thinking

    # Shared secret between the Next.js server and this API (also guards /internal/*).
    # Empty means "no authenticated users accepted" (fail closed).
    internal_secret: str = ""

    # Object storage for raw uploads (any S3-compatible store). Leave STORAGE_BUCKET empty to disable.
    storage_bucket: str = ""
    storage_endpoint_url: str = ""  # R2: https://<account id>.r2.cloudflarestorage.com ; empty for AWS S3
    storage_region: str = ""  # R2: auto ; AWS: for example ap-south-1
    storage_access_key_id: str = ""
    storage_secret_access_key: str = ""

    # Guest datasets are deleted after this many hours by the maintenance job.
    guest_retention_hours: int = 24

    upload_rate_limit_per_minute: int = 10
    read_rate_limit_per_minute: int = 60
    metric_write_rate_limit_per_minute: int = 30
    query_rate_limit_per_minute: int = 20
    ask_rate_limit_per_minute: int = 10  # each call can use an LLM request


        # Pipeline freshness (used by the scheduled maintenance jobs)
    profile_stale_after_hours: int = 24
    metric_refresh_after_hours: int = 24


settings = Settings()