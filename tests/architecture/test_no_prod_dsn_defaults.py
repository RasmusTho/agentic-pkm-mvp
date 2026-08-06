"""No test default may resolve to a production DSN (#4573).

`tests/conftest.py` enforces the dynamic guarantee twice: before imports for
inherited configuration, and again at every psycopg connection entry point for
late or dynamically assembled values. This AST census has one deliberately
smaller job: prevent a production-looking literal from returning as a default.

The census is about **default position**, not about the string appearing at
all. Tests legitimately quote prod-shaped DSNs as assertion data and guard
inputs. What must not exist is a literal that takes effect when configuration
is absent:

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


def _parsed_conninfo(value: str) -> dict[str, str] | None:
    """Return valid libpq conninfo, including keyword and URI forms."""

    try:
        return conninfo_to_dict(resolve_dsn(value))
    except Exception:
        return None


def _is_prod_dsn_constant(node: ast.AST) -> bool:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    return _parsed_conninfo(node.value) is not None and _looks_like_prod_test_dsn(node.value)


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
            for default in [
                *args.defaults,
                *(item for item in args.kw_defaults if item is not None),
            ]:
                if _is_prod_dsn_constant(default):
                    hits.append((node.lineno, "parameter default"))

    return sorted(set(hits))


def _python_sources() -> list[Path]:
    return sorted(path for path in TESTS_ROOT.rglob("*.py") if path.is_file())


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


def test_conftest_carries_no_prod_dsn_at_all() -> None:
    """The shared harness is stricter than the census: no prod DSN, anywhere."""

    source = (TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "default_pg_dsn_for_pg_tests" not in source

    # String constants only: the prose comment explaining why the default was
    # removed is documentation, not a target.
    tree = ast.parse(source, filename="tests/conftest.py")
    prod_constants = [node.value for node in ast.walk(tree) if _is_prod_dsn_constant(node)]
    assert not prod_constants, prod_constants


def test_census_recognises_each_default_position() -> None:
    """Guard the guard: every claimed default shape must actually trip it."""

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
