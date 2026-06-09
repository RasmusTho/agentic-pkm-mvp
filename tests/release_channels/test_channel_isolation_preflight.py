"""Channel-isolation preflight tests (Issues #1627, #1655, #1769).

Verifies that the preflight guard fail-closes when a compose overlay's
effective env bindings do not match the intended channel, and passes when they
do.

Issue #1655 extends the contract to omitted DSN bindings: when a
channel-critical app service omits `DATABASE_URL` / `DB_DSN` from the overlay,
the effective binding falls back to the base compose `env_file`
(`config/runtime.defaults.env`, which carries prod `app` DSNs). The preflight
must resolve that effective binding and fail closed when it lands on another
channel — or when it cannot be resolved at all.

Issue #1769 extends the contract to the full per-service env_file chain: compose
allows multiple `env_file` entries per service, later files winning.  The base
services include `${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}` after the
defaults file.  A wrong-channel DSN in a later layer must be caught.  The
preflight resolves DSN keys through the full chain and fails closed when a
required env_file is missing or any env_file cannot be read.

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
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"

#: Mirrors the channel-critical lines of config/runtime.defaults.env: the base
#: compose env_file supplies prod 'app' DSNs to every app service by default.
PROD_BASE_DEFAULTS = """\
DATABASE_URL=postgresql+psycopg://app:app@db:5432/app
DB_DSN=postgresql+psycopg://app:app@db:5432/app
"""


def _write_compose(tmp_path: Path, content: str) -> Path:
    """Write an in-memory compose overlay to a temp file and return the path."""
    p = tmp_path / "docker-compose.test.yml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _write_base_defaults(tmp_path: Path, content: str = PROD_BASE_DEFAULTS) -> Path:
    """Write a base-compose env_file next to the overlay (config/runtime.defaults.env)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    p = config_dir / "runtime.defaults.env"
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
# Omitted DSN bindings fail closed (Issue #1655)
# ---------------------------------------------------------------------------

def test_test_compose_with_omitted_dsn_keys_is_rejected(tmp_path: Path) -> None:
    """Omitting DATABASE_URL / DB_DSN from a test app service must fail closed.

    Incident scenario from PR #1633 review thread PRRT_kwDOQEip6s6HlGmN: the
    test overlay loses its DSN keys, the base compose env_file
    (config/runtime.defaults.env) still supplies prod 'app' DSNs, and the old
    preflight skipped missing keys and reported PASS while the effective test
    stack pointed at prod resources.
    """
    _write_base_defaults(tmp_path)
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
        "Expected preflight to FAIL when DATABASE_URL / DB_DSN are omitted "
        "from the test overlay while base defaults supply prod DSNs, "
        "but it passed."
    )

    dsn_violations = [
        v for v in result.violations if v.field in ("DATABASE_URL", "DB_DSN")
    ]
    violating = {(v.service, v.field) for v in dsn_violations}
    for svc in ("api", "worker", "watcher"):
        assert (svc, "DATABASE_URL") in violating, (
            f"Expected omitted DATABASE_URL violation for {svc!r}, got: {violating}"
        )
        assert (svc, "DB_DSN") in violating, (
            f"Expected omitted DB_DSN violation for {svc!r}, got: {violating}"
        )


def test_test_compose_with_single_omitted_dsn_key_is_rejected(tmp_path: Path) -> None:
    """Omitting only one of the two DSN keys is still a violation.

    DATABASE_URL is correctly bound to app_test, but DB_DSN is omitted and
    falls back to the prod base default.
    """
    _write_base_defaults(tmp_path)
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
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

    assert not result.ok
    violating = {(v.service, v.field) for v in result.violations}
    assert violating == {("api", "DB_DSN")}, (
        f"Expected exactly one omitted DB_DSN violation for 'api', got: {violating}"
    )


def test_omitted_dsn_violation_message_names_fallback(tmp_path: Path) -> None:
    """The omitted-DSN violation must tell the operator what actually happens.

    The summary must name the omitted key, the service, and the fact that the
    effective binding falls back to a base default on the wrong channel.
    """
    _write_base_defaults(tmp_path)
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
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

    assert not result.ok
    summary = result.summary()
    assert "DB_DSN" in summary
    assert "api" in summary
    assert "omitted" in summary.lower()
    assert "app_test" in summary  # the expected channel binding
    assert "5432/app" in summary  # the prod fallback actually in effect


