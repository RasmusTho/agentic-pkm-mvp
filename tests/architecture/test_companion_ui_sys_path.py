"""Regression for #3941: companion_ui must be importable from any test tree.

The companion_ui package lives at companion-ui/companion-app/companion_ui,
outside the rootdir pythonpath. Test trees beyond tests/companion_ui import it
at module level (tests/api, tests/uat, tests/tts), so the root conftest.py must
put companion-ui/companion-app on sys.path for every collection target — not
just for runs that happen to pass through tests/companion_ui/conftest.py.

The module-level import below is the regression: without the root-conftest
guard, standalone collection of this file (like any out-of-tree importer)
aborts with ModuleNotFoundError.
"""
from pathlib import Path

import companion_ui


def test_companion_ui_importable_from_any_test_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = (repo_root / "companion-ui" / "companion-app" / "companion_ui").resolve()
    package_dirs = [Path(p).resolve() for p in companion_ui.__path__]
    assert expected in package_dirs, (
        "companion_ui resolved outside this checkout: "
        f"{package_dirs} (expected {expected}); a machine-local install or an "
        "absolute sys.path entry from another checkout is shadowing the repo copy"
    )


def test_no_test_local_companion_ui_sys_path_shims() -> None:
    """Collection must rely on the declared consumer mechanism, not local shims."""
    repo_root = Path(__file__).resolve().parents[2]
    shim_paths = (
        "tests/companion_ui/conftest.py",
        "tests/tts/test_readback_segments_and_norm.py",
        "tests/uat/test_golden_path_integrated_runtime.py",
        "tests/api/test_companion_no_vault_routing.py",
    )
    for relative_path in shim_paths:
        shim_path = repo_root / relative_path
        if not shim_path.exists():
            continue
        source = shim_path.read_text(encoding="utf-8")
        assert "companion-ui/companion-app" not in source
        assert "companion_app_root" not in source


def test_ci_and_compose_use_declared_companion_ui_import_mechanisms() -> None:
    """CI shares root pytest collection; compose relies on its working directory."""
    repo_root = Path(__file__).resolve().parents[2]
    ci_source = (repo_root / ".github/workflows/ci-smoke.yaml").read_text(encoding="utf-8")
    compose_source = (repo_root / "docker-compose.yaml").read_text(encoding="utf-8")
    unit_test_job = ci_source.split("  pr-unit-tests-not-pg:", 1)[1].split(
        "  pr-index-pg-contracts:", 1
    )[0]

    assert "${{ github.workspace }}/companion-ui/companion-app" not in unit_test_job
    assert "PYTHONPATH: /app/companion-ui/companion-app:/app" not in compose_source
