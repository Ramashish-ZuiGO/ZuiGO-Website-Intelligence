from app.config import Settings


def test_settings_build_database_url_from_postgres_fields() -> None:
    settings = Settings(
        _env_file=None,
        postgres_user="website user",
        postgres_password="p@ss word",
        postgres_db="website intelligence",
        postgres_host="database",
        postgres_port=5433,
    )

    assert (
        settings.database_url == "postgresql+psycopg://website%20user:p%40ss%20word"
        "@database:5433/website%20intelligence"
    )
    assert settings.cors_origins == ["http://localhost:3000"]
