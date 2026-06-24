"""Verify packaging layout correctness."""
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def _load_pyproject():
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)


def test_wheel_excludes_tests():
    """tests* must not appear in packages.find.include."""
    data = _load_pyproject()
    includes = (
        data.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )
    for pat in includes:
        assert not pat.startswith("tests"), (
            f"tests* should not be in [tool.setuptools.packages.find].include but found: {pat!r}"
        )


def test_core_runtime_deps_declared():
    """Core runtime packages must be declared in [project].dependencies."""
    data = _load_pyproject()
    deps = data.get("project", {}).get("dependencies", [])
    dep_names = {
        d.split(">=")[0].split("<=")[0].split("==")[0].split("[")[0].strip().lower()
        for d in deps
    }
    required = {"fastapi", "uvicorn", "sqlalchemy", "psycopg", "langgraph", "alembic", "jsonschema"}
    missing = required - dep_names
    assert not missing, f"Missing core runtime deps in [project].dependencies: {missing}"
