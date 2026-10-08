"""Synthetic proofs for the opt-in validation-environment diagnostic."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTIC = REPO_ROOT / "scripts" / "validation_environment_readiness.py"

_DB_KEYS = {
    "DATABASE_URL",
    "DB_DSN",
    "BUILDEROPS_DATABASE_URL",
    "PKM_DB_HOST",
    "PKM_DB_PORT",
    "PKM_DB_NAME_DEV",
    "PKM_DB_NAME_TEST",
    "PKM_DB_NAME_PROD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGSERVICE",
    "PGSERVICEFILE",
}


def _clean_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _DB_KEYS}


def _write_python_wrapper(path: Path, interpreter: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"os.execvpe({interpreter!r}, [{interpreter!r}, *sys.argv[1:]], os.environ)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_diagnostic(
    *,
    tmp_path: Path,
    wrapper: Path,
    helper: Path,
    database_url: str | None = None,
    pythonpath: Path | None = None,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    environment = _clean_environment()
    environment["BUILDEROPS_PYTHON"] = str(wrapper)
    if pythonpath is not None:
        environment["PYTHONPATH"] = str(pythonpath)
    if database_url is not None:
        environment["DATABASE_URL"] = database_url
    environment.update(extra_environment or {})
    result = subprocess.run(
        [
            sys.executable,
            str(DIAGNOSTIC),
            "--target",
            "test",
            "--helper",
            str(helper),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    output = result.stdout
    assert str(tmp_path) not in output
    assert "credential" not in output.casefold()
    assert "acl" not in output.casefold()
    return json.loads(output)


def test_readiness_diagnostics_are_scoped_and_value_free(tmp_path: Path) -> None:
    """Classify toolchain, helper, and PG fixtures without touching a provider or DB."""

    module_root = tmp_path / "modules"
    module_root.mkdir()
    (module_root / "pytest.py").write_text("", encoding="utf-8")
    wrapper = tmp_path / "python-wrapper"
    _write_python_wrapper(wrapper, sys.executable)

    visible_helper = tmp_path / "visible-helper.py"
    visible_helper.write_text("raise SystemExit(0)\n", encoding="utf-8")
    missing_helper = tmp_path / "missing-helper.py"
    restricted_helper = tmp_path / "restricted-helper.py"
    restricted_helper.write_text("raise SystemExit(0)\n", encoding="utf-8")
    restricted_helper.chmod(0)
    unknown_helper = tmp_path / "unknown-helper.py"
    unknown_helper.write_text("raise SystemExit(7)\n", encoding="utf-8")

    # The wrapper is executable and the fixture makes the required import
    # compatible, while the helper invocation is independently visible.
    complete = _run_diagnostic(
        tmp_path=tmp_path,
        wrapper=wrapper,
        helper=visible_helper,
        pythonpath=module_root,
    )
    assert complete == {
        "helper": {"status": "visible"},
        "pg": {"status": "absent"},
        "target": "test",
        "toolchain": {
            "required_modules": ["pytest"],
            "status": "compatible",
        },
    }

    (module_root / "pytest.py").write_text(
        "raise RuntimeError('synthetic import incompatibility')\n", encoding="utf-8"
    )
    forbidden = _run_diagnostic(
        tmp_path=tmp_path,
        wrapper=wrapper,
        helper=missing_helper,
        database_url="postgresql://app:app@127.0.0.1:15432/app",
        pythonpath=module_root,
    )
    assert forbidden["helper"] == {"status": "missing"}
    assert forbidden["pg"] == {"status": "forbidden"}
    assert forbidden["toolchain"] == {
        "required_modules": ["pytest"],
        "status": "import_incompatible",
    }

    (module_root / "pytest.py").write_text("", encoding="utf-8")
    disposable = _run_diagnostic(
        tmp_path=tmp_path,
        wrapper=wrapper,
        helper=restricted_helper,
        database_url="postgresql://app:app@127.0.0.1:15434/app_test",
        pythonpath=module_root,
    )
    assert disposable["helper"] == {"status": "restricted"}
    assert disposable["pg"] == {"status": "disposable_candidate"}
    assert disposable["toolchain"] == {
        "required_modules": ["pytest"],
        "status": "compatible",
    }

    ambiguous = _run_diagnostic(
        tmp_path=tmp_path,
        wrapper=wrapper,
        helper=visible_helper,
        database_url="postgresql://app:app@127.0.0.1:15434/app_test",
        pythonpath=module_root,
        extra_environment={"PKM_DB_PORT": "15432"},
    )
    assert ambiguous["pg"] == {"status": "ambiguous"}

    unknown = _run_diagnostic(
        tmp_path=tmp_path,
        wrapper=wrapper,
        helper=unknown_helper,
        pythonpath=module_root,
    )
    assert unknown["helper"] == {"status": "unknown"}
