"""No test default may resolve to a production DSN (#4573).

`app.db.dsn.looks_like_prod_dsn` is the repo's definition of "this address is
production": database name exactly `app`, or the prod-published port 15432. A
test harness that hard-codes such a DSN *as a fallback* hands the pg lane —
destructive DDL, TRUNCATE, CREATE/DROP DATABASE — a production target whenever
the environment forgets to name one.

The census is deliberately about **default position**, not about the string
appearing at all: plenty of tests legitimately quote a prod-shaped DSN as
assertion data or as input to a guard they are proving. What must not exist is a
literal that *takes effect* when nothing else is configured:

    os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    resolve_dsn() or "postgresql://app:app@127.0.0.1:15432/app"
    def connect(dsn: str = "postgresql://app:app@127.0.0.1:15432/app"): ...
"""

from __future__ import annotations

import ast
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

from app.db.dsn import resolve_dsn
from tests.conftest import _looks_like_prod_test_dsn


REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

_ENV_LOOKUPS = {"getenv", "get"}


def _is_prod_dsn_constant(node: ast.AST) -> bool:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    return _parsed_conninfo(node.value) is not None and _looks_like_prod_test_dsn(node.value)


def _parsed_conninfo(value: str) -> dict[str, str] | None:
    """Return valid libpq conninfo, including keyword and URI forms."""

    try:
        return conninfo_to_dict(resolve_dsn(value))
    except Exception:
        return None


def _default_position_offenders(tree: ast.AST) -> list[tuple[int, str]]:
    """Prod-DSN constants sitting where they would take effect as a fallback."""

    hits: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # os.getenv("X", "<dsn>") / os.environ.get("X", "<dsn>")
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _ENV_LOOKUPS and len(node.args) >= 2:
                if _is_prod_dsn_constant(node.args[1]):
                    hits.append((node.lineno, "env-lookup default"))

        # <something> or "<dsn>"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values:
                if _is_prod_dsn_constant(value):
                    hits.append((node.lineno, "`or` fallback"))

        # def f(dsn="<dsn>") / lambda dsn="<dsn>"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for default in [*args.defaults, *(d for d in args.kw_defaults if d is not None)]:
                if _is_prod_dsn_constant(default):
                    hits.append((node.lineno, "parameter default"))

    return sorted(set(hits))


def _python_sources() -> list[Path]:
    return sorted(p for p in TESTS_ROOT.rglob("*.py") if p.is_file())


def test_no_test_default_resolves_to_a_prod_dsn() -> None:
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _default_position_offenders(tree)
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = hits

    assert not offenders, (
        "production-looking DSN literals in default position under tests/: "
        f"{offenders}. The pg lane must be pointed at a scratch database "
        "explicitly (DATABASE_URL/DB_DSN); it has no default target (#4573)."
    )


_DSN_ENV_VARS = {"DATABASE_URL", "DB_DSN", "BUILDEROPS_DATABASE_URL"}
# The runtime gate in tests/conftest.py checks four writer families; the census
# must not be narrower, or `injected-prod` stays open through the ones it omits.
_DSN_HOST_VARS = {"PKM_DB_HOST", "PGHOST"}
_DSN_PORT_VARS = {"PKM_DB_PORT", "PGPORT"}

# Loopback plus the prod-published port: the address a production container on
# the developer's own machine actually answers on. Unreachable prod-*shaped*
# sentinels (`db:5432` compose-internal, `configured.example`, `127.0.0.1:1`)
# are deliberately allowed — they exist to prove code paths without a server.
_REACHABLE_PROD_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
_PROD_PUBLISHED_PORT = 15432
_DEFAULT_POSTGRES_PORT = 5432


def _is_reachable_prod_dsn(value: str) -> bool:
    """Prod-classified AND at an address this host could actually answer on.

    Loopback is the discriminator. Both of `looks_like_prod_dsn`'s criteria
    count once the host is loopback: port 15432 is what the prod container
    publishes, and database `app` on the default 5432 is a locally installed
    production database. Non-loopback prod-shaped DSNs (`db:5432` compose
    internal, `configured.example`, TEST-NET) stay legal — they exist to drive
    code paths without a server.
    """

    parsed = _parsed_conninfo(value)
    if parsed is None or not _looks_like_prod_test_dsn(value):
        return False

    # A service file can name any host/port/database after pytest_configure,
    # where the runtime pre-import guard can no longer inspect it.
    if str(parsed.get("service", "") or "").strip():
        return True

    hosts = [
        part.strip()
        for key in ("host", "hostaddr")
        for part in str(parsed.get(key, "") or "").split(",")
        if part.strip()
    ]
    # No host means libpq's local Unix socket, which can still reach a locally
    # installed production database.
    if hosts and not any(host in _REACHABLE_PROD_HOSTS for host in hosts):
        return False

    ports = [
        part.strip() for part in str(parsed.get("port", "") or "").split(",") if part.strip()
    ] or [str(_DEFAULT_POSTGRES_PORT)]
    database = str(parsed.get("dbname", "") or "").strip()
    if str(_PROD_PUBLISHED_PORT) in ports:
        return True
    # Database `app` on the default port is a locally installed production
    # database. Any other port (1, 15433, 15434, …) is a deliberately-dead
    # sentinel or a non-prod channel.
    return str(_DEFAULT_POSTGRES_PORT) in ports and database == "app"


