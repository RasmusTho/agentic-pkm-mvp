"""Channel-isolation preflight tests (Issue #1627).

Verifies that the preflight guard fail-closes when a compose overlay's
effective env bindings do not match the intended channel, and passes when they
do.

All tests are static (no Docker, no network, no running services) — they parse
compose YAML in-process or use in-memory YAML fixtures.

Policy authority: docs/RELEASE_CHANNELS/README.md §Invariants.

Acceptance criteria:
- AC1: test compose with PKM_ENVIRONMENT=prod is REJECTED with non-zero exit
  and a clear violation message.
- AC2: test compose with correct PKM_ENVIRONMENT=test + app_test DSN is
  ACCEPTED.
- AC3: error messages name the violating service, field, expected and actual
  values clearly.
- Verify: scripts/test/test_ui_doctor.sh invocation coverage is exercised by
  test_ui_doctor_surfaces_compose_mismatch.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.release_channels.channel_isolation_preflight import (
    check_compose_channel_isolation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"


def _write_compose(tmp_path: Path, content: str) -> Path:
    """Write an in-memory compose overlay to a temp file and return the path."""
    p = tmp_path / "docker-compose.test.yml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# AC1: drifted test compose with PKM_ENVIRONMENT=prod is REJECTED
# ---------------------------------------------------------------------------

def test_test_compose_with_prod_env_is_rejected(tmp_path: Path) -> None:
    """A test compose overlay that declares PKM_ENVIRONMENT=prod must be rejected.

    This is the incident scenario from Issue #1627: the test compose was
    locally modified to set PKM_ENVIRONMENT=prod, which would have bound the
    test stack to prod resources.

    AC1: preflight fails with a violation on PKM_ENVIRONMENT for every service
    that declares the wrong value.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          db:
            environment:
              POSTGRES_DB: app_test
            ports: !override
              - "15434:5432"

          api:
            ports: !override
              - "18002:8000"
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test

          worker:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test

          watcher:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when PKM_ENVIRONMENT=prod is declared in "
        "a test compose overlay, but it passed."
    )

    pkm_violations = [
        v for v in result.violations if v.field == "PKM_ENVIRONMENT"
    ]
    assert pkm_violations, (
        "Expected PKM_ENVIRONMENT violations but found none. "
        f"All violations: {result.violations}"
    )

    # Every application service that declares the wrong env should be caught.
    violating_services = {v.service for v in pkm_violations}
    assert "api" in violating_services
    assert "worker" in violating_services
    assert "watcher" in violating_services

    for v in pkm_violations:
        assert v.expected == "test"
        assert v.actual == "prod"


def test_rejection_message_names_mismatch_clearly(tmp_path: Path) -> None:
    """AC3: the summary message must clearly state expected vs actual values.

    The operator must be able to understand what is wrong and where without
    reading source code.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok
    summary = result.summary()

    assert "FAIL" in summary
    assert "test" in summary          # expected channel
    assert "prod" in summary          # actual value
    assert "PKM_ENVIRONMENT" in summary
    assert "api" in summary           # service name
    assert "Action required" in summary


# ---------------------------------------------------------------------------
# AC2: correct test compose with PKM_ENVIRONMENT=test is ACCEPTED
# ---------------------------------------------------------------------------

def test_correct_test_compose_is_accepted(tmp_path: Path) -> None:
    """A test compose overlay with PKM_ENVIRONMENT=test + app_test DSN must pass.

    This is the canonical correct state as shipped in docker-compose.test.yml.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          db:
            environment:
              POSTGRES_DB: app_test
            ports: !override
              - "15434:5432"

          api:
            ports: !override
              - "18002:8000"
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test

          worker:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test

          watcher:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert result.ok, (
        "Expected preflight to PASS for a correctly bound test compose, "
        f"but got violations:\n{result.summary()}"
    )
    assert "PASS" in result.summary()


def test_correct_test_compose_summary_confirms_pass(tmp_path: Path) -> None:
    """The summary string on a clean result contains 'PASS' and channel name."""
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert result.ok
    summary = result.summary()
    assert "PASS" in summary
    assert "test" in summary


# ---------------------------------------------------------------------------
# DSN binding checks
# ---------------------------------------------------------------------------

