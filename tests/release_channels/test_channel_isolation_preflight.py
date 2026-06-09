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

Issue #1769 extends the resolution to the full per-service `env_file` chain of
the merged compose model (base + overlay): layers are read in declaration
order, later files win, `${VAR:-default}` path expressions are interpolated
the way compose does, and a layer that could win but cannot be verified
(unreadable, missing-but-required, unresolvable path expression) fails closed.

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
# Layered env_file chains (Issue #1769)
# ---------------------------------------------------------------------------

TEST_DSN = "postgresql+psycopg://app:app@db:5432/app_test"
PROD_DSN = "postgresql+psycopg://app:app@db:5432/app"

#: Mirrors the shipped docker-compose.yaml shape: every app service layers an
#: interpolated runtime env file (written by scripts/export_runtime_env.sh,
#: which includes DATABASE_URL / DB_DSN) after the committed defaults file.
BASE_COMPOSE_WITH_RUNTIME_LAYER = """\
services:
  api:
    env_file:
      - ./config/runtime.defaults.env
      - path: ${RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
  worker:
    env_file:
      - ./config/runtime.defaults.env
      - path: ${RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
  watcher:
    env_file:
      - ./config/runtime.defaults.env
      - path: ${RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
"""

#: Mirrors docker-compose.prod.yml: the overlay omits DATABASE_URL / DB_DSN
#: entirely and relies on the env_file chain for its effective DSN bindings.
PROD_LIKE_OVERLAY = """\
services:
  api:
    environment:
      API_HEALTHCHECK_URL: http://host.docker.internal:18000/healthz
"""


def _write_base_compose(
    tmp_path: Path, content: str = BASE_COMPOSE_WITH_RUNTIME_LAYER
) -> Path:
    """Write a synthetic base compose file (docker-compose.yaml) to tmp_path."""
    p = tmp_path / "docker-compose.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _write_env_layer(tmp_path: Path, dsn: str, rel: str = "tmp/runtime.env") -> Path:
    """Write a later env_file layer carrying DATABASE_URL / DB_DSN."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"DATABASE_URL={dsn}\nDB_DSN={dsn}\n", encoding="utf-8")
    return p


def test_omitted_dsn_with_wrong_channel_later_layer_fails(tmp_path: Path) -> None:
    """AC1 (#1769): a wrong-channel DSN in a later env_file layer fails closed.

    The base defaults carry the prod DSNs, but a second env_file layer
    (tmp/runtime.env) carries app_test DSNs. Compose layering makes the later
    file win, so the effective binding of the prod-like overlay crosses into
    the test channel — the preflight must reject it.
    """
    _write_base_defaults(tmp_path)  # prod DSNs
    _write_base_compose(tmp_path)
    _write_env_layer(tmp_path, TEST_DSN)
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected preflight to FAIL when a later env_file layer supplies a "
        "test-channel DSN for an omitted key on the prod channel, but it passed."
    )
    violating = {(v.service, v.field) for v in result.violations}
    for svc in ("api", "worker", "watcher"):
        assert (svc, "DATABASE_URL") in violating
        assert (svc, "DB_DSN") in violating
    # The operator must see which layer the wrong value came from.
    assert "runtime.env" in result.summary()


def test_omitted_dsn_with_correct_channel_later_layer_passes(tmp_path: Path) -> None:
    """AC2 (#1769): a correct-channel DSN in the winning layer passes."""
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path)
    _write_env_layer(tmp_path, PROD_DSN)
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert result.ok, (
        "Expected preflight to PASS when the winning env_file layer carries "
        f"the intended-channel DSN, but got:\n{result.summary()}"
    )


def test_bare_key_unset_in_winning_layer_fails_closed(tmp_path: Path) -> None:
    """A bare ``KEY`` line (no ``=``) in the winning layer fails closed.

    Compose treats a bare key in an env_file as unset/host-passthrough and
    later files win, so the prod defaults are NOT the effective binding even
    though they textually define the DSNs. The resolver must treat the bare
    key as the winning (unverifiable) binding, not keep the earlier value.
    """
    _write_base_defaults(tmp_path)  # prod DSNs
    _write_base_compose(tmp_path)
    layer = tmp_path / "tmp" / "runtime.env"
    layer.parent.mkdir(parents=True, exist_ok=True)
    layer.write_text("DATABASE_URL\nDB_DSN\n", encoding="utf-8")
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected preflight to FAIL when the winning env_file layer unsets "
        "DATABASE_URL / DB_DSN via bare-key lines, but it passed."
    )
    assert "bare key" in result.summary()
    assert "runtime.env" in result.summary()


