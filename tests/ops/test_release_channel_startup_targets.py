"""
Static inspection tests for canonical startup targets (Issue #967).

Verifies that the Makefile startup targets for test and prod channels
bind the correct compose file, compose project name, PKM_ENVIRONMENT,
and vault root — and that both require an explicit VAULT_ROOT.

No Docker required. Tests read the Makefile only.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _makefile_target_body(makefile_text: str, target_name: str) -> str | None:
    """Extract the body of a Makefile target.

    Anchors on `^<target>:` to avoid matching .PHONY declarations.
    Body ends at the next non-tab line (next target or variable).
    """
    pattern = re.compile(
        rf"^{re.escape(target_name)}\s*:.*?(?=\n\S|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(makefile_text)
    return match.group(0) if match else None


def test_test_start_target_binds_test_environment() -> None:
    """test-start-full must explicitly bind PKM_ENVIRONMENT=test and use
    the test compose overlay and project name.

    Verify: Issue #967 AC1 —
      tests/ops/test_release_channel_startup_targets.py::test_test_start_target_binds_test_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "test-start-full")

    assert body is not None, (
        "Could not find 'test-start-full' target in Makefile. "
        "A canonical test full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?test["\']?', body), (
        "Makefile 'test-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=test. Test startup must bind this to prevent "
        "test services from running with prod environment (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-test["\']?', body), (
        "Makefile 'test-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-test. "
        "Test and prod channels must use distinct project names (Issue #967)."
    )
    assert re.search(r'docker-compose\.test\.yml', body), (
        "Makefile 'test-start-full' target does not reference docker-compose.test.yml. "
        "The test overlay must be included in the test startup (Issue #967)."
    )


def test_prod_start_target_binds_prod_environment() -> None:
    """prod-start-full must explicitly bind PKM_ENVIRONMENT=prod and use
    the prod compose overlay and project name.

    Verify: Issue #967 AC2 —
      tests/ops/test_release_channel_startup_targets.py::test_prod_start_target_binds_prod_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "prod-start-full")

    assert body is not None, (
        "Could not find 'prod-start-full' target in Makefile. "
        "A canonical prod full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?prod["\']?', body), (
        "Makefile 'prod-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=prod. Prod startup must bind this explicitly "
        "to prevent implicit env inheritance (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-prod["\']?', body), (
        "Makefile 'prod-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-prod. "
        "Prod channel must use an explicit project name (Issue #967)."
    )
    assert re.search(r'docker-compose\.prod\.yml', body), (
        "Makefile 'prod-start-full' target does not reference docker-compose.prod.yml. "
        "The prod overlay must be included in the prod startup (Issue #967)."
    )


def test_full_start_targets_require_vault_root() -> None:
    """Both test-start-full and prod-start-full must enforce VAULT_ROOT.

    Targets must use the require-vault-root prerequisite or equivalent
    guard so they fail immediately when VAULT_ROOT is unset rather than
    silently starting with the wrong or empty vault path.

    Verify: Issue #967 AC3 —
      tests/ops/test_release_channel_startup_targets.py::test_full_start_targets_require_vault_root
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")

    for target_name in ("test-start-full", "prod-start-full"):
        body = _makefile_target_body(makefile_text, target_name)
        assert body is not None, (
            f"Could not find '{target_name}' target in Makefile (Issue #967)."
        )
        # Either the target declares require-vault-root as a dependency
        # or it contains an inline VAULT_ROOT guard.
        has_prereq = "require-vault-root" in body
        has_inline_guard = re.search(r'VAULT_ROOT', body) is not None
        assert has_prereq or has_inline_guard, (
            f"Makefile '{target_name}' target does not enforce VAULT_ROOT. "
            "Add 'require-vault-root' as a prerequisite or an inline guard "
            "to prevent startup without an explicit vault path (Issue #967)."
        )
