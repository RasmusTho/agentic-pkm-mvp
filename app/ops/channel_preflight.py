"""Fail-loud channel-environment preflight (issue #1997 F2).

The 2026-06-14 v6.1 Wave 1 promotion was almost entirely harness pain: the
test channel was configured by *ambient / CWD-relative defaults*
(``INDEX_OUTBOX_PATH`` unset → CWD-relative, ``TEST_VAULT_ROOT=$(PWD)/...``,
``db:5432`` reached from the host, ``tmp/`` vs ``tmp-test/``). Each only works
in the exact happy-path context and silently targets the wrong thing
otherwise, producing red-for-the-wrong-reason signals.

This module is the whole-channel analogue of the #1991 vault preflight
(:mod:`app.vault.promotion_preflight`): a frozen-dataclass result plus a pure
function that validates the *effective runtime environment* a test-channel
entrypoint is about to run with, and **refuses to run on mismatch** instead of
falling back to an ambient default. It names the offending variable.

Scope boundary — two complementary preflights:

* :mod:`app.release_channels.channel_isolation_preflight` validates the *static
  compose overlay YAML* (what the containers will bind to).
* This module validates the *live process environment* the host-side
  entrypoints (``promote-to-test``, ``make test-*``, the in-process UAT,
  ``scripts/bootstrap_test_channel.sh``) run with.

It is harness-only: it reads env and reports; it mutates nothing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

# ---------------------------------------------------------------------------
# Channel specification
# ---------------------------------------------------------------------------

#: Canonical host-reachable Postgres port for the test channel (published by
#: ``docker-compose.test.yml`` as ``15434:5432``). The in-container DSN host
#: ``db:5432`` is unreachable from the host and is a misconfig symptom.
TEST_DB_HOST_PORT = "15434"

#: Channel env keys whose effective value decides which channel a host-side
#: entrypoint writes to. Kept aligned with docker-compose.test.yml.
_CHANNEL_ENV_KEYS = ("PKM_ENVIRONMENT", "PKM_CHANNEL", "ENVIRONMENT", "CHANNEL")

_SUPPORTED_CHANNELS = ("test",)


@dataclass(frozen=True)
class ChannelEnvViolation:
    """One offending env binding: which var, what was expected, what was seen."""

    var: str
    expected: str
    actual: str | None
    reason: str

    def __str__(self) -> str:
        actual_repr = repr(self.actual) if self.actual is not None else "(not set)"
        return f"  {self.var}: expected {self.expected}; got {actual_repr} — {self.reason}"


@dataclass(frozen=True)
class ChannelEnvPreflight:
    """Result of checking whether the runtime env is channel-correct.

    ``blocking`` is True when a test-channel entrypoint must refuse to run
    against this environment. ``violations`` always names the offending var(s).
    """

    channel: str
    context: str
    violations: tuple[ChannelEnvViolation, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def blocking(self) -> bool:
        return bool(self.violations)

    @property
    def offending_vars(self) -> tuple[str, ...]:
        # Preserve order, de-duplicate.
        seen: dict[str, None] = {}
        for v in self.violations:
            seen.setdefault(v.var, None)
        return tuple(seen)

    def format_report(self) -> str:
        if self.ok:
            return (
                f"PASS  channel-env preflight: {self.channel!r} channel "
                f"({self.context}) env is consistent and channel-correct"
            )
        lines = [
            f"FAIL  channel-env preflight: {len(self.violations)} violation(s) "
            f"for {self.channel!r} channel ({self.context} context)",
            "",
            "Offending bindings:",
            *[str(v) for v in self.violations],
            "",
            "Refusing to run on an inconsistent/ambient channel configuration. "
            "Fix the named variable(s) — do not fall back to a CWD-relative or "
            "in-container default. The canonical bring-up is "
            "`scripts/bootstrap_test_channel.sh` (issue #1997).",
        ]
        return "\n".join(lines)


class ChannelPreflightError(RuntimeError):
    """Raised by :func:`raise_if_blocking` when the channel env is inconsistent."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_absolute(path: str) -> bool:
    # Treat a path as absolute if it is absolute on either POSIX or Windows so
    # the check is stable regardless of the host the harness runs on.
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def _dsn_host(dsn: str) -> str | None:
    """Extract the network host from a SQLAlchemy/psycopg DSN, if present."""
    match = re.search(r"@([^/?\s]+)", dsn)
    if not match:
        return None
    authority = match.group(1)
    # authority may be host:port
    host = authority.rsplit(":", 1)[0] if ":" in authority else authority
    return host or None


def _resolve_channel(environ: Mapping[str, str], explicit: str | None) -> tuple[str | None, str | None]:
    """Return (channel, raw_env_value). channel is None if underivable."""
    raw = None
    for key in _CHANNEL_ENV_KEYS:
        raw = _clean(environ.get(key))
        if raw is not None:
            break
    if explicit is not None:
        return explicit.strip().lower(), raw
    if raw is None:
        return None, None
    return raw.lower(), raw


