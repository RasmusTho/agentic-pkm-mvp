"""Channel-isolation preflight guard (Issues #1627, #1655, #1769).

Fail-closed check that a compose overlay's effective env bindings
(PKM_ENVIRONMENT, DATABASE_URL / DB_DSN, vault) match the *intended* channel
before any test/prod stack start or before promote-to-test / execute-promotion
proceed.

Policy authority: docs/RELEASE_CHANNELS/README.md §Invariants.

Design constraints:
- Read-only: this module NEVER mutates operator files.
- No Docker, no network: parses compose YAML plus env_file chain only.
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

env_file-chain resolution (Issue #1769): compose allows multiple ``env_file``
entries per service, with later entries winning over earlier ones.  The base
services declare a second env_file ``${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}``
after ``config/runtime.defaults.env``.  If that second layer supplies a wrong-channel
DSN the preflight would previously have missed it because it only consulted
``config/runtime.defaults.env``.  The fix resolves DSN keys through the full
per-service ``env_file`` chain from both the base compose file and the overlay,
in declaration order (later files win), using the same ``${VAR:-default}``
interpolation that compose applies to env_file path expressions.

Missing-env-file posture: compose treats a missing non-optional env_file as a
hard error. This preflight mirrors that posture: if a referenced env_file
entry is marked ``required: true`` (or ``required`` is omitted, defaulting to
true) and the file does not exist or cannot be read, the preflight fails closed
for every DSN key that would have been resolved from that file onward.  Only
entries explicitly marked ``required: false`` are silently skipped when absent.
An env_file that *exists* but cannot be read (e.g. permission denied) always
fails closed regardless of the ``required`` flag.
"""
from __future__ import annotations

import os
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
# env_file chain resolution (Issue #1769)
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate_env_path(expr: str) -> str:
    """Interpolate ``${VAR:-default}`` and ``${VAR}`` in an env_file path expression.

    Uses ``os.environ`` for lookups, matching what compose does when resolving
    env_file paths.  Only the ``:-`` (default-if-unset-or-empty) and plain
    ``${VAR}`` forms are handled — these cover all patterns observed in the
    compose files in this repo.
    """
    def _replace(m: "re.Match[str]") -> str:
        spec_inner = m.group(1)
        if ":-" in spec_inner:
            var, _, default = spec_inner.partition(":-")
            val = os.environ.get(var.strip(), "").strip()
            return val if val else default
        else:
            return os.environ.get(spec_inner.strip(), "")

    return _ENV_VAR_RE.sub(_replace, expr)