def test_omitted_dsn_without_resolvable_base_defaults_fails_closed(
    tmp_path: Path,
) -> None:
    """If the base defaults file cannot be resolved, omission still fails.

    Fail-closed posture: when the preflight cannot prove what the effective
    DSN binding is, it must reject rather than assume the binding is safe.
    """
    # NOTE: no _write_base_defaults — config/runtime.defaults.env is absent.
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: test
              DATABASE_URL: postgresql+psycopg://app:app@db:5432/app_test
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

    assert not result.ok, (
        "Expected fail-closed rejection when an omitted DSN binding cannot "
        "be resolved against base defaults, but the preflight passed."
    )
    violating = {(v.service, v.field) for v in result.violations}
    assert ("api", "DB_DSN") in violating


def test_absent_channel_service_is_still_checked(tmp_path: Path) -> None:
    """A channel-critical service absent from the overlay is still checked.

    Compose layering starts the base service regardless: a test overlay that
    drops the 'worker' block entirely still runs worker against the base prod
    DSNs. Absence is the most complete form of omission and must fail closed.
    """
    _write_base_defaults(tmp_path)
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
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

    assert not result.ok
    violating_services = {v.service for v in result.violations}
    assert violating_services == {"worker"}, (
        f"Expected only the absent 'worker' service to be flagged, "
        f"got: {violating_services}"
    )