def test_bare_key_superseded_by_later_definition_resolves(tmp_path: Path) -> None:
    """A later layer that redefines the key supersedes an earlier bare-key unset."""
    _write_base_defaults(tmp_path)  # prod DSNs
    _write_base_compose(
        tmp_path,
        """\
        services:
          api:
            env_file:
              - ./config/runtime.defaults.env
              - ./unset.env
              - ./final.env
          worker:
            env_file:
              - ./config/runtime.defaults.env
              - ./unset.env
              - ./final.env
          watcher:
            env_file:
              - ./config/runtime.defaults.env
              - ./unset.env
              - ./final.env
        """,
    )
    (tmp_path / "unset.env").write_text("DATABASE_URL\nDB_DSN\n", encoding="utf-8")
    (tmp_path / "final.env").write_text(
        f"DATABASE_URL={PROD_DSN}\nDB_DSN={PROD_DSN}\n", encoding="utf-8"
    )
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert result.ok, (
        "Expected preflight to PASS when a later layer redefines the key after "
        f"a bare-key unset, but got:\n{result.summary()}"
    )


def test_later_env_file_layer_wins_over_defaults(tmp_path: Path) -> None:
    """Declaration order matters: the later layer overrides earlier defaults.

    Here the defaults file carries a wrong-channel (test) DSN, but the later
    runtime layer corrects it back to prod. The effective binding is the later
    value, so the prod preflight must pass — proving later-wins resolution
    rather than first-match or defaults-only resolution.
    """
    _write_base_defaults(tmp_path, f"DATABASE_URL={TEST_DSN}\nDB_DSN={TEST_DSN}\n")
    _write_base_compose(tmp_path)
    _write_env_layer(tmp_path, PROD_DSN)
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert result.ok, (
        "Expected the later env_file layer to win over the defaults layer, "
        f"but got:\n{result.summary()}"
    )


def test_env_file_path_interpolation_honors_environment_variable(
    tmp_path: Path,
) -> None:
    """`${VAR:-default}` resolves from the invoking environment when set.

    RUNTIME_ENV_FILE points the second layer at an alternate file carrying a
    wrong-channel DSN; the default path does not exist. The preflight must
    follow the interpolated path, not the literal default.
    """
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path)
    _write_env_layer(tmp_path, TEST_DSN, rel="custom/alt.env")
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(
        compose_path,
        "prod",
        environ={"RUNTIME_ENV_FILE": "./custom/alt.env"},
    )

    assert not result.ok, (
        "Expected preflight to FAIL via the interpolated env_file path, "
        "but it passed."
    )
    assert "alt.env" in result.summary()


def test_dotenv_file_supplies_interpolation_default(tmp_path: Path) -> None:
    """Compose also interpolates from `.env` in the project directory."""
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path)
    _write_env_layer(tmp_path, TEST_DSN, rel="custom/alt.env")
    (tmp_path / ".env").write_text(
        "RUNTIME_ENV_FILE=./custom/alt.env\n", encoding="utf-8"
    )
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected preflight to FAIL when .env points the winning layer at a "
        "wrong-channel DSN file, but it passed."
    )
    assert "alt.env" in result.summary()


def test_unreadable_winning_env_file_layer_fails_closed(tmp_path: Path) -> None:
    """AC3 (#1769): a winning layer that exists but cannot be read fails closed.

    The layer path exists but is not readable as an env file (a directory —
    portable stand-in for a permission failure). The preflight cannot prove
    the effective binding, so it must reject and name the layer.
    """
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path)
    (tmp_path / "tmp" / "runtime.env").mkdir(parents=True)  # exists, unreadable
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected fail-closed rejection for an unreadable winning env_file "
        "layer, but the preflight passed."
    )
    summary = result.summary()
    assert "runtime.env" in summary
    violating = {(v.service, v.field) for v in result.violations}
    assert ("api", "DATABASE_URL") in violating


