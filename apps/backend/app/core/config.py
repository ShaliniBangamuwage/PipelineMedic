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
    github_log_max_bytes: int = 10_000_000
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    auth_enabled: bool = False
    expose_invitation_urls: bool = False
    redis_url: str = ""
    redis_queue_name: str = "pipelinemedic:jobs"
    worker_max_attempts: int = 3
    worker_backoff_seconds: float = 1.0
    patch_generation_enabled: bool = False
    patch_max_files: int = 10
    patch_max_changed_lines: int = 200
    patch_max_bytes: int = 100_000
    patch_allowed_extensions: str = ".py,.ts,.tsx,.js,.jsx,.java,.go,.cs,.md"
    patch_context_max_bytes: int = 200_000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
