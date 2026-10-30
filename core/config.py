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

    # Shared secret between the Next.js server and this API.
    # Empty means "no authenticated users accepted" (fail closed).
    internal_secret: str = ""

    upload_rate_limit_per_minute: int = 10
    read_rate_limit_per_minute: int = 60
    metric_write_rate_limit_per_minute: int = 30
    query_rate_limit_per_minute: int = 20
    ask_rate_limit_per_minute: int = 10  # each call can use an LLM request


settings = Settings()