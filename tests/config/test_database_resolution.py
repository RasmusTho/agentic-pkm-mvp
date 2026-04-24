from __future__ import annotations

from app.config.database import resolve_runtime_database_url


def test_runtime_database_url_differs_between_dev_and_prod_without_explicit_override() -> None:
    dev = resolve_runtime_database_url({"PKM_ENVIRONMENT": "dev"})
    prod = resolve_runtime_database_url({"PKM_ENVIRONMENT": "prod"})

    assert dev.endswith("/app_dev")
    assert prod.endswith("/app")
    assert dev != prod


def test_explicit_database_url_override_bypasses_environment_convention() -> None:
    explicit = "postgresql+psycopg://custom:pw@localhost:5432/custom_db"
    resolved = resolve_runtime_database_url(
        {
            "PKM_ENVIRONMENT": "dev",
            "DATABASE_URL": explicit,
            "PKM_DB_NAME_DEV": "ignored_db",
        }
    )
    assert resolved == explicit
