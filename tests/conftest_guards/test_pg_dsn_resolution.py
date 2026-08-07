"""The pg lane's database-resolution contract is explicit-or-nothing (#4573).

These tests drive the real `tests/conftest.py` gate through a child pytest
process, because the behaviour under test *is* the outcome of a run: whether a
`pytest -m pg` invocation reaches a database at all. Asserting on the hook in
isolation would prove the function, not the lane.

Two deliberate choices make the proofs load-bearing rather than decorative:

* Whether a database was contacted is measured with a `psycopg.connect` spy
  (`connect_spy.py`), not inferred from the absence of a connection-*failure*
  string. The failure-string form passes whether or not a server answered,
  which is exactly backwards for a guard whose worst case is a *successful*
  connection to production.
* The child collects both a real scratch-factory module and the suite's known
  import-time Postgres probe, so destructive fixture setup and collection-time
  connection behavior are both inside the blast radius of the assertion.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# A real scratch-database factory: its fixture resolves an admin DSN through
# app.db.dsn.resolve_dsn() and issues CREATE/DROP DATABASE against it.
SCRATCH_FACTORY_TARGET = "tests/migrations/test_store_schema_parity.py"

# A module that probes Postgres at *import* time, via a skipif that calls
# pg_available(). Collection imports it, so it is the reason the guard cannot
# live in a collection hook.
IMPORT_TIME_PROBE_TARGET = "tests/stores/test_capabilities_matrix.py"

BUILDEROPS_RECOVERY_TARGET = (
    "tests/ops/test_builderops_backup_restore.py"
    "::test_recovered_epoch_fences_leases_and_executor_until_reconciliation"
)

LATE_CONNECTION_PROBES = [
    "tests/conftest_guards/late_connection_probe.py::test_dynamic_explicit_conninfo_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_late_runtime_default_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_late_ambient_socket_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_late_service_file_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_module_kwargs_only_prod_target_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_sync_kwargs_override_safe_conninfo_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_async_service_kwarg_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_implicit_local_defaults_are_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_explicit_local_socket_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_leading_empty_host_member_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_trailing_empty_host_member_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_empty_hostaddr_member_is_blocked",
    "tests/conftest_guards/late_connection_probe.py::test_paired_empty_host_member_is_blocked",
]

# The DSN the removed autouse fixture used to install. Port 15432 and database
# `app` are both prod markers per app/db/dsn.py :: looks_like_prod_dsn.
PROD_DSN = "postgresql://app:app@127.0.0.1:15432/app"

# Same production *server*, different database. Only the port marks it, which is
# what makes it the right probe for the scratch-factory case: creating and
# dropping databases here still lands on the prod cluster.
PROD_SERVER_SCRATCH_DSN = "postgresql://app:app@127.0.0.1:15432/scratch_probe"

PYTEST_USAGE_ERROR = 4


def _run_pytest(
    targets: list[str],
    *,
    dsn: str | None,
    spy_log: Path,
    extra_args: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    # Drop the parent's DSN and its plugin policy: the repo's own full-suite
    # command sets PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, and an inherited copy would
    # leave the child without xdist, turning `-n 2` into an unknown option
    # rather than the configuration under test.
    dropped = {
        "DATABASE_URL",
        "DB_DSN",
        "BUILDEROPS_DATABASE_URL",
        "PKM_DB_HOST",
        "PKM_DB_PORT",
        "PKM_DB_NAME_DEV",
        "PKM_DB_NAME_TEST",
        "PKM_DB_NAME_PROD",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGHOSTADDR",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    }
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    if dsn is not None:
        env["DATABASE_URL"] = dsn
    env.update(env_overrides or {})
    env["PYTEST_ADDOPTS"] = ""
    env["PG_CONNECT_SPY_LOG"] = str(spy_log)

    args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-p",
        "tests.conftest_guards.connect_spy",
        "-m",
        "pg",
        *(extra_args or []),
        *targets,
    ]
    result = subprocess.run(
        args, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900
    )
    attempts = (
        [line for line in spy_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        if spy_log.exists()
        else []
    )
    return result, attempts


@pytest.fixture
def spy_log(tmp_path: Path) -> Path:
    return tmp_path / "connect-attempts.log"


def test_pg_marker_without_explicit_dsn_does_not_resolve_a_target(spy_log: Path) -> None:
    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET, IMPORT_TIME_PROBE_TARGET], dsn=None, spy_log=spy_log
    )
    output = result.stdout + result.stderr

    assert "no database configured for the pg lane" in output, output
    assert "DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test" in output, output
    assert "pg lane skipped" in output, output
    assert " skipped" in output, output
    assert " passed" not in output, output

    # Nothing was dialled with a target we named. `psycopg.connect("")` would
    # fall through to libpq's ambient defaults, so an empty conninfo is a
    # finding too, not a pass.
    assert attempts == [], attempts


def test_prod_looking_dsn_aborts_the_run(spy_log: Path) -> None:
    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET, IMPORT_TIME_PROBE_TARGET],
        dsn=PROD_DSN,
        spy_log=spy_log,
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert "Refusing to run pg-marked tests" in output, output
    assert "production-looking database" in output, output
    # The password must not be echoed back into CI logs.
    assert "app:app@127.0.0.1:15432/app" not in output, output
    assert "not echoed because it may contain credentials" in output, output

    # The whole point: the abort precedes every connection, including the
    # import-time probe in IMPORT_TIME_PROBE_TARGET.
    assert attempts == [], attempts


def test_scratch_factories_refuse_a_prod_server(spy_log: Path) -> None:
    """CREATE/DROP DATABASE on the prod *server* is refused, not only writes to `app`."""

    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET], dsn=PROD_SERVER_SCRATCH_DSN, spy_log=spy_log
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert "Refusing to run pg-marked tests" in output, output
    assert "CREATE DATABASE" not in output, output
    assert " passed" not in output, output
    assert attempts == [], attempts


# pytest-xdist is not in requirements.txt/dev-requirements.txt, so the CI unit
# lane cannot run the two parallel-mode proofs below. They still gate every
# local full-suite run and the nightly, which is where xdist is actually used.
requires_xdist = pytest.mark.skipif(
    importlib.util.find_spec("xdist") is None,
    reason="pytest-xdist not installed; the parallel-mode guard proofs need it",
)


@requires_xdist
def test_guard_survives_xdist(spy_log: Path) -> None:
    """`make smoke` and CI Smoke both run under xdist, where hooks split hosts.

    The collection hook runs in the workers and the terminal summary in the
    controller, so a guard that stashes state during collection reports nothing
    here — a silently skipped PG lane, which the contract forbids explicitly.
    """

    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn=None,
        spy_log=spy_log,
        extra_args=["-n", "2", "--dist=loadfile"],
    )
    output = result.stdout + result.stderr

    assert "pg lane skipped" in output, output
    assert "no database configured for the pg lane" in output, output
    assert attempts == [], attempts


@requires_xdist
def test_prod_dsn_aborts_cleanly_under_xdist(spy_log: Path) -> None:
    """A prod DSN must produce the stated refusal, not an INTERNALERROR."""

    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn=PROD_DSN,
        spy_log=spy_log,
        extra_args=["-n", "2", "--dist=loadfile"],
    )
    output = result.stdout + result.stderr

    assert "Refusing to run pg-marked tests" in output, output
    assert "INTERNALERROR" not in output, output
    assert attempts == [], attempts


def test_control_plane_dsn_is_guarded_too(spy_log: Path) -> None:
    """BUILDEROPS_DATABASE_URL has its own CREATE SCHEMA path against the server."""

    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn="postgresql://app:app@127.0.0.1:15434/app_test",
        spy_log=spy_log,
        env_overrides={"BUILDEROPS_DATABASE_URL": PROD_DSN},
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert "BUILDEROPS_DATABASE_URL resolves to a production-looking" in output, output
    assert attempts == [], attempts


def test_guarded_targets_are_still_what_the_proofs_assume() -> None:
    """Guard the guard: both probe targets must keep the property they stand for."""

    factory = (REPO_ROOT / SCRATCH_FACTORY_TARGET).read_text(encoding="utf-8")
    assert "CREATE DATABASE" in factory
    assert "DROP DATABASE" in factory
    assert "resolve_dsn" in factory

    probe = (REPO_ROOT / IMPORT_TIME_PROBE_TARGET).read_text(encoding="utf-8")
    # An import-time (module-level) call, i.e. one evaluated during collection.
    assert "skipif" in probe and "pg_available()" in probe


def test_runtime_resolver_env_is_guarded_too(spy_log: Path) -> None:
    """`PKM_DB_*` is a second resolver that reaches the DB without DATABASE_URL.

    `app/config/database.py :: resolve_runtime_database_url` feeds
    `app/db/db.py :: conn_rw`, so a run with only `PKM_DB_HOST`/`PKM_DB_PORT`
    set connects while `DATABASE_URL`/`DB_DSN` still look unconfigured.
    """

    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn=None,
        spy_log=spy_log,
        env_overrides={"PKM_DB_HOST": "127.0.0.1", "PKM_DB_PORT": "15432"},
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert "PKM_DB_* / POSTGRES_* resolves to a production-looking" in output, output
    assert attempts == [], attempts


def test_unconfigured_runtime_fallback_is_not_treated_as_explicit() -> None:
    """The compose-shaped fallback is ignored only when no writer named it."""

    from app.config.database import explicit_runtime_database_url

    assert explicit_runtime_database_url({}) is None
    assert explicit_runtime_database_url({"PKM_DB_HOST": "db"}) is not None


def test_connect_spy_cannot_hide_an_attempt(tmp_path: Path) -> None:
    """The spy is the instrument every `attempts == []` rests on — prove it works.

    All three psycopg entry points are distinct objects, and an *empty* conninfo
    (libpq ambient defaults) must be recorded as a finding rather than as a
    blank line a reader would strip.
    """

    log = tmp_path / "selftest.log"
    script = (
        "import asyncio, os, psycopg\n"
        "import tests.conftest_guards.connect_spy as spy\n"
        "assert psycopg.connect is not psycopg.Connection.connect\n"
        "D = 'postgresql://u:p@127.0.0.1:1/closed'\n"
        "errors = []\n"
        "for fn in (psycopg.connect, psycopg.Connection.connect):\n"
        "    try: fn(D, connect_timeout=1)\n"
        "    except Exception as exc: errors.append(str(exc))\n"
        "try: asyncio.run(psycopg.AsyncConnection.connect(D, connect_timeout=1))\n"
        "except Exception as exc: errors.append(str(exc))\n"
        "try: psycopg.connect('', connect_timeout=1)\n"
        "except Exception as exc: errors.append(str(exc))\n"
        "assert errors == ['connection blocked by pg safety probe'] * 4, errors\n"
    )
    env = dict(os.environ, PG_CONNECT_SPY_LOG=str(log))
    subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env, check=True, timeout=120)

    from tests.conftest_guards.connect_spy import AMBIENT

    recorded = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert recorded.count("postgresql://u:p@127.0.0.1:1/closed") == 3, recorded
    assert AMBIENT in recorded, recorded


@pytest.mark.parametrize("target", LATE_CONNECTION_PROBES)
def test_connection_guard_blocks_late_and_dynamic_targets(spy_log: Path, target: str) -> None:
    result, attempts = _run_pytest(
        [target],
        dsn="postgresql://app:app@127.0.0.1:15434/app_test",
        spy_log=spy_log,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "Refusing to run pg-marked tests" in output, output
    # If the connection-time wrapper regresses, the child plugin records and
    # blocks the attempt before a socket opens; a non-empty list is a failure.
    assert attempts == [], attempts


def test_refusal_message_never_echoes_conninfo() -> None:
    """The safest credential redaction is to never echo arbitrary conninfo."""

    from tests.conftest import _looks_like_prod_test_dsn, _prod_dsn_abort_message

    leaky = [
        # keyword conninfo, plain, quoted, and whitespace-separated
        "host=127.0.0.1 port=5432 dbname=app user=app password=hunter2",
        "dbname=app user=app password='hunter 2'",
        "host = 127.0.0.1 port = 15432 dbname = app password = hunter2",
        # URL userinfo, and password as a query parameter
        "postgresql://app:hunter2@127.0.0.1:15432/app",
        "postgresql://app@127.0.0.1:15432/db?password=hunter2",
        "postgresql://app@127.0.0.1:15432/db?pass%77ord=hunter2",
        "postgresql://app@127.0.0.1:15432/db?%70assword=hunter2",
        # schemeless: looks_like_prod_dsn classifies this as prod too
        "app:hunter2@127.0.0.1:15432/app",
    ]
    for dsn in leaky:
        assert _looks_like_prod_test_dsn(dsn), f"probe is not classified prod: {dsn}"
        message = _prod_dsn_abort_message()
        assert "hunter" not in message
        assert dsn not in message
        assert "not echoed because it may contain credentials" in message


def test_effective_libpq_query_parameters_are_classified_as_production() -> None:
    from tests.conftest import _looks_like_prod_test_dsn

    from app.db.dsn import looks_like_prod_dsn

    port_query = "postgresql:///app_test?host=127.0.0.1&port=15432"
    db_query = "postgresql:///safe?dbname=app"
    # The shared restore classifier is explicitly out of scope for #4573.
    assert not looks_like_prod_dsn(port_query)
    assert not looks_like_prod_dsn(db_query)
    assert _looks_like_prod_test_dsn(port_query)
    assert _looks_like_prod_test_dsn(db_query)


@pytest.mark.parametrize(
    "dsn",
    [
        "service=hidden_target",
        "postgresql:///safe?service=hidden_target",
    ],
)
def test_explicit_service_indirection_aborts_before_connect(spy_log: Path, dsn: str) -> None:
    result, attempts = _run_pytest([SCRATCH_FACTORY_TARGET], dsn=dsn, spy_log=spy_log)
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert "production-looking database" in output, output
    assert "hidden_target" not in output, output
    assert attempts == [], attempts


def test_test_guard_reads_effective_libpq_query_port() -> None:
    from tests.conftest import _looks_like_prod_test_dsn

    assert _looks_like_prod_test_dsn("postgresql:///safe?host=nonloopback.example&port=15432")


def test_keyword_conninfo_classifier_handles_whitespace_around_equals() -> None:
    from tests.conftest import _looks_like_prod_test_dsn

    assert _looks_like_prod_test_dsn(
        "host = nonloopback.example port = 15432 dbname = safe password = hunter2"
    )


def test_builderops_dsn_counts_as_configured_for_pg_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tests.conftest as test_config

    class Item:
        def __init__(self, path: Path, *, fixturenames: tuple[str, ...] = ()) -> None:
            self.path = path
            self.fixturenames = fixturenames
            self.markers: list[object] = []

        def get_closest_marker(self, name: str) -> object | None:
            return object() if name == "pg" else None

        def add_marker(self, marker: object) -> None:
            self.markers.append(marker)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("BUILDEROPS_DATABASE_URL", "postgresql://app:app@db:5432/builderops")
    item = Item(REPO_ROOT / "tests/builderops/control_plane/test_contract.py")
    test_config.pytest_collection_modifyitems(None, [item])
    assert item.markers == []

    recovery = Item(
        REPO_ROOT / "tests/ops/test_builderops_backup_restore.py",
        fixturenames=("recovery_store",),
    )
    test_config.pytest_collection_modifyitems(None, [recovery])
    assert recovery.markers == []

    unrelated = Item(REPO_ROOT / SCRATCH_FACTORY_TARGET)
    test_config.pytest_collection_modifyitems(None, [unrelated])
    assert len(unrelated.markers) == 1

    same_module_nonconsumer = Item(REPO_ROOT / "tests/ops/test_builderops_backup_restore.py")
    test_config.pytest_collection_modifyitems(None, [same_module_nonconsumer])
    assert len(same_module_nonconsumer.markers) == 1


def test_builderops_dsn_authorizes_the_real_recovery_consumer(spy_log: Path) -> None:
    builderops_dsn = "postgresql://app:app@127.0.0.1:15434/builderops_test"
    result, attempts = _run_pytest(
        [BUILDEROPS_RECOVERY_TARGET],
        dsn=None,
        spy_log=spy_log,
        env_overrides={"BUILDEROPS_DATABASE_URL": builderops_dsn},
    )
    output = result.stdout + result.stderr

    assert "no database configured for the pg lane" not in output, output
    assert "connection blocked by pg safety probe" in output, output
    assert attempts == [builderops_dsn], attempts


@pytest.mark.parametrize(
    "env_overrides,expected_variable",
    [
        (
            {
                "PGHOSTADDR": "127.0.0.1",
                "PGPORT": "15432",
                "PGDATABASE": "safe",
            },
            "PGHOST/PGPORT/PGDATABASE",
        ),
        ({"PGUSER": "app"}, "PGHOST/PGPORT/PGDATABASE"),
        (
            {"PGSERVICE": "production", "PGSERVICEFILE": "/nonexistent/pg_service.conf"},
            "PGSERVICE/PGSERVICEFILE configures libpq service indirection",
        ),
        (
            {"PGSERVICEFILE": "/nonexistent/pg_service.conf"},
            "PGSERVICE/PGSERVICEFILE configures libpq service indirection",
        ),
    ],
)
def test_ambient_libpq_escape_hatches_fail_before_connect(
    spy_log: Path, env_overrides: dict[str, str], expected_variable: str
) -> None:
    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn="postgresql://app:app@127.0.0.1:15434/app_test",
        spy_log=spy_log,
        env_overrides=env_overrides,
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert expected_variable in output, output
    assert attempts == [], attempts


@pytest.mark.parametrize(
    "env_overrides,expected_variable",
    [
        (
            {"PKM_DB_HOST": "nonloopback.example", "PKM_DB_PORT": "15432"},
            "PKM_DB_* / POSTGRES_*",
        ),
        (
            {
                "PGHOST": "nonloopback.example",
                "PGPORT": "15434,15432",
                "PGDATABASE": "safe",
            },
            "PGHOST/PGPORT/PGDATABASE",
        ),
    ],
)
def test_each_writer_is_guarded_independently_of_a_safe_primary_dsn(
    spy_log: Path, env_overrides: dict[str, str], expected_variable: str
) -> None:
    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn="postgresql://app:app@127.0.0.1:15434/app_test",
        spy_log=spy_log,
        env_overrides=env_overrides,
    )
    output = result.stdout + result.stderr

    assert result.returncode == PYTEST_USAGE_ERROR, output
    assert expected_variable in output, output
    assert attempts == [], attempts


def test_runtime_writer_does_not_authorize_primary_dsn_consumers(spy_log: Path) -> None:
    result, attempts = _run_pytest(
        [SCRATCH_FACTORY_TARGET],
        dsn=None,
        spy_log=spy_log,
        env_overrides={
            "PKM_ENVIRONMENT": "test",
            "PKM_DB_HOST": "127.0.0.1",
            "PKM_DB_PORT": "15434",
            "PKM_DB_NAME_TEST": "app_test",
        },
    )
    output = result.stdout + result.stderr

    assert "pg lane skipped" in output, output
    assert attempts == [], attempts


# The "no prod DSN survives in default position under tests/" census lives in
# tests/architecture/test_no_prod_dsn_defaults.py, which inspects string
# constants via AST rather than raw text — the right tool for that question.


if __name__ == "__main__":  # pragma: no cover - convenience only
    raise SystemExit(pytest.main([__file__]))
