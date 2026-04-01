from app.db.dsn import resolve_dsn, resolve_sqlalchemy_url


def test_resolve_dsn_strips_psycopg_driver() -> None:
    assert (
        resolve_dsn("postgresql+psycopg://app:app@db:5432/app")
        == "postgresql://app:app@db:5432/app"
    )


def test_resolve_sqlalchemy_url_adds_psycopg_driver() -> None:
    assert (
        resolve_sqlalchemy_url("postgresql://app:app@db:5432/app")
        == "postgresql+psycopg://app:app@db:5432/app"
    )


def test_resolve_sqlalchemy_url_preserves_psycopg_driver() -> None:
    assert (
        resolve_sqlalchemy_url("postgresql+psycopg://app:app@db:5432/app")
        == "postgresql+psycopg://app:app@db:5432/app"
    )
