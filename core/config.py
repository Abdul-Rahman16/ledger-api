from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://ledger:ledger@localhost:5434/ledger"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    environment: str = "development"


settings = Settings()