# ---------------------------------------------------------------------------
# Core preflight
# ---------------------------------------------------------------------------

def channel_env_preflight(
    environ: Mapping[str, str] | None = None,
    *,
    channel: str | None = None,
    context: str = "host",
) -> ChannelEnvPreflight:
    """Validate the effective env is mutually consistent and channel-correct.

    Args:
        environ: env mapping to validate (defaults to ``os.environ``).
        channel: the *intended* channel; when ``None`` it is derived from
            ``PKM_ENVIRONMENT``/``PKM_CHANNEL`` and an underivable channel is a
            blocking violation (we never validate against an ambient default).
        context: ``"host"`` (the default; entrypoints run host-side, so the DSN
            must be host-reachable) or ``"container"`` (the in-container
            ``db:5432`` DSN is correct).

    Returns a :class:`ChannelEnvPreflight`; ``blocking`` True means the
    entrypoint must abort. Only the ``test`` channel is supported here — the
    operator/prod channel is never bootstrapped by this harness.
    """
    env = os.environ if environ is None else environ
    resolved, raw_channel = _resolve_channel(env, channel)
    violations: list[ChannelEnvViolation] = []

    if resolved is None:
        violations.append(
            ChannelEnvViolation(
                var="PKM_ENVIRONMENT",
                expected="one of " + ", ".join(_SUPPORTED_CHANNELS),
                actual=None,
                reason="channel is unset; refusing to assume an ambient default",
            )
        )
        return ChannelEnvPreflight(channel="(unset)", context=context, violations=tuple(violations))

    if resolved not in _SUPPORTED_CHANNELS:
        violations.append(
            ChannelEnvViolation(
                var="PKM_ENVIRONMENT",
                expected="one of " + ", ".join(_SUPPORTED_CHANNELS),
                actual=raw_channel or resolved,
                reason="this harness only bootstraps the test channel; never the operator/prod channel",
            )
        )
        return ChannelEnvPreflight(channel=resolved, context=context, violations=tuple(violations))

    # From here: the intended channel is "test".
    _check_pkm_environment(env, raw_channel, violations)
    _check_vault_root(env, violations)
    _check_index_outbox(env, violations)
    _check_dsn(env, context, violations)
    _check_heartbeats(env, violations)

    return ChannelEnvPreflight(channel="test", context=context, violations=tuple(violations))


def _check_pkm_environment(
    env: Mapping[str, str], raw_channel: str | None, violations: list[ChannelEnvViolation]
) -> None:
    pkm_env = _clean(env.get("PKM_ENVIRONMENT"))
    if pkm_env is None:
        violations.append(
            ChannelEnvViolation(
                var="PKM_ENVIRONMENT",
                expected="test",
                actual=None,
                reason="must be explicitly 'test' for the test channel (no ambient default)",
            )
        )
        return
    if pkm_env.strip().lower() != "test":
        violations.append(
            ChannelEnvViolation(
                var="PKM_ENVIRONMENT",
                expected="test",
                actual=pkm_env,
                reason="intended channel is test but PKM_ENVIRONMENT disagrees",
            )
        )


def _check_vault_root(env: Mapping[str, str], violations: list[ChannelEnvViolation]) -> None:
    vault_root = _clean(env.get("VAULT_ROOT"))
    if vault_root is None:
        violations.append(
            ChannelEnvViolation(
                var="VAULT_ROOT",
                expected="an absolute operator-configured test-vault path",
                actual=None,
                reason="unset; refusing the ambient ./vault fallback",
            )
        )
    elif not _is_absolute(vault_root):
        violations.append(
            ChannelEnvViolation(
                var="VAULT_ROOT",
                expected="an absolute path",
                actual=vault_root,
                reason="relative paths resolve against CWD and diverge between callers",
            )
        )
    # The vault that backs the test channel is operator-configured (one of the
    # operator's own Obsidian vaults). Its name is intentionally not pinned here:
    # isolation is the operator's responsibility (point test at a non-prod vault),
    # so this preflight only enforces that the path is absolute and consistent
    # with VAULT_ROOT_TEST — never that it matches a hardcoded ``vault-test`` name.

    vault_root_test = _clean(env.get("VAULT_ROOT_TEST"))
    if vault_root_test is None:
        violations.append(
            ChannelEnvViolation(
                var="VAULT_ROOT_TEST",
                expected="set, matching VAULT_ROOT",
                actual=None,
                reason="resolve_vault_root(environment='test') reads VAULT_ROOT_TEST; leaving it unset diverges from VAULT_ROOT",
            )
        )
    elif not _is_absolute(vault_root_test):
        violations.append(
            ChannelEnvViolation(
                var="VAULT_ROOT_TEST",
                expected="an absolute path",
                actual=vault_root_test,
                reason="relative paths resolve against CWD and diverge between callers",
            )
        )
    elif vault_root is not None and os.path.normpath(vault_root_test) != os.path.normpath(vault_root):
        violations.append(
            ChannelEnvViolation(
                var="VAULT_ROOT_TEST",
                expected=f"equal to VAULT_ROOT ({vault_root})",
                actual=vault_root_test,
                reason="VAULT_ROOT and VAULT_ROOT_TEST disagree; the channel would bind two different vaults",
            )
        )


