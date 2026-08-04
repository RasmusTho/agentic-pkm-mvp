from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest


def _marker_expr(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:]
    return ""


def _normalize_debug_env() -> None:
    raw = os.environ.get("DEBUG")
    if raw is None:
        return
    if raw.strip().lower() in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return
    # Test collection imports settings early; keep invalid local shell values
    # from breaking pytest bootstrap.
    os.environ["DEBUG"] = "false"


# Keep the repo's default unit-test run deterministic even if the developer has
# DATABASE_URL/DB_DSN exported in their shell.
#
# This is intentionally evaluated before importing app modules.
_mark_expr = _marker_expr(sys.argv).strip().lower()
_normalize_debug_env()
if "not pg" in _mark_expr:
    os.environ["STORE_BACKEND"] = "memory"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("DB_DSN", None)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class StoredObject:
    kind: str | None
    source_ref: str | None
    payload: dict[str, Any]
    embedding: list[float]
    model: str


class StubVectorIndex:
    def __init__(self) -> None:
        self.store: dict[UUID, StoredObject] = {}

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
        identity: Any | None = None,
    ) -> None:
        self.store[object_id] = StoredObject(
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=list(embedding),
            model=model,
        )

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        if not self.store:
            return []
        query_vec = list(embedding)
        results: list[Any] = []
        for object_id, stored in self.store.items():
            if filters and not all(stored.payload.get(k) == v for k, v in filters.items()):
                continue
            score = sum(a * b for a, b in zip(query_vec, stored.embedding, strict=False))
            from app.search.vector_index import VectorResult  # noqa: PLC0415

            results.append(VectorResult(object_id=object_id, score=score, payload=stored.payload))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:k]


@pytest.fixture
def stub_index(monkeypatch: pytest.MonkeyPatch) -> StubVectorIndex:
    import app.search as search_module  # noqa: PLC0415
    import app.search.service as search_service_module  # noqa: PLC0415
    from app.search import get_vector_index as original_get_vector_index  # noqa: PLC0415

    index = StubVectorIndex()

    def _get_index() -> StubVectorIndex:
        return index

    monkeypatch.setattr(search_module, "get_vector_index", _get_index)
    monkeypatch.setattr(search_service_module, "get_vector_index", _get_index)
    if hasattr(original_get_vector_index, "cache_clear"):
        original_get_vector_index.cache_clear()
    return index


@pytest.fixture
def clean_llm_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure a clean LLM environment for each test."""

    from app.config import llm as llm_config

    keys = [
        "LLM_PROVIDER",
        "LLM_MODEL",
        "EMBED_PROFILE",
        "EMBED_MODEL",
        "LLM_FORCE_PROVIDER",
        "LLM_FORCE_MODEL",
        "LLM_PROVIDER_ENFORCE",
        "OLLAMA_HOST",
        "OLLAMA_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    yield monkeypatch


@pytest.fixture(autouse=True)
def force_memory_store_for_non_pg(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Keep non-pg tests independent of DATABASE_URL/DB_DSN."""

    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    yield monkeypatch