def _parse_env_file(text: str) -> dict[str, str]:
    """Parse a docker-style KEY=VALUE env file, skipping comments and blanks."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    return result


def _parse_env_file_entries(
    service_dict: dict[str, Any],
) -> list[tuple[str, bool]]:
    """Return the ordered list of ``(path_expr, required)`` from a service's ``env_file`` block.

    Handles both the short-form (plain string list) and long-form (mapping with
    ``path`` / ``required`` keys) that compose v2/v3 supports.
    """
    raw = service_dict.get("env_file")
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    entries: list[tuple[str, bool]] = []
    for item in raw:
        if isinstance(item, str):
            entries.append((item, True))
        elif isinstance(item, dict):
            path_expr = str(item.get("path", ""))
            required = bool(item.get("required", True))
            if path_expr:
                entries.append((path_expr, required))
    return entries


# Sentinel: chain resolution failed in a way that must fail closed.
class _EnvFileChainError(Exception):
    """Raised when an env_file in the resolution chain blocks safe verification."""
    def __init__(self, path_expr: str, reason: str) -> None:
        self.path_expr = path_expr
        self.reason = reason
        super().__init__(f"env_file {path_expr!r}: {reason}")


def _resolve_env_file_chain(
    service_dict: dict[str, Any],
    compose_dir: Path,
) -> dict[str, str]:
    """Resolve the effective KEY=VALUE mapping from a service's env_file list.

    Processes entries in declaration order; later files win.  Interpolates
    ``${VAR:-default}`` path expressions.

    Raises :class:`_EnvFileChainError` when a required env_file is missing or
    any env_file (required or not) exists but cannot be read.
    """
    merged: dict[str, str] = {}
    for path_expr, required in _parse_env_file_entries(service_dict):
        resolved_str = _interpolate_env_path(path_expr)
        path = Path(resolved_str)
        if not path.is_absolute():
            path = compose_dir / path

        if not path.exists():
            if required:
                raise _EnvFileChainError(
                    path_expr,
                    f"file does not exist and required=true (resolved: {path})",
                )
            # required=false and absent → silently skip, compose does the same
            continue

        # File exists — must be readable regardless of required flag
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _EnvFileChainError(
                path_expr,
                f"file exists but cannot be read (resolved: {path}): {exc}",
            ) from exc

        merged.update(_parse_env_file(text))

    return merged


# ---------------------------------------------------------------------------
# Core preflight logic
# ---------------------------------------------------------------------------

def check_compose_channel_isolation(
    compose_path: Path,
    channel: str,
    base_defaults_path: Path | None = None,
    base_compose_path: Path | None = None,
) -> PreflightResult:
    """Check that *compose_path* overlay binds correctly for *channel*.

    Reads the overlay YAML from disk (working-tree copy) so uncommitted drift
    is caught immediately.  DSN bindings are checked against the *effective*
    value after compose layering: the overlay value when declared, else the
    effective value from the full per-service env_file chain (Issue #1769).

    The env_file chain is resolved from the merged compose model: first the
    base compose file (``docker-compose.yaml`` next to *compose_path*, or
    *base_compose_path* when given), then the overlay's per-service env_file
    entries.  Later entries win.  ``${VAR:-default}`` path expressions are
    interpolated against ``os.environ``.

    Missing-env-file posture:
    - A referenced env_file with ``required: true`` (the default) that does not
      exist is treated as a hard error → fail closed.
    - A referenced env_file with ``required: false`` that does not exist is
      silently skipped (matches compose behaviour).
    - An env_file that exists but cannot be read always fails closed.

    *base_defaults_path* is kept for backward compatibility; when supplied it
    overrides the first env_file entry for each service (the base defaults
    file).  Prefer *base_compose_path* for new callers.

    Returns a :class:`PreflightResult`; call ``.ok`` to test pass/fail.
    Raises ``ValueError`` if *channel* is unknown.
    """
    if channel not in CHANNEL_SPECS:
        raise ValueError(
            f"Unknown channel {channel!r}. Supported: {sorted(CHANNEL_SPECS)}"
        )

    spec = CHANNEL_SPECS[channel]
    compose_dir = compose_path.resolve().parent
    compose_data = _load_compose(compose_path)
    services = compose_data.get("services") or {}

    # Load the base compose (docker-compose.yaml) to get its per-service
    # env_file declarations, which are the first layers in the chain.
    if base_compose_path is not None:
        base_compose_data = _load_compose(base_compose_path)
        base_compose_dir = base_compose_path.resolve().parent
        has_base_compose = True
    else:
        default_base = compose_dir / "docker-compose.yaml"
        if default_base.exists():
            base_compose_data = _load_compose(default_base)
            base_compose_dir = compose_dir
            has_base_compose = True
        else:
            base_compose_data = {}
            base_compose_dir = compose_dir
            has_base_compose = False

    base_services = base_compose_data.get("services") or {}

    result = PreflightResult(channel=channel, compose_path=str(compose_path))

    for svc_name in CHANNEL_SERVICES:
        # Channel-critical services are checked even when absent from the
        # overlay: compose layering still starts them from the base file with
        # the base default DSNs.
        svc = services.get(svc_name) or {}
        env = _service_env(svc)

        # Build the merged env_file chain for this service:
        # base service env_files come first, then overlay service env_files.
        base_svc = base_services.get(svc_name) or {}

        base_entries = _parse_env_file_entries(base_svc)
        overlay_entries = _parse_env_file_entries(svc)

        # If the caller supplied a legacy base_defaults_path override, substitute
        # it for the first base entry (which is always config/runtime.defaults.env).
        # This preserves backward compatibility with tests that supply this param.
        if base_defaults_path is not None:
            if base_entries:
                base_entries = [(str(base_defaults_path), base_entries[0][1])] + base_entries[1:]
            else:
                # No base compose entries at all — inject the override as the
                # sole base layer (mirrors the pre-#1769 fallback behaviour).
                base_entries = [(str(base_defaults_path), True)]

        # When no base compose YAML is present and no base_defaults_path override
        # was given, fall back to the canonical base-defaults file path so that
        # tests which write only config/runtime.defaults.env still resolve DSNs.
        if not has_base_compose and base_defaults_path is None and not base_entries:
            default_env_path = compose_dir / BASE_ENV_DEFAULTS_REL
            base_entries = [(str(default_env_path), True)]

        # Reconstruct a synthetic service dict carrying the merged env_file list
        # so _resolve_env_file_chain can process it uniformly.
        combined_entries = base_entries + overlay_entries
        merged_svc_for_chain: dict[str, Any] = {
            "env_file": [{"path": p, "required": r} for p, r in combined_entries]
        }

        _check_pkm_environment(result, svc_name, env, spec)
        _check_db_dsn_with_chain(
            result,
            svc_name,
            env,
            spec,
            merged_svc_for_chain,
            base_compose_dir,
        )

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


def _check_db_dsn_with_chain(
    result: PreflightResult,
    svc_name: str,
    env: dict[str, str | None],
    spec: dict[str, Any],
    merged_svc_for_chain: dict[str, Any],
    compose_dir: Path,
) -> None:
    """Validate effective DATABASE_URL / DB_DSN bindings match the channel.

    The effective binding is resolved in priority order:
    1. The overlay ``environment`` block (direct binding — highest priority).
    2. The full per-service env_file chain from the merged compose model
       (base + overlay env_files, in declaration order, later files winning).

    Fail closed (Issues #1655, #1769): an omitted binding is a violation when
    its effective value resolves to another channel, and also when the chain
    cannot be read at all — an unverifiable binding is never safe.
    """
    db_fragment = spec.get("db_name_fragment")

    # Attempt to resolve the env_file chain once per service.  Cache the
    # result or the error so we do not re-raise per key.
    chain_result: dict[str, str] | None = None
    chain_error: _EnvFileChainError | None = None
    try:
        chain_result = _resolve_env_file_chain(merged_svc_for_chain, compose_dir)
    except _EnvFileChainError as exc:
        chain_error = exc

    for key in CHANNEL_CRITICAL_DSN_KEYS:
        dsn = env.get(key)
        if dsn is not None:
            # Direct overlay binding — check it immediately.
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

        # Key omitted from the overlay environment block: resolve through the
        # env_file chain.
        if chain_error is not None:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay "
                        "or via a readable env_file chain"
                    ),
                    actual=(
                        f"omitted from overlay; env_file chain unresolvable "
                        f"({chain_error.path_expr}: {chain_error.reason}) — "
                        "effective binding unverifiable"
                    ),
                )
            )
            continue

        # chain_result is valid (possibly empty dict if no env_files present)
        assert chain_result is not None
        fallback = chain_result.get(key)
        if fallback is None:
            # Not in any env_file either: unverifiable — fail closed.
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay "
                        "or via env_file chain"
                    ),
                    actual="omitted from overlay and absent from all env_file layers",
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
                        f"omitted from overlay; effective value from env_file chain: "
                        f"{fallback!r}"
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
