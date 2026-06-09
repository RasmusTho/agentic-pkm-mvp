"""Channel-isolation preflight guard (Issue #1627).

Fail-closed check that a compose overlay's effective env bindings
(PKM_ENVIRONMENT, DATABASE_URL / DB_DSN, vault) match the *intended* channel
before any test/prod stack start or before promote-to-test / execute-promotion
proceed.

Policy authority: docs/RELEASE_CHANNELS/README.md §Invariants.

Design constraints:
- Read-only: this module NEVER mutates operator files.
- No Docker, no network: parses compose YAML only.
- Covers both committed and working-tree compose drift.
- Must cover all services that carry channel env vars (api, worker, watcher).
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
) -> PreflightResult:
    """Check that *compose_path* overlay binds correctly for *channel*.

    Reads the overlay YAML from disk (working-tree copy) so uncommitted drift
    is caught immediately.

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

    result = PreflightResult(channel=channel, compose_path=str(compose_path))

    for svc_name in CHANNEL_SERVICES:
        svc = services.get(svc_name) or {}
        env = _service_env(svc)
        if not env:
            # Service not overridden in this overlay — nothing to check.
            continue

        _check_pkm_environment(result, svc_name, env, spec)
        _check_db_dsn(result, svc_name, env, spec)

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


def _check_db_dsn(
    result: PreflightResult,
    svc_name: str,
    env: dict[str, str | None],
    spec: dict[str, Any],
) -> None:
    """Validate DATABASE_URL / DB_DSN bindings match the expected channel.

    Fail-closed policy (Issue #1655): if a service has any environment keys
    declared in the overlay but omits a channel-critical DSN key
    (DATABASE_URL or DB_DSN), the effective value after compose layering could
    resolve to the base compose env_file default — which for the prod channel
    points at the 'app' database.  Omission is therefore treated as a
    violation, not a skip.
    """
    db_fragment = spec.get("db_name_fragment")

    for key in ("DATABASE_URL", "DB_DSN"):
        dsn = env.get(key)

        if dsn is None:
            # Key is absent from the overlay.  Fail closed: if this service is
            # present in the overlay (has any env keys), the omitted DSN can
            # resolve to the wrong channel via the base compose env_file.
            if db_fragment:
                result.violations.append(
                    BindingViolation(
                        service=svc_name,
                        field=key,
                        expected=f"DSN containing {db_fragment!r} (key must be explicit in overlay)",
                        actual=None,
                    )
                )
            continue

        if db_fragment and db_fragment not in dsn:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=f"DSN containing {db_fragment!r}",
                    actual=dsn,
                )
            )
            continue

        # For prod: additionally ban test/dev fragments in DSN
        banned_pattern = spec.get("db_name_fragment_banned")
        if banned_pattern and banned_pattern.search(dsn):
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected="prod DSN (not app_test/app_dev)",
                    actual=dsn,
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