@pytest.fixture(autouse=True)
def store_schema_autocreate_for_pg_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Explicit create-on-demand opt-in for pg-marked tests (KERNEL-04, #2766).

    Production store schema is migration-owned; ``_ensure_tables()`` is
    assert-only unless STORE_SCHEMA_AUTOCREATE is set. Test databases keep
    create-on-demand through this explicit fixture opt-in.
    """

    if (
        request.node.get_closest_marker("pg") is not None
        and os.getenv("STORE_SCHEMA_AUTOCREATE") is None
    ):
        monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    yield monkeypatch


@pytest.fixture(autouse=True)
def default_vault_layout_env(monkeypatch: pytest.MonkeyPatch):
    """Provide explicit test defaults for vault layout env.

    Runtime code must not assume folder names; tests set explicit defaults to
    keep behavior deterministic and avoid implicit fallbacks.

    This fixture never overrides a value that is already set.
    """

    if os.getenv("VAULT_SYSTEM_DIR_REL") is None:
        monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "⚙️ System")
    if os.getenv("VAULT_INBOX_DIR_REL") is None:
        monkeypatch.setenv("VAULT_INBOX_DIR_REL", "📥 Inbox")
    if os.getenv("VAULT_DESK_DIR_REL") is None:
        monkeypatch.setenv("VAULT_DESK_DIR_REL", "🛠️ Workbench")

    yield monkeypatch


@pytest.fixture(autouse=True)
def _reset_retrieval_tuning_cache():
    """Reset the RetrievalTuning process cache (ADR-0059 D3, #3404) around every test.

    Production code resolves this once per process from settings + env; tests monkeypatch
    RERANK_*/RETRIEVAL_* env vars per-case, so the cache must not leak a stale resolution from one
    test into the next.
    """

    from app.retrieval.tuning import reset_retrieval_tuning_cache

    reset_retrieval_tuning_cache()
    yield
    reset_retrieval_tuning_cache()


def pytest_addoption(parser) -> None:
    """Provide minimal timeout flags when pytest-timeout is unavailable."""

    group = parser.getgroup("timeout", "timeout control")
    try:
        group.addoption(
            "--timeout",
            action="store",
            type=float,
            dest="timeout",
            default=None,
            help="No-op stub for pytest-timeout's --timeout option.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--timeout-method",
            action="store",
            dest="timeout_method",
            default="signal",
            help="No-op stub for pytest-timeout's --timeout-method option.",
        )
    except ValueError:
        pass
    try:
        group.addoption(
            "--faulthandler-timeout",
            action="store",
            type=float,
            dest="faulthandler_timeout",
            default=None,
            help="No-op stub for pytest-faulthandler's --faulthandler-timeout option.",
        )
    except ValueError:
        pass


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "pg: marks tests requiring Postgres")

    # Fail loud if a non-zero --timeout was requested but the real pytest-timeout
    # plugin is not active. Otherwise the no-op stub above silently absorbs the
    # flag and the suite runs with NO per-test timeout — exactly the failure mode
    # behind the intermittent 22-min CI hangs (#2259): a hung test then has no
    # safety net at all. A missing/incompatible pytest-timeout must break the
    # build, not quietly disarm the watchdog.
    requested = getattr(config.option, "timeout", None)
    plugins = config.pluginmanager
    has_real_timeout = plugins.hasplugin("timeout") or plugins.hasplugin(
        "pytest_timeout"
    )
    if requested and not has_real_timeout:
        raise pytest.UsageError(
            f"--timeout={requested} was requested but the pytest-timeout plugin "
            "is not active; the per-test hang watchdog is disarmed. Install "
            "pytest-timeout (see dev-requirements.txt) or remove the --timeout "
            "flag. Refusing to run unguarded — see #2259."
        )

    # Must run here, before the first test module is imported (#4573).
    _refuse_prod_dsn_before_any_import()


# --------------------------------------------------------------------------
# pg-lane database resolution guard (#4573)
#
# The pg lane runs destructive DDL, TRUNCATE, and CREATE/DROP DATABASE against
# whatever DATABASE_URL/DB_DSN resolves to. It used to carry an autouse default
# of `postgresql://app:app@127.0.0.1:15432/app` — a DSN the repo's own
# `app.db.dsn.looks_like_prod_dsn` classifies as production on both criteria —
# so a bare `pytest -m pg` targeted prod. The resolution contract is now
# explicit-or-nothing.
#
# The prod refusal lives in `pytest_configure`, NOT in a collection hook. Test
# modules run connection probes at import time (`tests/stores/
# test_capabilities_matrix.py` evaluates `pg_available()` in a `skipif`, which
# opens a real connection), and every import happens *after* collection starts.
# A collection-time check therefore refuses only after the suite has already
# dialled production. `pytest_configure` runs before the first test module is
# imported, and it does not depend on which items were collected — so it also
# behaves under pytest-xdist, where the controller never collects.
#
# Every scratch-database factory under tests/ derives its admin DSN from
# `app.db.dsn.resolve_dsn()`, i.e. from exactly the environment checked here, so
# this single gate also stops CREATE/DROP DATABASE against a prod server.
# --------------------------------------------------------------------------

_PG_LANE_SCRATCH_HINT = (
    "DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test"
)

_PG_DSN_UNSET_REASON = (
    "no database configured for the pg lane: set DATABASE_URL or DB_DSN to an "
    "explicit non-production Postgres before running pg-marked tests, e.g. "
    f"{_PG_LANE_SCRATCH_HINT}. This lane has no default target on purpose "
    "(#4573) — it runs destructive DDL, TRUNCATE, and CREATE/DROP DATABASE."
)


def _redact_dsn(dsn: str) -> str:
    """Drop any password from a DSN so guard messages stay printable.

    Covers every shape `app.db.dsn.looks_like_prod_dsn` accepts: libpq keyword
    form (``host=... password=...``, tokenised with `shlex` exactly as that
    module does, so a quoted password is not half-echoed), URL userinfo
    (``postgresql://user:pw@host/db``), and a password passed as a URL query
    parameter (``...?password=...``), which the userinfo branch alone missed.
    """

    if "://" not in dsn and "=" in dsn:
        try:
            fields = shlex.split(dsn)
        except ValueError:
            return "<unparseable conninfo redacted>"
        parts = []
        for field in fields:
            key, sep, _ = field.partition("=")
            parts.append(f"{key}=***" if sep and key.lower() == "password" else field)
        return " ".join(parts)

    scheme, sep, rest = dsn.partition("://")
    if not sep:
        # Schemeless and keyword-less. `looks_like_prod_dsn` classifies this as
        # prod (app/db/dsn.py: `if "://" not in url: return True`), so it can
        # reach the abort message; a `user:pw@host` shape must not survive.
        if "@" in dsn:
            userinfo, _, hostpart = dsn.rpartition("@")
            user, has_password, _ = userinfo.partition(":")
            if has_password:
                return f"{user}:***@{hostpart}"
        return dsn

    rest, query_sep, query = rest.partition("?")
    if query:
        redacted_query = "&".join(
            f"{p.split('=', 1)[0]}=***"
            if p.split("=", 1)[0].lower() in {"password", "passfile"} and "=" in p
            else p
            for p in query.split("&")
        )
        query = redacted_query

    if "@" in rest:
        userinfo, _, hostpart = rest.rpartition("@")
        user, has_password, _ = userinfo.partition(":")
        if has_password:
            rest = f"{user}:***@{hostpart}"

    return f"{scheme}://{rest}{query_sep}{query}"


def _prod_dsn_abort_message(dsn: str, *, variable: str = "DATABASE_URL/DB_DSN") -> str:
    return (
        f"Refusing to run pg-marked tests: {variable} resolves to a "
        f"production-looking database ({_redact_dsn(dsn)}). "
        "app.db.dsn.looks_like_prod_dsn flags a DSN whose database name is "
        "exactly 'app' or whose port is the prod-published 15432. The pg lane "
        "runs destructive DDL, TRUNCATE, and CREATE/DROP DATABASE against the "
        f"resolved server. Point it at a scratch database, e.g. "
        f"{_PG_LANE_SCRATCH_HINT} (#4573)."
    )


_REACHABLE_PROD_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def _points_at_a_reachable_prod_server(dsn: str) -> bool:
    """Prod-classified *and* at an address this host can actually answer on.

    Used only for the second resolver below, where the built-in fallback is the
    compose-internal `…@db:5432/app`. That address is prod-shaped but reachable
    only from inside the compose network, so treating it as a refusal would
    abort ordinary runs. A loopback prod address is the real hazard.
    """

    from urllib.parse import urlsplit

    from app.db.dsn import looks_like_prod_dsn, resolve_dsn

    if not looks_like_prod_dsn(dsn):
        return False
    try:
        parts = urlsplit(resolve_dsn(dsn))
        return parts.hostname in _REACHABLE_PROD_HOSTS
    except ValueError:
        return True


def _refuse_prod_dsn_before_any_import() -> None:
    """Abort the session if any configured DSN points at production.

    Three writers, not one. `DATABASE_URL`/`DB_DSN` is the documented pair, but
    `app/config/database.py :: resolve_runtime_database_url` is a *second*
    resolver behind `app/db/db.py :: conn_rw`, fed by `PKM_DB_HOST`,
    `PKM_DB_PORT`, `PKM_DB_NAME_*` and `POSTGRES_*`. A run with
    `PKM_DB_HOST=127.0.0.1 PKM_DB_PORT=15432` and no `DATABASE_URL` reaches
    production through `conn_rw()` while the first pair looks unconfigured.
    `BUILDEROPS_DATABASE_URL` is a third, with its own CREATE SCHEMA path.
    """

    from app.config.database import explicit_runtime_database_url
    from app.db.dsn import looks_like_prod_dsn, resolve_dsn

    control_plane = os.getenv("BUILDEROPS_DATABASE_URL", "").strip()
    if control_plane and looks_like_prod_dsn(control_plane):
        raise pytest.UsageError(
            _prod_dsn_abort_message(control_plane, variable="BUILDEROPS_DATABASE_URL")
        )

    dsn = resolve_dsn()
    if dsn and looks_like_prod_dsn(dsn):
        raise pytest.UsageError(_prod_dsn_abort_message(dsn))

    runtime_dsn = explicit_runtime_database_url(os.environ)
    if runtime_dsn and _points_at_a_reachable_prod_server(runtime_dsn):
        raise pytest.UsageError(
            _prod_dsn_abort_message(runtime_dsn, variable="PKM_DB_* / POSTGRES_*")
        )

    # Only when nothing else named a target: that is the only situation in which
    # an empty conninfo can still be handed to libpq and take effect.
    if not dsn and not runtime_dsn:
        ambient = _ambient_libpq_target()
        if ambient and _points_at_a_reachable_prod_server(ambient):
            raise pytest.UsageError(
                _prod_dsn_abort_message(ambient, variable="PGHOST/PGPORT/PGDATABASE")
            )


def _ambient_libpq_target() -> str:
    """The DSN libpq would synthesise from its own environment, if any.

    `psycopg.connect("")` is not "no target": libpq fills the blanks from
    `PGHOST`/`PGPORT`/`PGDATABASE`. A run with those exported at the production
    values reaches production through any caller that hands an empty conninfo
    down, without `DATABASE_URL` ever being set.

    Deliberately narrow. With `PGHOST` unset libpq uses a **Unix domain
    socket**, which cannot reach the TCP-published prod container at all, so
    synthesising a `127.0.0.1` host there would invent a risk that does not
    exist and abort every run of a developer who merely has `PGDATABASE`
    exported for unrelated work. Returns "" unless `PGHOST` actually names a
    TCP host.
    """

    host = os.getenv("PGHOST", "").strip()
    if not host or host.startswith("/"):  # unset, or an explicit socket directory
        return ""
    port = os.getenv("PGPORT", "").strip() or "5432"
    user = os.getenv("PGUSER", "").strip() or "postgres"
    dbname = os.getenv("PGDATABASE", "").strip() or user
    # Only the first host of a multi-host list is modelled; the loopback check
    # below is what decides, and a list naming loopback first is the risky case.
    host = host.split(",", 1)[0].strip()
    if ":" in host and not host.startswith("["):  # bare IPv6 literal
        host = f"[{host}]"
    return f"postgresql://{user}@{host}:{port}/{dbname}"


def pytest_collection_modifyitems(config, items) -> None:
    """Skip pg-marked tests when no database was named, with a stated reason."""

    from app.db.dsn import resolve_dsn

    if resolve_dsn():
        return

    skip_pg = pytest.mark.skip(reason=_PG_DSN_UNSET_REASON)
    for item in items:
        if item.get_closest_marker("pg") is not None:
            item.add_marker(skip_pg)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Make an unconfigured pg lane loud rather than a silent run of 's'.

    Driven by the skip reports themselves rather than by state stashed during
    collection: under pytest-xdist the collection hook runs in the workers while
    this summary runs in the controller, so anything stashed on the worker's
    config is invisible here. Reports cross that boundary; config stashes do
    not. Reading the reports also means no banner is printed for a run that
    simply had no pg tests in it.
    """

    skipped = terminalreporter.stats.get("skipped", [])
    if not any(_PG_DSN_UNSET_REASON in str(report.longrepr) for report in skipped):
        return
    terminalreporter.write_sep("=", "pg lane skipped", red=True, bold=True)
    terminalreporter.write_line(_PG_DSN_UNSET_REASON)