def test_test_compose_with_prod_dsn_is_rejected(tmp_path: Path) -> None:
    """Test compose overlay that uses a prod DSN (not app_test) is rejected.

    Scenario: PKM_ENVIRONMENT is correctly set to test, but DATABASE_URL
    points to the prod 'app' database — a resource isolation breach.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app
              DB_DSN: postgresql+psycopg://app:app@db:5432/app
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when DATABASE_URL points to prod 'app' DB "
        "in a test compose overlay."
    )
    dsn_violations = [v for v in result.violations if v.field in ("DATABASE_URL", "DB_DSN")]
    assert dsn_violations, f"Expected DSN violations, got: {result.violations}"
    for v in dsn_violations:
        assert "app_test" in v.expected


def test_prod_compose_with_test_dsn_is_rejected(tmp_path: Path) -> None:
    """Prod compose overlay that uses app_test DSN is rejected.

    Scenario: operator accidentally points the prod overlay at the test DB.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "prod")

    assert not result.ok
    dsn_violations = [v for v in result.violations if v.field in ("DATABASE_URL", "DB_DSN")]
    assert dsn_violations, f"Expected DSN violations, got: {result.violations}"


# ---------------------------------------------------------------------------
# Real repo compose files
# ---------------------------------------------------------------------------

def test_real_test_compose_passes_preflight() -> None:
    """The committed docker-compose.test.yml must pass the test channel preflight.

    This is a regression guard: if docker-compose.test.yml ever drifts to the
    incident state (PKM_ENVIRONMENT=prod or a prod DSN), this test will catch it
    before any stack start.
    """
    result = check_compose_channel_isolation(TEST_COMPOSE, "test")

    assert result.ok, (
        "docker-compose.test.yml does not satisfy the test-channel isolation "
        f"preflight.\n\n{result.summary()}"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unknown_channel_raises_value_error(tmp_path: Path) -> None:
    """Passing an unsupported channel name raises ValueError immediately."""
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: dev
        """,
    )

    with pytest.raises(ValueError, match="Unknown channel"):
        check_compose_channel_isolation(compose_path, "staging")


def test_overlay_with_no_channel_services_passes(tmp_path: Path) -> None:
    """An overlay that touches only db/ports (no app services) passes cleanly.

    The preflight only inspects services that carry channel env vars (api,
    worker, watcher). A db-only override has nothing to check.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          db:
            environment:
              POSTGRES_DB: app_test
            ports: !override
              - "15434:5432"
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert result.ok, (
        f"Expected PASS for db-only overlay, got: {result.summary()}"
    )


def test_partial_service_set_is_checked(tmp_path: Path) -> None:
    """Only services present in the overlay are checked; absent ones are skipped."""
    # Only 'api' is in this overlay — worker and watcher are absent.
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok
    violating_services = {v.service for v in result.violations}
    assert violating_services == {"api"}, (
        f"Expected only 'api' to be flagged, got: {violating_services}"
    )


# ---------------------------------------------------------------------------
# AC2 / test-ui-doctor integration coverage
# ---------------------------------------------------------------------------

def test_ui_doctor_surfaces_compose_mismatch(tmp_path: Path) -> None:
    """The preflight summary surfaces enough information for an operator to act.

    This test simulates the test-ui-doctor / verify-test-channel path: it
    calls the preflight and asserts that the output a human operator sees
    (the summary string) contains all necessary diagnostic information.

    Covers: scripts/test/test_ui_doctor.sh invocation coverage (AC2).
    """
    # Build a drifted compose — PKM_ENVIRONMENT=prod, correct DSN
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
          worker:
            environment:
              PKM_ENVIRONMENT: prod
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, "Drifted compose should fail preflight"

    summary = result.summary()

    # Operator-facing diagnostic requirements:
    assert "FAIL" in summary, "Summary must contain FAIL keyword"
    assert "channel-isolation preflight" in summary, "Summary must identify the check name"
    assert "PKM_ENVIRONMENT" in summary, "Summary must name the violating field"
    assert "'test'" in summary, "Summary must state the expected channel value"
    assert "prod" in summary, "Summary must state the actual wrong value"
    assert "Action required" in summary, "Summary must include remediation guidance"
    assert "read-only" in summary.lower(), "Summary must state that the check is read-only"

    # Non-zero exit behavior: result.ok is False, so callers must use non-zero exit.
    # The CLI entry point maps this to exit code 1.
    assert result.ok is False


# ---------------------------------------------------------------------------
# AC1 (Issue #1655): omitted DSN in app-service overlay fails closed
# ---------------------------------------------------------------------------

def test_omitted_dsn_in_test_overlay_fails_closed(tmp_path: Path) -> None:
    """A test overlay that sets PKM_ENVIRONMENT=test but omits DATABASE_URL / DB_DSN
    must FAIL the preflight (fail-closed behaviour, Issue #1655).

    Scenario: the base docker-compose.yaml env_file supplies
    DATABASE_URL=.../app (prod DB). The test overlay sets PKM_ENVIRONMENT=test
    but forgets to override the DSN keys.  After compose layering the effective
    DATABASE_URL still points at the prod 'app' database — a channel-isolation
    breach the operator cannot see from the overlay alone.

    The preflight must detect the omission of channel-critical DSN keys and
    fail closed so the operator is forced to add explicit test-channel DSNs.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              WATCHER_STATE_DIR: tmp-test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when DATABASE_URL / DB_DSN are omitted "
        "from a test-channel overlay that does set PKM_ENVIRONMENT — the "
        "effective DSN can fall back to the prod 'app' DB via the base compose "
        "env_file.  Got: " + result.summary()
    )
    dsn_violations = [v for v in result.violations if v.field in ("DATABASE_URL", "DB_DSN")]
    assert dsn_violations, (
        "Expected violations for missing DATABASE_URL / DB_DSN, "
        f"but violations list was: {result.violations}"
    )
    for v in dsn_violations:
        assert "app_test" in v.expected, (
            f"Violation expected value should mention 'app_test', got: {v.expected!r}"
        )


def test_omitted_database_url_only_fails_closed(tmp_path: Path) -> None:
    """Only DATABASE_URL is omitted; DB_DSN is correctly set.

    Both keys are channel-critical; omitting either one is a violation.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when DATABASE_URL is omitted even if "
        "DB_DSN is correctly set.  Got: " + result.summary()
    )
    missing_url_violations = [v for v in result.violations if v.field == "DATABASE_URL"]
    assert missing_url_violations, (
        "Expected a violation for missing DATABASE_URL, "
        f"but violations were: {result.violations}"
    )