def _is_os_environ(node: ast.AST) -> bool:
    """`os.environ` / `environ`, so an unrelated dict subscript is not flagged."""

    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def _flag_host_port_dict(
    lineno: int, pairs: list[tuple[ast.AST, ast.AST]], bound: dict[str, str], hits: list
) -> None:
    """A dict literal naming host+port directly, e.g. env overrides in a call."""

    seen: dict[str, str] = {}
    for key_node, value_node in pairs:
        key = _resolve_str(key_node, bound)
        value = _resolve_str(value_node, bound)
        if key is None or value is None:
            continue
        if key in _DSN_HOST_VARS:
            seen["host"] = value
        elif key in _DSN_PORT_VARS:
            seen["port"] = value
        elif key in {"PKM_DB_NAME_PROD", "PGDATABASE"}:
            seen["db"] = value
    if seen.get("host") in _REACHABLE_PROD_HOSTS:
        port, db = seen.get("port", ""), seen.get("db", "")
        if port == str(_PROD_PUBLISHED_PORT) or (
            port in ("", str(_DEFAULT_POSTGRES_PORT)) and db == "app"
        ):
            hits.append((lineno, f"{seen['host']}:{port or _DEFAULT_POSTGRES_PORT}/{db or '?'}"))


def _module_string_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = "..."` bindings, so a named constant is not a hole."""

    bound: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
                bound[node.target.id] = node.value.value
    return bound


def _resolve_str(node: ast.AST, bound: dict[str, str]) -> str | None:
    """A string value knowable statically: literal, named constant, or concat."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bound.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_str(node.left, bound)
        right = _resolve_str(node.right, bound)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):  # f-string with only literal parts
        out = []
        for value in node.values:
            resolved = _resolve_str(value, bound)
            if resolved is None:
                return None
            out.append(resolved)
        return "".join(out)
    if isinstance(node, ast.FormattedValue):
        return _resolve_str(node.value, bound)
    return None


def _injected_reachable_prod_dsns(tree: ast.AST) -> list[tuple[int, str]]:
    """Statements that put a live production address into a DSN env var.

    Covers `monkeypatch.setenv(...)`, `os.environ[...] = ...`, and
    `os.environ.update({...})`, with values given as a literal, a module-level
    constant, a concatenation, or a literal f-string.

    This is a safety net, not a proof: a value assembled at runtime, read from a
    file, or passed through a helper this census cannot follow will not be seen.
    The runtime gate in tests/conftest.py is the guarantee; this exists to catch
    the shape that already bit once (#4573).
    """

    bound = _module_string_constants(tree)
    hits: list[tuple[int, str]] = []
    host_port: dict[int, dict[str, str]] = {}

    def flag(lineno: int, key_node: ast.AST, value_node: ast.AST) -> None:
        key = _resolve_str(key_node, bound)
        if key not in _DSN_ENV_VARS:
            return
        value = _resolve_str(value_node, bound)
        if value and _is_reachable_prod_dsn(value):
            hits.append((lineno, value))

    def flag_pair(lineno: int, key_node: ast.AST, value_node: ast.AST) -> None:
        """`PKM_DB_HOST`/`PGHOST` + the prod port name a target without a URL."""

        key = _resolve_str(key_node, bound)
        value = _resolve_str(value_node, bound)
        if value is None:
            return
        if key in _DSN_HOST_VARS:
            host_port.setdefault(0, {})["host"] = value
        elif key in _DSN_PORT_VARS:
            host_port.setdefault(0, {})["port"] = value
        elif key in {"PKM_DB_NAME_PROD", "PGDATABASE"}:
            host_port.setdefault(0, {})["db"] = value
        else:
            return
        seen = host_port[0]
        if seen.get("host") in _REACHABLE_PROD_HOSTS:
            port = seen.get("port", "")
            db = seen.get("db", "")
            if port == str(_PROD_PUBLISHED_PORT) or (
                port in ("", str(_DEFAULT_POSTGRES_PORT)) and db == "app"
            ):
                hits.append(
                    (lineno, f"{seen.get('host')}:{port or _DEFAULT_POSTGRES_PORT}/{db or '?'}")
                )

    for node in ast.walk(tree):
        # monkeypatch.setenv("DATABASE_URL", "...")
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "setenv" and len(node.args) >= 2:
                flag(node.lineno, node.args[0], node.args[1])
                flag_pair(node.lineno, node.args[0], node.args[1])
            # `dict.update` takes ONE positional argument; gating this on two
            # made the branch unreachable.
            elif name == "update" and isinstance(node.args[0], ast.Dict):
                pairs = [
                    (k, v) for k, v in zip(node.args[0].keys, node.args[0].values) if k is not None
                ]
                for k, v in pairs:
                    flag(node.lineno, k, v)
                _flag_host_port_dict(node.lineno, pairs, bound, hits)

        # os.environ["DATABASE_URL"] = "..."
        if isinstance(node, ast.Assign) and isinstance(
            node.value, (ast.Constant, ast.Name, ast.BinOp, ast.JoinedStr)
        ):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _is_os_environ(target.value):
                    flag(node.lineno, target.slice, node.value)

    return sorted(set(hits))


def test_no_test_injects_a_reachable_prod_dsn_into_the_environment() -> None:
    """A prod DSN installed at runtime is not inert, even in a non-pg test.

    `pytest_configure` cannot see this one: the value arrives via `monkeypatch`
    after the session is configured. It bit for real — `tests/stores/
    test_backend_auto_detection.py` set the live prod DSN, and that module's
    autouse teardown runs `reset_store_backends()` -> `truncate_pg_tables()`
    *before* monkeypatch restores the environment, issuing DELETE against
    production on any host publishing it on 15432 (#4573).
    """

    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _injected_reachable_prod_dsns(tree)
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = hits

    assert not offenders, (
        "tests inject a reachable production DSN into the environment: "
        f"{offenders}. Use an unreachable sentinel or the test-channel address "
        "(127.0.0.1:15434/app_test) — a live prod address in os.environ is one "
        "stray teardown away from writing to production (#4573)."
    )


def test_reachable_prod_classifier_is_neither_too_wide_nor_too_narrow() -> None:
    assert _is_reachable_prod_dsn("postgresql://app:app@127.0.0.1:15432/app")
    assert _is_reachable_prod_dsn("postgresql+psycopg://app:app@localhost:15432/scratch")

    # Unreachable sentinels stay legal.
    assert not _is_reachable_prod_dsn("postgresql://app:app@db:5432/app")
    assert not _is_reachable_prod_dsn("postgresql://configured.example/app")
    assert not _is_reachable_prod_dsn("postgresql://app:app@127.0.0.1:1/app")
    # Locally installed production on the default port is still production.
    assert _is_reachable_prod_dsn("postgresql://app:app@localhost:5432/app")
    assert _is_reachable_prod_dsn("host=127.0.0.1 port=15432 dbname=app")
    assert not _is_reachable_prod_dsn("postgresql://app:app@localhost:5432/app_test")
    assert not _is_reachable_prod_dsn("host=127.0.0.1 port=15434 dbname=app_test")
    # Non-prod channels stay legal.
    assert not _is_reachable_prod_dsn("postgresql://app:app@127.0.0.1:15434/app_test")


def test_conftest_carries_no_prod_dsn_at_all() -> None:
    """The shared harness is stricter than the census: no prod DSN, anywhere.

    `tests/conftest.py` applies to every test in the repo, so a prod DSN there
    is never inert regardless of the syntactic position it sits in.
    """

    source = (TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "default_pg_dsn_for_pg_tests" not in source

    # String constants only: the prose comment explaining *why* the default was
    # removed is documentation, not a target.
    tree = ast.parse(source, filename="tests/conftest.py")
    prod_constants = [node.value for node in ast.walk(tree) if _is_prod_dsn_constant(node)]
    assert not prod_constants, prod_constants


def test_census_recognises_each_default_position() -> None:
    """Guard the guard: every shape the census claims to catch must actually trip it."""

    prod = "postgresql://app:app@127.0.0.1:15432/app"
    scratch = "postgresql://app:app@127.0.0.1:15434/app_test"

    for template, label in (
        ('import os\nos.getenv("DATABASE_URL", "{dsn}")\n', "env-lookup default"),
        ('resolve_dsn() or "{dsn}"\n', "`or` fallback"),
        ('def connect(dsn: str = "{dsn}") -> None: ...\n', "parameter default"),
    ):
        prod_hits = _default_position_offenders(ast.parse(template.format(dsn=prod)))
        assert [reason for _, reason in prod_hits] == [label], (template, prod_hits)

        scratch_hits = _default_position_offenders(ast.parse(template.format(dsn=scratch)))
        assert not scratch_hits, (template, scratch_hits)

    # Assertion data and guard fixtures are not defaults and must stay allowed.
    inert = f'EXPECTED = "{prod}"\nassert resolved == "{prod}"\n'
    assert not _default_position_offenders(ast.parse(inert))

    keyword_prod = "host=127.0.0.1 port=15432 dbname=app"
    keyword_hits = _default_position_offenders(
        ast.parse(f'import os\nos.getenv("DATABASE_URL", "{keyword_prod}")\n')
    )
    assert [reason for _, reason in keyword_hits] == ["env-lookup default"]


def test_census_recognises_injected_keyword_conninfo() -> None:
    prod = "host=127.0.0.1 port=15432 dbname=app"
    scratch = "host=127.0.0.1 port=15434 dbname=app_test"

    prod_tree = ast.parse(
        f'def test_it(monkeypatch):\n    monkeypatch.setenv("DATABASE_URL", "{prod}")\n'
    )
    assert _injected_reachable_prod_dsns(prod_tree) == [(2, prod)]

    scratch_tree = ast.parse(
        f'def test_it(monkeypatch):\n    monkeypatch.setenv("DATABASE_URL", "{scratch}")\n'
    )
    assert not _injected_reachable_prod_dsns(scratch_tree)