def test_missing_required_env_file_layer_fails_closed(tmp_path: Path) -> None:
    """A required env_file layer absent at preflight time fails closed.

    Compose refuses to start a service whose required env_file is missing, and
    the preflight cannot verify what the file would have contained — it must
    not silently assume absence.
    """
    _write_base_defaults(tmp_path)
    _write_base_compose(
        tmp_path,
        """\
        services:
          api:
            env_file:
              - ./config/runtime.defaults.env
              - ./config/runtime.local.env
        """,
    )
    compose_path = _write_compose(
        tmp_path,
        """\
        services:
          api:
            environment:
              API_HEALTHCHECK_URL: http://host.docker.internal:18000/healthz
        """,
    )

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected fail-closed rejection for a missing required env_file "
        "layer, but the preflight passed."
    )
    assert "runtime.local.env" in result.summary()


def test_missing_optional_env_file_layer_is_skipped(tmp_path: Path) -> None:
    """A `required: false` layer absent at preflight time contributes nothing.

    This matches compose semantics (missing optional env_file is skipped); the
    effective binding resolves from the remaining layers — here the prod
    defaults — so the prod channel passes.
    """
    _write_base_defaults(tmp_path)
    _write_base_compose(tmp_path)  # optional runtime layer not written
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert result.ok, (
        "Expected preflight to PASS when the optional runtime layer is absent "
        f"and defaults bind the intended channel, but got:\n{result.summary()}"
    )


def test_unsupported_env_file_path_expression_fails_closed(tmp_path: Path) -> None:
    """Path expressions the preflight cannot interpolate fail closed."""
    _write_base_defaults(tmp_path)
    _write_base_compose(
        tmp_path,
        """\
        services:
          api:
            env_file:
              - ./config/runtime.defaults.env
              - path: ${RUNTIME_ENV_FILE:?must be set}
                required: false
        """,
    )
    compose_path = _write_compose(tmp_path, PROD_LIKE_OVERLAY)

    result = check_compose_channel_isolation(compose_path, "prod", environ={})

    assert not result.ok, (
        "Expected fail-closed rejection for an unresolvable env_file path "
        "expression, but the preflight passed."
    )


def test_real_prod_compose_fails_when_runtime_layer_carries_test_dsn(
    tmp_path: Path,
) -> None:
    """The real merged model (docker-compose.yaml + prod overlay) is resolved.

    Pointing WATCHER_RUNTIME_ENV_FILE at a layer carrying app_test DSNs must
    fail the prod preflight: this is exactly the escape found in the codex
    review of PR #1766.
    """
    layer = _write_env_layer(tmp_path, TEST_DSN, rel="runtime.env")

    result = check_compose_channel_isolation(
        PROD_COMPOSE,
        "prod",
        environ={"WATCHER_RUNTIME_ENV_FILE": str(layer)},
    )

    assert not result.ok, (
        "Expected the real prod compose to FAIL when the runtime env layer "
        "carries a test-channel DSN, but it passed."
    )
    violating = {(v.service, v.field) for v in result.violations}
    for svc in ("api", "worker", "watcher"):
        assert (svc, "DATABASE_URL") in violating
        assert (svc, "DB_DSN") in violating


def test_real_prod_compose_passes_when_runtime_layer_carries_prod_dsn(
    tmp_path: Path,
) -> None:
    """Companion: a prod-channel runtime layer keeps the real prod compose green."""
    layer = _write_env_layer(tmp_path, PROD_DSN, rel="runtime.env")

    result = check_compose_channel_isolation(
        PROD_COMPOSE,
        "prod",
        environ={"WATCHER_RUNTIME_ENV_FILE": str(layer)},
    )

    assert result.ok, (
        "Expected the real prod compose to PASS with a prod-channel runtime "
        f"layer, but got:\n{result.summary()}"
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