def test_omitted_db_dsn_only_fails_closed(tmp_path: Path) -> None:
    """Only DB_DSN is omitted; DATABASE_URL is correctly set.

    Both keys are channel-critical; omitting either one is a violation.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when DB_DSN is omitted even if "
        "DATABASE_URL is correctly set.  Got: " + result.summary()
    )
    missing_dsn_violations = [v for v in result.violations if v.field == "DB_DSN"]
    assert missing_dsn_violations, (
        "Expected a violation for missing DB_DSN, "
        f"but violations were: {result.violations}"
    )


def test_both_dsn_omitted_from_all_services_fails_closed(tmp_path: Path) -> None:
    """All three channel services omit DATABASE_URL / DB_DSN; all must be flagged."""
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
          worker:
            environment:
              PKM_ENVIRONMENT: test
          watcher:
            environment:
              PKM_ENVIRONMENT: test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert not result.ok, (
        "Expected preflight to FAIL when all three services omit DSN keys.  "
        "Got: " + result.summary()
    )
    violating_services = {v.service for v in result.violations}
    assert "api" in violating_services
    assert "worker" in violating_services
    assert "watcher" in violating_services


def test_service_with_no_env_block_is_not_flagged_for_missing_dsn(tmp_path: Path) -> None:
    """A service that has NO environment block at all is not flagged for missing DSN.

    The omitted-DSN check only applies when the service IS present in the overlay
    and HAS some environment keys set.  A completely absent service section is
    already handled by the existing skip-if-no-env rule.
    """
    # Only 'db' appears; all app services are absent from this overlay.
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          db:
            environment:
              POSTGRES_DB: app_test
            ports: !override
              - "15434:5432"
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert result.ok, (
        "Expected PASS when no app services appear in the overlay at all, "
        f"but got: {result.summary()}"
    )


def test_correctly_declared_test_dsn_still_passes(tmp_path: Path) -> None:
    """Positive case: PKM_ENVIRONMENT=test with both DSN keys set to app_test passes.

    This is the AC2 regression guard from Issue #1655 — the fix must not break
    overlays that correctly declare all three channel-critical keys.
    """
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
          worker:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
          watcher:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
              DB_DSN: postgresql+psycopg://app:app@db:5432/app_test
        """,
    )

    result = check_compose_channel_isolation(compose_path, "test")

    assert result.ok, (
        "Expected PASS for a correctly declared test-channel overlay, "
        f"but got violations:\n{result.summary()}"
    )