def _check_index_outbox(env: Mapping[str, str], violations: list[ChannelEnvViolation]) -> None:
    outbox = _clean(env.get("INDEX_OUTBOX_PATH"))
    if outbox is None:
        violations.append(
            ChannelEnvViolation(
                var="INDEX_OUTBOX_PATH",
                expected="an absolute …/tmp-test/index-outbox.jsonl path",
                actual=None,
                reason="unset → CWD-relative default; watcher and consumer silently diverge",
            )
        )
        return
    if not _is_absolute(outbox):
        violations.append(
            ChannelEnvViolation(
                var="INDEX_OUTBOX_PATH",
                expected="an absolute path",
                actual=outbox,
                reason="relative outbox resolves against CWD; watcher and consumer diverge",
            )
        )
    if "tmp-test" not in outbox:
        violations.append(
            ChannelEnvViolation(
                var="INDEX_OUTBOX_PATH",
                expected="a tmp-test/ path",
                actual=outbox,
                reason="test-channel artifacts live under tmp-test/, not tmp/",
            )
        )


def _check_dsn(env: Mapping[str, str], context: str, violations: list[ChannelEnvViolation]) -> None:
    database_url = _clean(env.get("DATABASE_URL"))
    db_dsn = _clean(env.get("DB_DSN"))
    if database_url is None and db_dsn is None:
        violations.append(
            ChannelEnvViolation(
                var="DATABASE_URL",
                expected="a test DSN (…@127.0.0.1:15434/app_test)",
                actual=None,
                reason="neither DATABASE_URL nor DB_DSN is set",
            )
        )
        return

    for var, dsn in (("DATABASE_URL", database_url), ("DB_DSN", db_dsn)):
        if dsn is None:
            continue
        if "app_test" not in dsn:
            violations.append(
                ChannelEnvViolation(
                    var=var,
                    expected="DSN containing 'app_test'",
                    actual=dsn,
                    reason="test channel must target the app_test database",
                )
            )
        if context == "host":
            host = _dsn_host(dsn)
            if host == "db":
                violations.append(
                    ChannelEnvViolation(
                        var=var,
                        expected=f"host-reachable 127.0.0.1:{TEST_DB_HOST_PORT}",
                        actual=dsn,
                        reason="'@db:5432' is the in-container address and is unreachable from the host",
                    )
                )
            elif host is not None and f":{TEST_DB_HOST_PORT}" not in dsn:
                violations.append(
                    ChannelEnvViolation(
                        var=var,
                        expected=f"published test port {TEST_DB_HOST_PORT}",
                        actual=dsn,
                        reason=f"host-side test DSN must use the published port {TEST_DB_HOST_PORT}",
                    )
                )

    if database_url is not None and db_dsn is not None and database_url != db_dsn:
        violations.append(
            ChannelEnvViolation(
                var="DB_DSN",
                expected=f"equal to DATABASE_URL ({database_url})",
                actual=db_dsn,
                reason="DATABASE_URL and DB_DSN disagree; the channel would split reads/writes across DBs",
            )
        )


def _check_heartbeats(env: Mapping[str, str], violations: list[ChannelEnvViolation]) -> None:
    for var in ("WORKER_HEARTBEAT_PATH", "WATCHER_HEARTBEAT_PATH"):
        value = _clean(env.get(var))
        if value is None:
            # Heartbeat paths are supplied by compose for the container; a host
            # entrypoint that leaves them unset inherits the channel-correct
            # compose value, so an unset host var is not itself a violation.
            continue
        if "tmp-test" not in value:
            violations.append(
                ChannelEnvViolation(
                    var=var,
                    expected="a tmp-test/ path",
                    actual=value,
                    reason="test-channel heartbeats live under tmp-test/, not tmp/",
                )
            )


def raise_if_blocking(result: ChannelEnvPreflight) -> ChannelEnvPreflight:
    """Raise :class:`ChannelPreflightError` (naming the vars) when blocking."""
    if result.blocking:
        raise ChannelPreflightError(result.format_report())
    return result


__all__ = [
    "TEST_DB_HOST_PORT",
    "ChannelEnvViolation",
    "ChannelEnvPreflight",
    "ChannelPreflightError",
    "channel_env_preflight",
    "raise_if_blocking",
]
