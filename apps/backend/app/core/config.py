from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "PipelineMedic"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./pipelinemedic.db"
    frontend_url: str = "http://localhost:5173"
    github_webhook_secret: str = ""
    github_token: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ai_enabled: bool = False
    max_log_size_bytes: int = 5_000_000
    max_ai_log_characters: int = 30_000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
