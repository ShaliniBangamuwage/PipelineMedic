from app.core.config import Settings


def test_frontend_origins_include_configured_and_local_dev_ports():
    settings = Settings(frontend_url="http://localhost:4173")

    assert settings.frontend_origins == [
        "http://localhost:4173",
        "http://localhost:5173",
        "http://localhost",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1",
    ]


def test_frontend_origins_support_comma_separated_values():
    settings = Settings(frontend_url="http://localhost:5173, http://localhost:4173")

    assert "http://localhost:5173" in settings.frontend_origins
    assert "http://localhost:4173" in settings.frontend_origins


def test_frontend_origin_regex_is_configurable_for_preview_deployments():
    settings = Settings(
        frontend_url="https://pipeline-medic.example.com",
        frontend_origin_regex=r"https://pipeline-medic-[a-z0-9-]+\.vercel\.app",
    )

    assert settings.frontend_origin_regex == r"https://pipeline-medic-[a-z0-9-]+\.vercel\.app"
