from app.services import outbox as outbox_service
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


def test_resolve_dsn_uses_db_dsn_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_DSN", "postgresql+psycopg://app:app@db:5432/app")

    assert resolve_dsn() == "postgresql://app:app@db:5432/app"


def test_resolve_sqlalchemy_url_uses_db_dsn_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_DSN", "postgresql://app:app@db:5432/app")

    assert resolve_sqlalchemy_url() == "postgresql+psycopg://app:app@db:5432/app"


def test_outbox_open_conn_uses_db_dsn_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyConn:
        pass

    def fake_connect(url: str, autocommit: bool = True):
        captured["url"] = url
        captured["autocommit"] = autocommit
        return DummyConn()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_DSN", "postgresql+psycopg://app:app@db:5432/app")
    monkeypatch.setattr(outbox_service, "conn_rw", None)
    monkeypatch.setattr("psycopg.connect", fake_connect)

    conn = outbox_service._open_conn()

    assert isinstance(conn, DummyConn)
    assert captured == {
        "url": "postgresql://app:app@db:5432/app",
        "autocommit": True,
    }
