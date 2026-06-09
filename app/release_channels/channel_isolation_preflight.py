"""Channel-isolation preflight guard (Issues #1627, #1655).

Fail-closed check that a compose overlay's effective env bindings
(PKM_ENVIRONMENT, DATABASE_URL / DB_DSN, vault) match the *intended* channel
before any test/prod stack start or before promote-to-test / execute-promotion
proceed.

Policy authority: docs/RELEASE_CHANNELS/README.md §Invariants.

Design constraints:
- Read-only: this module NEVER mutates operator files.
- No Docker, no network: parses compose YAML plus the base env_file only.
- Covers both committed and working-tree compose drift.
- Must cover all services that carry channel env vars (api, worker, watcher).

Omitted-binding semantics (Issue #1655): the base compose file feeds every app
service from ``config/runtime.defaults.env``, which carries the prod ``app``
DSNs. When an overlay omits ``DATABASE_URL`` / ``DB_DSN`` for a
channel-critical service — by dropping the keys or the whole service block —
compose layering silently falls back to those base defaults. The preflight
therefore resolves the *effective* binding (overlay value, else base default)
and fails closed when it lands on another channel, or when the base defaults
cannot be read at all.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Channel specifications
# ---------------------------------------------------------------------------

#: Expected bindings for each supported channel.
CHANNEL_SPECS: dict[str, dict[str, Any]] = {
    "test": {
        "pkm_environment": "test",
        # DB name fragment that must appear in DATABASE_URL / DB_DSN
        "db_name_fragment": "app_test",
        # compose project name
        "compose_project": "pkm-test",
        # vault fragment that must NOT be the bare prod "vault/" (no suffix)
        "vault_fragment_banned": re.compile(r'(?<![/\w])vault(?![-_/])'),
    },
    "prod": {
        "pkm_environment": "prod",
        "db_name_fragment": "app",           # bare "app" DB; not app_test / app_dev
        "db_name_fragment_banned": re.compile(r"app_test|app_dev"),
        "compose_project": "pkm-prod",
        "vault_fragment_banned": re.compile(r"vault-test|vault-dev"),
    },
}

#: Services inside a compose overlay that carry channel env vars.
CHANNEL_SERVICES = ("api", "worker", "watcher")

#: Env keys whose effective value decides which channel's DB a service writes to.
CHANNEL_CRITICAL_DSN_KEYS = ("DATABASE_URL", "DB_DSN")

#: Base compose env_file that supplies default DSNs to every app service,
#: relative to the compose file directory (see docker-compose.yaml `env_file`).
BASE_ENV_DEFAULTS_REL = Path("config") / "runtime.defaults.env"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BindingViolation:
    service: str
    field: str
    expected: str
    actual: str | None

    def __str__(self) -> str:
        actual_repr = repr(self.actual) if self.actual is not None else "(not set)"
        return (
            f"  Service '{self.service}': {self.field} — "
            f"expected {self.expected!r}, got {actual_repr}"
        )


@dataclass
class PreflightResult:
    channel: str
    compose_path: str
    violations: list[BindingViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.ok:
            return (
                f"PASS  channel-isolation preflight: {self.channel!r} channel "
                f"bindings verified in {self.compose_path}"
            )
        lines = [
            f"FAIL  channel-isolation preflight: {len(self.violations)} violation(s) "
            f"in {self.compose_path} for channel {self.channel!r}",
            "",
            "Violations:",
        ]
        lines += [str(v) for v in self.violations]
        lines += [
            "",
            "Action required: correct the compose overlay to match the intended channel.",
            "This check is read-only — it will not modify operator files.",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# YAML loader that handles compose !override / !reset tags
# ---------------------------------------------------------------------------

def _make_compose_loader() -> type[yaml.SafeLoader]:
    class _ComposeLoader(yaml.SafeLoader):
        pass

    def _passthrough(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _ComposeLoader.add_constructor("!override", _passthrough)
    _ComposeLoader.add_constructor("!reset", _passthrough)
    return _ComposeLoader


def _load_compose(path: Path) -> dict[str, Any]:
    """Load a docker-compose YAML file tolerating !override / !reset tags."""
    loader = _make_compose_loader()
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}


def _load_base_env_defaults(
    compose_path: Path,
    base_defaults_path: Path | None = None,
) -> dict[str, str] | None:
    """Load the base compose env_file defaults that back omitted overlay keys.

    Returns the KEY=VALUE mapping from ``config/runtime.defaults.env`` next to
    the compose overlay (or *base_defaults_path* when given), or ``None`` when
    the file cannot be read. ``None`` means omitted channel-critical bindings
    are unverifiable and must fail closed.
    """
    path = base_defaults_path or (compose_path.resolve().parent / BASE_ENV_DEFAULTS_REL)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    defaults: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            defaults[key.strip()] = value.strip()
    return defaults


def _service_env(service_dict: dict[str, Any]) -> dict[str, str | None]:
    """Return the environment mapping for a single compose service dict."""
    raw = service_dict.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): (str(v) if v is not None else None) for k, v in raw.items()}
    # list form: ["KEY=val", "KEY2"]
    result: dict[str, str | None] = {}
    for entry in raw:
        key, sep, value = str(entry).partition("=")
        result[key] = value if sep else None
    return result


# ---------------------------------------------------------------------------
# Core preflight logic
# ---------------------------------------------------------------------------

def check_compose_channel_isolation(
    compose_path: Path,
    channel: str,
    base_defaults_path: Path | None = None,
) -> PreflightResult:
    """Check that *compose_path* overlay binds correctly for *channel*.

    Reads the overlay YAML from disk (working-tree copy) so uncommitted drift
    is caught immediately. DSN bindings are checked against the *effective*
    value after compose layering: the overlay value when declared, else the
    base default from ``config/runtime.defaults.env`` (or
    *base_defaults_path*). Omitted bindings whose fallback resolves to another
    channel — or cannot be resolved at all — are violations (Issue #1655).

    Returns a :class:`PreflightResult`; call ``.ok`` to test pass/fail.
    Raises ``ValueError`` if *channel* is unknown.
    """
    if channel not in CHANNEL_SPECS:
        raise ValueError(
            f"Unknown channel {channel!r}. Supported: {sorted(CHANNEL_SPECS)}"
        )

    spec = CHANNEL_SPECS[channel]
    compose_data = _load_compose(compose_path)
    services = compose_data.get("services") or {}
    base_defaults = _load_base_env_defaults(compose_path, base_defaults_path)

    result = PreflightResult(channel=channel, compose_path=str(compose_path))

    for svc_name in CHANNEL_SERVICES:
        # Channel-critical services are checked even when absent from the
        # overlay: compose layering still starts them from the base file with
        # the base default DSNs.
        svc = services.get(svc_name) or {}
        env = _service_env(svc)

        _check_pkm_environment(result, svc_name, env, spec)
        _check_db_dsn(result, svc_name, env, spec, base_defaults)

    return result


def _check_pkm_environment(
    result: PreflightResult,
    svc_name: str,
    env: dict[str, str | None],
    spec: dict[str, Any],
) -> None:
    """Validate PKM_ENVIRONMENT matches the expected channel."""
    pkm_env = env.get("PKM_ENVIRONMENT")
    if pkm_env is None:
        # Not set in this overlay — base compose may supply it; skip.
        return
    expected = spec["pkm_environment"]
    if str(pkm_env).strip().lower() != expected:
        result.violations.append(
            BindingViolation(
                service=svc_name,
                field="PKM_ENVIRONMENT",
                expected=expected,
                actual=pkm_env,
            )
        )


def _dsn_violation(dsn: str, spec: dict[str, Any]) -> str | None:
    """Return the expected-binding description if *dsn* violates *spec*, else None."""
    db_fragment = spec.get("db_name_fragment")
    if db_fragment and db_fragment not in dsn:
        return f"DSN containing {db_fragment!r}"

    # For prod: additionally ban test/dev fragments in DSN
    banned_pattern = spec.get("db_name_fragment_banned")
    if banned_pattern and banned_pattern.search(dsn):
        return "prod DSN (not app_test/app_dev)"

    return None


def _check_db_dsn(
    result: PreflightResult,
    svc_name: str,
    env: dict[str, str | None],
    spec: dict[str, Any],
    base_defaults: dict[str, str] | None,
) -> None:
    """Validate effective DATABASE_URL / DB_DSN bindings match the channel.

    The effective binding is the overlay value when declared, else the base
    compose env_file default. Fail closed (Issue #1655): an omitted binding is
    a violation when its fallback resolves to another channel, and also when
    the base defaults cannot be read — an unverifiable binding is never safe.
    """
    db_fragment = spec.get("db_name_fragment")
    for key in CHANNEL_CRITICAL_DSN_KEYS:
        dsn = env.get(key)
        if dsn is not None:
            expected_on_violation = _dsn_violation(dsn, spec)
            if expected_on_violation:
                result.violations.append(
                    BindingViolation(
                        service=svc_name,
                        field=key,
                        expected=expected_on_violation,
                        actual=dsn,
                    )
                )
            continue

        # Key omitted from the overlay (or whole service absent): compose
        # layering falls back to the base env_file default.
        if base_defaults is None:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay, "
                        "or a resolvable channel-correct base default"
                    ),
                    actual=(
                        "omitted from overlay; base defaults "
                        f"({BASE_ENV_DEFAULTS_REL}) unreadable — effective "
                        "binding unverifiable"
                    ),
                )
            )
            continue

        fallback = base_defaults.get(key)
        if fallback is None:
            # No overlay value and no base default: the service would start
            # without this binding at all. Treat as unverifiable — fail closed.
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay "
                        "or via base defaults"
                    ),
                    actual="omitted from overlay and absent from base defaults",
                )
            )
            continue

        expected_on_violation = _dsn_violation(fallback, spec)
        if expected_on_violation:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=f"{expected_on_violation} (explicit in the overlay)",
                    actual=(
                        f"omitted from overlay; falls back to base default {fallback!r}"
                    ),
                )
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli_main(argv: list[str] | None = None) -> int:
    """Minimal CLI: check_channel_isolation <compose-path> <channel>

    Exits 0 on pass, 1 on violation, 2 on usage error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Channel-isolation preflight: fail-closed check that a compose "
            "overlay's effective env bindings match the intended channel."
        )
    )
    parser.add_argument(
        "compose_path",
        help="Path to the compose overlay file (e.g. docker-compose.test.yml)",
    )
    parser.add_argument(
        "channel",
        choices=sorted(CHANNEL_SPECS),
        help="Intended channel (test | prod)",
    )
    args = parser.parse_args(argv)

    compose_path = Path(args.compose_path)
    if not compose_path.exists():
        print(f"ERROR: compose file not found: {compose_path}", file=sys.stderr)
        return 2

    result = check_compose_channel_isolation(compose_path, args.channel)
    print(result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli_main())
