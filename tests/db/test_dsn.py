import pytest

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


def _file_env(monkeypatch, tmp_path):
    for key in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / 'password'
    path.write_text('fake DB canary:@/word')
    monkeypatch.setenv('DATABASE_PASSWORD_FILE', str(path))
    monkeypatch.setenv('DATABASE_URL', 'postgresql://app@db:5432/app_test')
    return path


def test_runtime_database_config_uses_password_file(monkeypatch, tmp_path):
    import os
    from psycopg.conninfo import conninfo_to_dict
    from app.config.database import resolve_runtime_database_url
    from app.db.db import _psycopg_dsn

    path = _file_env(monkeypatch, tmp_path)
    before = dict(os.environ)
    runtime = resolve_runtime_database_url(os.environ)
    assert conninfo_to_dict(resolve_dsn(runtime))['password'] == path.read_text()
    assert conninfo_to_dict(_psycopg_dsn())['password'] == path.read_text()
    assert resolve_dsn(resolve_dsn(runtime)) == resolve_dsn(runtime)
    assert dict(os.environ) == before


def test_password_bearing_direct_dsn_is_rejected_without_value_disclosure(monkeypatch, tmp_path):
    import pytest
    from app.config.database import DatabaseCredentialError

    _file_env(monkeypatch, tmp_path)
    for value in ('postgresql://app:SECRET_CANARY@db/app_test', "host=db password='SECRET_CANARY'", 'postgresql://db/app_test?password=SECRET_CANARY'):
        with pytest.raises(DatabaseCredentialError) as failure:
            resolve_dsn(value)
        assert 'SECRET_CANARY' not in str(failure.value)
    monkeypatch.setenv('DB_DSN', 'postgresql://app:SECRET_CANARY@db/app_test')
    with pytest.raises(DatabaseCredentialError):
        resolve_dsn()


def test_credential_free_direct_dsn_uses_password_file(monkeypatch, tmp_path):
    from psycopg.conninfo import conninfo_to_dict

    path = _file_env(monkeypatch, tmp_path)
    fields = conninfo_to_dict(resolve_dsn('host=db port=5432 dbname=app_test user=app sslmode=require'))
    assert fields['password'] == path.read_text()
    assert fields['sslmode'] == 'require'
    assert fields['dbname'] == 'app_test'


def test_alembic_uses_file_aware_database_resolver(monkeypatch, tmp_path):
    from contextlib import nullcontext
    import runpy
    from alembic import context
    from sqlalchemy import create_engine

    path = _file_env(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(context, 'is_offline_mode', lambda: True)
    monkeypatch.setattr(context, 'configure', lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(context, 'begin_transaction', nullcontext)
    monkeypatch.setattr(context, 'run_migrations', lambda: None)
    runpy.run_path('app/alembic/env.py')
    engine = create_engine(captured['url'])
    args, kwargs = engine.dialect.create_connect_args(engine.url)
    assert not args
    assert kwargs['password'] == path.read_text()
    assert kwargs['host'] == 'db'
    assert kwargs['dbname'] == 'app_test'


def test_file_resolver_refuses_missing_malformed_or_ambient_credentials(monkeypatch, tmp_path):
    import pytest
    from app.config.database import DatabaseCredentialError

    path = _file_env(monkeypatch, tmp_path)
    for value in ('', 'line\nbreak', '\x00', '\n'):
        path.write_text(value)
        with pytest.raises(DatabaseCredentialError):
            resolve_dsn()
    path.unlink()
    with pytest.raises(DatabaseCredentialError):
        resolve_dsn()
    path.write_text('fakecanary')
    monkeypatch.setenv('POSTGRES_PASSWORD', 'ambient-canary')
    with pytest.raises(DatabaseCredentialError):
        resolve_dsn()
    monkeypatch.delenv('POSTGRES_PASSWORD')
    monkeypatch.setenv('DATABASE_PASSWORD_FILE', '')
    with pytest.raises(DatabaseCredentialError):
        resolve_dsn()


def test_direct_clients_and_outbox_cannot_bypass_file_resolver(monkeypatch, tmp_path):
    import pytest
    from app.config.database import DatabaseCredentialError
    from app.memory_kv.store import _dsn as memory_dsn
    from app.stores.postgres import _dsn as store_dsn
    from app.jobs.backfill import _dsn as backfill_dsn

    _file_env(monkeypatch, tmp_path)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://app:fake-canary@db/app_test')
    for resolver in (memory_dsn, store_dsn, backfill_dsn, outbox_service._open_conn):
        with pytest.raises(DatabaseCredentialError):
            resolver()


@pytest.mark.parametrize("host", ["/var/run/postgresql", "db,external.example.invalid", "localhost", "127.0.0.1", "::1"])
def test_host_database_probe_refuses_ambiguous_endpoint_translation(host):
    from app.config.database import DatabaseCredentialError, host_database_fields
    with pytest.raises(DatabaseCredentialError, match="database credential configuration refused"):
        host_database_fields({"host": host, "port": "5432", "user": "app", "dbname": "app_test"}, published_port=15434)


@pytest.mark.parametrize("key", ["host", "hostaddr"])
@pytest.mark.parametrize("address", [
    "127.0.0.2", "127.255.255.254", "::ffff:127.0.0.2", "::ffff:7f00:2",
    "0:0:0:0:0:0:0:1", "127.1", "2130706434", "0x7f000002", "0177.0.0.2",
    "LOCALHOST.", "0.0.0.0", "::",
])
def test_host_database_probe_rejects_semantic_loopback(key, address):
    from app.config.database import DatabaseCredentialError, host_database_fields
    fields = {"host": "database.example.invalid", "port": "5432", key: address}
    with pytest.raises(DatabaseCredentialError):
        host_database_fields(fields, published_port=15434)


@pytest.mark.parametrize("address", ["192.0.2.8", "::ffff:192.0.2.8", "2001:db8::8", "database.example.invalid"])
def test_host_database_probe_preserves_non_loopback_target(address):
    from app.config.database import host_database_fields
    fields = {"host": address, "port": "5432", "sslmode": "verify-full"}
    assert host_database_fields(fields, published_port=15434) == fields


@pytest.mark.parametrize("dsn", [
    "host=@ygg-review dbname=app_test", "host='' dbname=app_test", "dbname=app_test",
    "postgresql:///app_test", "postgresql:///?host=", "postgresql:///?host=%40ygg-review",
    "postgresql://%40ygg-review/app_test", "postgresql:///?host=%2Fvar%2Frun%2Fpostgresql",
])
def test_host_database_probe_rejects_libpq_socket_and_default_targets(dsn):
    from app.config.database import DatabaseCredentialError, credential_free_database_fields, host_database_fields
    fields = credential_free_database_fields(dsn)
    with pytest.raises(DatabaseCredentialError):
        host_database_fields(fields, published_port=15434)
