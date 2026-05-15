from __future__ import annotations

from app.config.database import resolve_runtime_database_url


def test_runtime_database_url_differs_between_dev_and_prod_without_explicit_override() -> None:
    dev = resolve_runtime_database_url({"PKM_ENVIRONMENT": "dev"})
    prod = resolve_runtime_database_url({"PKM_ENVIRONMENT": "prod"})

    assert dev.endswith("/app_dev")
    assert prod.endswith("/app")
    assert dev != prod


def test_runtime_database_url_test_environment_uses_app_test() -> None:
    """PKM_ENVIRONMENT=test must use the isolated app_test database name."""
    url = resolve_runtime_database_url({"PKM_ENVIRONMENT": "test"})
    assert url.endswith("/app_test")

    overridden = resolve_runtime_database_url(
        {"PKM_ENVIRONMENT": "test", "PKM_DB_NAME_TEST": "custom_test_db"}
    )
    assert overridden.endswith("/custom_test_db")


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