def test_prod_compose_with_omitted_dsn_and_prod_base_default_passes(
    tmp_path: Path,
) -> None:
    """Prod overlay omitting DSNs is fine when base defaults ARE the prod DSNs.

    Mirrors the shipped docker-compose.prod.yml: the prod overlay does not
    redeclare DATABASE_URL / DB_DSN because the base default already binds the
    prod 'app' DB. The effective binding resolves to the intended channel, so
    omission is not a violation here. One product, channel-aware resolution —
    not a prod-only exemption.
    """
    _write_base_defaults(tmp_path)
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              API_HEALTHCHECK_URL: http://host.docker.internal:18000/healthz
        """,
    )

    result = check_compose_channel_isolation(compose_path, "prod")

    assert result.ok, (
        "Expected prod preflight to PASS when omitted DSNs resolve to prod "
        f"base defaults, but got violations:\n{result.summary()}"
    )


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


def test_real_prod_compose_passes_preflight() -> None:
    """The committed docker-compose.prod.yml must pass the prod channel preflight.

    The prod overlay relies on base defaults (config/runtime.defaults.env) for
    its DSN bindings; the preflight must resolve that fallback to the prod
    channel and pass — omission only fails when the fallback crosses channels.
    """
    result = check_compose_channel_isolation(PROD_COMPOSE, "prod")

    assert result.ok, (
        "docker-compose.prod.yml does not satisfy the prod-channel isolation "
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


def test_db_only_test_overlay_fails_closed_on_dsn_fallback(tmp_path: Path) -> None:
    """A test overlay that touches only db/ports fails closed (Issue #1655).

    Compose layering still starts api/worker/watcher from the base file, where
    the base defaults bind the prod 'app' DSNs. A db-only test overlay
    therefore runs every app service against prod resources — the preflight
    must reject it.
    """
    _write_base_defaults(tmp_path)
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

    assert not result.ok, (
        "Expected FAIL for a db-only test overlay whose app services fall "
        "back to prod base DSNs, but the preflight passed."
    )
    violating_services = {v.service for v in result.violations}
    assert violating_services == {"api", "worker", "watcher"}


def test_partial_service_set_flags_declared_and_absent_services(
    tmp_path: Path,
) -> None:
    """Declared services are checked directly; absent ones via base fallback."""
    # Only 'api' is in this overlay — worker and watcher are absent and fall
    # back to the prod base defaults.
    _write_base_defaults(tmp_path)
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
    assert violating_services == {"api", "worker", "watcher"}, (
        f"Expected api (wrong PKM_ENVIRONMENT) plus absent worker/watcher "
        f"(prod DSN fallback) to be flagged, got: {violating_services}"
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
# Issue #1769 — full env_file chain resolution
# ---------------------------------------------------------------------------
# Helpers for these tests: write a minimal base docker-compose.yaml that
# mirrors the real base compose structure (services with multi-layer env_file),
# plus a synthetic second env_file that represents the runtime layer.

def _write_base_compose(
    tmp_path: Path,
    second_env_file: str = "./tmp/runtime.env",
    required: bool = False,
) -> Path:
    """Write a minimal docker-compose.yaml mirroring real base compose structure.

    Each app service (api, worker, watcher) gets:
    - ``config/runtime.defaults.env`` as the first env_file (always required)
    - a second env_file at *second_env_file* with the given *required* flag.
    """
    required_str = "true" if required else "false"
    content = textwrap.dedent(f"""\
        services:
          db:
            env_file:
              - ./config/runtime.defaults.env
          api:
            env_file:
              - ./config/runtime.defaults.env
              - path: {second_env_file}
                required: {required_str}
          worker:
            env_file:
              - ./config/runtime.defaults.env
              - path: {second_env_file}
                required: {required_str}
          watcher:
            env_file:
              - ./config/runtime.defaults.env
              - path: {second_env_file}
                required: {required_str}
    """)
    p = tmp_path / "docker-compose.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _write_runtime_env(tmp_path: Path, content: str) -> Path:
    """Write a runtime env file in ``tmp_path/tmp/runtime.env``."""
    runtime_dir = tmp_path / "tmp"
    runtime_dir.mkdir(exist_ok=True)
    p = runtime_dir / "runtime.env"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_layered_env_file_wrong_channel_dsn_fails(tmp_path: Path) -> None:
    """AC1(#1769): omitted DSN key whose winning env_file layer supplies a
    wrong-channel DSN must fail the preflight.

    Scenario: base compose has a second env_file layer (./tmp/runtime.env, optional)
    that carries DATABASE_URL pointing at app_test. The overlay declares only
    PKM_ENVIRONMENT=prod but omits DATABASE_URL/DB_DSN.  Compose resolves the
    DSNs from the second layer, which is wrong for the prod channel.
    """
    _write_base_defaults(tmp_path)  # first layer: prod DSNs
    _write_base_compose(tmp_path, second_env_file="./tmp/runtime.env", required=False)
    # Second layer wins → test DSNs in a prod-intended stack
    _write_runtime_env(
        tmp_path,
        """\
        DATABASE_URL=postgresql+psycopg://app:app@db:5432/app_test
        DB_DSN=postgresql+psycopg://app:app@db:5432/app_test
        """,
    )
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
          worker:
            environment:
              PKM_ENVIRONMENT: prod
          watcher:
            environment:
              PKM_ENVIRONMENT: prod
        """,
    )

    result = check_compose_channel_isolation(
        compose_path,
        "prod",
        base_compose_path=tmp_path / "docker-compose.yaml",
    )

    assert not result.ok, (
        "Expected FAIL when a later env_file layer supplies a test-channel DSN "
        f"for a prod-intended stack, but got PASS.\n{result.summary()}"
    )
    dsn_violations = [v for v in result.violations if v.field in ("DATABASE_URL", "DB_DSN")]
    assert dsn_violations, (
        f"Expected DSN violations from the layered env_file, got: {result.violations}"
    )
    # Violation message must reference the wrong-channel value that was found
    summary = result.summary()
    assert "app_test" in summary, "Summary must name the wrong DSN fragment found"


def test_layered_env_file_correct_channel_dsn_passes(tmp_path: Path) -> None:
    """AC2(#1769): omitted DSN key whose winning env_file layer supplies the
    intended-channel DSN must pass.

    Scenario: second layer carries prod-correct DSNs; overlay declares only
    PKM_ENVIRONMENT.  Effective DSN is channel-correct → PASS.
    """
    _write_base_defaults(tmp_path)  # first layer: prod DSNs (already correct)
    _write_base_compose(tmp_path, second_env_file="./tmp/runtime.env", required=False)
    # Second layer also carries prod DSNs — still channel-correct
    _write_runtime_env(
        tmp_path,
        """\
        DATABASE_URL=postgresql+psycopg://app:app@db:5432/app
        DB_DSN=postgresql+psycopg://app:app@db:5432/app
        """,
    )
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
          worker:
            environment:
              PKM_ENVIRONMENT: prod
          watcher:
            environment:
              PKM_ENVIRONMENT: prod
        """,
    )

    result = check_compose_channel_isolation(
        compose_path,
        "prod",
        base_compose_path=tmp_path / "docker-compose.yaml",
    )

    assert result.ok, (
        "Expected PASS when the winning env_file layer supplies the correct "
        f"channel DSN, but got violations:\n{result.summary()}"
    )


def test_unreadable_winning_env_file_layer_fails_closed(tmp_path: Path) -> None:
    """AC3(#1769): an env_file that exists but cannot be read must fail closed.

    The preflight must never silently skip an unreadable file — it cannot
    verify what the effective binding would be, so it must reject.
    """
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path, second_env_file="./tmp/runtime.env", required=False)
    runtime_env = _write_runtime_env(
        tmp_path,
        "DATABASE_URL=postgresql+psycopg://app:app@db:5432/app\n",
    )
    # Make the file unreadable
    runtime_env.chmod(0o000)

    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
          worker:
            environment:
              PKM_ENVIRONMENT: prod
          watcher:
            environment:
              PKM_ENVIRONMENT: prod
        """,
    )

    try:
        result = check_compose_channel_isolation(
            compose_path,
            "prod",
            base_compose_path=tmp_path / "docker-compose.yaml",
        )

        assert not result.ok, (
            "Expected FAIL when a referenced env_file exists but cannot be "
            f"read, but got PASS.\n{result.summary()}"
        )
        summary = result.summary()
        # Summary must tell the operator which file was unreadable
        assert "runtime.env" in summary, (
            f"Summary must name the unreadable file; got:\n{summary}"
        )
        assert "unresolvable" in summary.lower() or "cannot be read" in summary.lower(), (
            f"Summary must state the file could not be read; got:\n{summary}"
        )
    finally:
        # Restore permissions so pytest cleanup can remove the temp dir
        runtime_env.chmod(0o644)


def test_required_missing_env_file_layer_fails_closed(tmp_path: Path) -> None:
    """Missing required env_file layer fails closed (posture per docs/RELEASE_CHANNELS/README.md).

    When a referenced env_file is marked ``required: true`` (the default) and
    does not exist, the preflight cannot verify what value compose would use, so
    it must fail closed for all keys that would have been resolved from that
    layer onward.
    """
    _write_base_defaults(tmp_path)
    # required=True for the second layer — but we do NOT write it
    _write_base_compose(tmp_path, second_env_file="./tmp/runtime.env", required=True)
    # Do NOT create tmp/runtime.env — it is absent but required

    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
          worker:
            environment:
              PKM_ENVIRONMENT: prod
          watcher:
            environment:
              PKM_ENVIRONMENT: prod
        """,
    )

    result = check_compose_channel_isolation(
        compose_path,
        "prod",
        base_compose_path=tmp_path / "docker-compose.yaml",
    )

    assert not result.ok, (
        "Expected FAIL when a required env_file is missing, but got PASS.\n"
        f"{result.summary()}"
    )
    summary = result.summary()
    assert "runtime.env" in summary, (
        f"Summary must name the missing required env_file; got:\n{summary}"
    )


def test_optional_missing_env_file_layer_uses_earlier_layer(tmp_path: Path) -> None:
    """Missing optional env_file layer is silently skipped; earlier layer wins.

    When a referenced env_file is ``required: false`` and does not exist,
    compose skips it.  The preflight must mirror this: the effective DSN comes
    from the first layer (base defaults) which is channel-correct → PASS.
    """
    _write_base_defaults(tmp_path)  # first layer: prod DSNs (channel-correct)
    _write_base_compose(tmp_path, second_env_file="./tmp/runtime.env", required=False)
    # Do NOT create tmp/runtime.env — it is absent and optional

    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              PKM_ENVIRONMENT: prod
          worker:
            environment:
              PKM_ENVIRONMENT: prod
          watcher:
            environment:
              PKM_ENVIRONMENT: prod
        """,
    )

    result = check_compose_channel_isolation(
        compose_path,
        "prod",
        base_compose_path=tmp_path / "docker-compose.yaml",
    )

    assert result.ok, (
        "Expected PASS when an optional env_file is absent and the first layer "
        f"supplies a channel-correct DSN, but got violations:\n{result.summary()}"
    )
