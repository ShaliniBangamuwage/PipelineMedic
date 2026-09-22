from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PipelineMedic"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./pipelinemedic.db"
    frontend_url: str = "http://localhost:5173"
    resend_api_key: str = ""
    resend_from_email: str = ""
    github_webhook_secret: str = ""
    github_token: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_callback_url: str = "http://localhost:8000/api/auth/github/callback"
    github_oauth_state_ttl_seconds: int = 600
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_slug: str = ""
    github_app_install_url: str = ""
    github_app_webhook_secret: str = ""
    github_app_state_ttl_seconds: int = 600
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ai_enabled: bool = False
    ai_timeout_seconds: int = 15
    ai_max_log_chars: int = 30_000

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"
    max_log_size_bytes: int = 5_000_000
    max_ai_log_characters: int = 30_000
    github_log_max_bytes: int = 10_000_000
    jwt_secret: str = "development-only-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    auth_enabled: bool = False
    expose_invitation_urls: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    api_key_rate_limit_per_minute: int = 60
    api_key_rate_limit_window_seconds: int = 60
    api_key_default_expiry_days: int = 30
    redis_url: str = ""
    redis_queue_name: str = "pipelinemedic:jobs"
    worker_max_attempts: int = 3
    worker_backoff_seconds: float = 1.0
    worker_max_backoff_seconds: float = 300.0
    patch_generation_enabled: bool = False
    patch_max_files: int = 10
    patch_max_changed_lines: int = 200
    patch_max_bytes: int = 100_000
    patch_allowed_extensions: str = ".py,.ts,.tsx,.js,.jsx,.java,.go,.cs,.md"
    patch_context_max_bytes: int = 200_000
    model_config = SettingsConfigDict(
        env_file=(".env", "apps/backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def model_post_init(self, __context):
        if self.is_production and not self.auth_enabled:
            raise ValueError("AUTH_ENABLED must be true in production")
        if self.is_production and (len(self.jwt_secret) < 32 or self.jwt_secret == "development-only-change-me"):
            raise ValueError("JWT_SECRET must be at least 32 characters in production")

    @property
    def frontend_origin(self) -> str:
        for raw in (self.frontend_url or "").split(","):
            value = raw.strip().rstrip("/")
            if value:
                return value
        return ""

    @property
    def frontend_origins(self):
        configured = []
        for raw in (self.frontend_url or "").split(","):
            value = raw.strip()
            if value:
                configured.append(value)

        dev_aliases = [
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost",
            "http://127.0.0.1:4173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1",
        ]

        seen = []
        for origin in configured + dev_aliases:
            if origin not in seen:
                seen.append(origin)
        return seen


settings = Settings()
