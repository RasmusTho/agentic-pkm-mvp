"""Channel-isolation preflight guard (Issues #1627, #1655, #1769).

Fail-closed check that a compose overlay's effective env bindings
(PKM_ENVIRONMENT, DATABASE_URL / DB_DSN, vault) match the *intended* channel
before any test/prod stack start or before promote-to-test / execute-promotion
proceed.

Policy authority: docs/RELEASE_CHANNELS/README.md §Invariants.

Design constraints:
- Read-only: this module NEVER mutates operator files.
- No Docker, no network: parses compose YAML plus the per-service env_file
  chains it declares.
- Covers both committed and working-tree compose drift.
- Must cover all services that carry channel env vars (api, worker, watcher).

Omitted-binding semantics (Issues #1655, #1769): when an overlay omits
``DATABASE_URL`` / ``DB_DSN`` for a channel-critical service — by dropping the
keys or the whole service block — compose resolves the effective value from
the service's ``env_file`` chain in the merged model (base compose plus
overlay): files are read in declaration order and **later files win**. The
base compose layers an interpolated runtime env file
(``${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}``, written by
``scripts/export_runtime_env.sh`` and carrying DSNs) after
``config/runtime.defaults.env``, so the defaults alone are not the effective
binding. The preflight therefore resolves omitted keys through the full
chain — interpolating ``${VAR:-default}`` path expressions the way compose
does (invoking environment first, then ``.env`` in the compose directory) —
and fails closed when:

- the effective value lands on another channel;
- a layer that would win exists but cannot be read;
- a required layer is missing at preflight time (compose would refuse to
  start; the preflight must not silently assume absence);
- a layer's path expression cannot be resolved.

A ``required: false`` layer that is absent at preflight time contributes
nothing, exactly as compose treats it. When no base compose file sits next to
the overlay, the base layering is modeled as the single committed defaults
file (``config/runtime.defaults.env``), preserving the #1655 contract.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping
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
#: Used as the modeled base layer when no base compose file is present.
BASE_ENV_DEFAULTS_REL = Path("config") / "runtime.defaults.env"

#: Filename of the base compose file the channel overlays layer on top of.
#: The merged compose model is base + overlay (later env_file entries win).
BASE_COMPOSE_FILENAME = "docker-compose.yaml"


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


def _parse_env_file_text(text: str) -> dict[str, str | None]:
    """Parse env-file lines (comments and blanks ignored).

    ``KEY=VALUE`` defines the key. A bare ``KEY`` line (no ``=``) is compose's
    unset/passthrough form: the variable is removed from earlier layers (or
    resolved from the host environment at ``compose up`` time). It is parsed
    as ``None`` so chain resolution can treat it as a *winning* unset binding
    rather than silently keeping an earlier layer's value.
    """
    values: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep:
            values[key] = value.strip()
        elif key:
            values[key] = None
    return values


def _load_dotenv(compose_dir: Path) -> dict[str, str]:
    """Load ``.env`` next to the compose files (compose interpolation defaults)."""
    try:
        parsed = _parse_env_file_text((compose_dir / ".env").read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {key: value for key, value in parsed.items() if value is not None}


def _make_var_lookup(
    environ: Mapping[str, str],
    dotenv: Mapping[str, str],
) -> Callable[[str], str | None]:
    """Compose interpolation precedence: invoking environment, then ``.env``."""

    def lookup(name: str) -> str | None:
        if name in environ:
            return environ[name]
        return dotenv.get(name)

    return lookup


# ---------------------------------------------------------------------------
# env_file chain model (Issue #1769)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvFileLayer:
    """One env_file declaration on a service, in declaration order."""

    path_expr: str
    required: bool = True


@dataclass(frozen=True)
class _ChainResolution:
    """Outcome of resolving one env key through a service's env_file chain.

    Exactly one of these shapes holds:
    - ``error`` set: the effective value is unverifiable — fail closed.
    - ``value``/``source`` set: the winning layer's value and its file path.
    - all ``None``: no layer defines the key.
    """

    value: str | None = None
    source: str | None = None
    error: str | None = None


#: Matches compose interpolation tokens: $$, $VAR, ${...}.
_ENV_FILE_VAR_PATTERN = re.compile(
    r"\$(?:(?P<escaped>\$)|(?P<named>[A-Za-z_][A-Za-z0-9_]*)|\{(?P<braced>[^}]*)\})"
)
_BRACED_SIMPLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BRACED_DEFAULT = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<colon>:?)-(?P<default>.*)$"
)


def _interpolate_env_file_path(
    expr: str,
    lookup: Callable[[str], str | None],
) -> str | None:
    """Interpolate an env_file path expression the way compose does.

    Supports ``$VAR``, ``${VAR}``, ``${VAR-default}`` and ``${VAR:-default}``.
    Returns ``None`` when the expression uses a form the preflight cannot
    resolve (e.g. ``${VAR:?err}``, nested expressions) or when the result is
    empty / still contains ``$`` — the caller must treat that as an
    unverifiable binding and fail closed.
    """
    out: list[str] = []
    pos = 0
    for match in _ENV_FILE_VAR_PATTERN.finditer(expr):
        out.append(expr[pos:match.start()])
        pos = match.end()
        if match.group("escaped"):
            out.append("$")
            continue
        named = match.group("named")
        if named is not None:
            out.append(lookup(named) or "")
            continue
        braced = match.group("braced") or ""
        if _BRACED_SIMPLE.match(braced):
            out.append(lookup(braced) or "")
            continue
        default_match = _BRACED_DEFAULT.match(braced)
        if default_match is None or "$" in default_match.group("default"):
            return None  # unsupported expression form — unresolvable
        value = lookup(default_match.group("name"))
        if default_match.group("colon"):
            out.append(value if value else default_match.group("default"))
        else:
            out.append(value if value is not None else default_match.group("default"))
    out.append(expr[pos:])
    resolved = "".join(out)
    if not resolved or "$" in resolved:
        return None
    return resolved


def _service_env_file_layers(service_dict: dict[str, Any]) -> list[EnvFileLayer]:
    """Extract the env_file chain declared on one compose service dict."""
    raw = service_dict.get("env_file")
    if raw is None:
        return []
    if isinstance(raw, (str, int, float)):
        return [EnvFileLayer(path_expr=str(raw))]
    layers: list[EnvFileLayer] = []
    for entry in raw:
        if isinstance(entry, dict):
            layers.append(
                EnvFileLayer(
                    path_expr=str(entry.get("path", "")),
                    required=bool(entry.get("required", True)),
                )
            )
        else:
            layers.append(EnvFileLayer(path_expr=str(entry)))
    return layers


def _resolve_key_through_chain(
    key: str,
    chain: list[EnvFileLayer],
    compose_dir: Path,
    lookup: Callable[[str], str | None],
) -> _ChainResolution:
    """Resolve *key* through *chain* in declaration order; later files win.

    Fail-closed posture (Issue #1769):
    - an unresolvable path expression is immediately unverifiable;
    - a missing **required** layer is immediately unverifiable — compose would
      refuse to start the service, and the preflight cannot prove what the
      file would have contained;
    - a missing ``required: false`` layer contributes nothing, exactly as
      compose treats it;
    - a layer that exists but cannot be read is unverifiable *unless a later
      readable layer defines the key* — in that case the later layer wins
      regardless of the unreadable layer's contents;
    - a bare ``KEY`` line (no ``=``) in the winning layer unsets the binding
      or passes the host environment through at ``compose up`` time — for a
      channel-critical key that is unverifiable at preflight time and fails
      closed (a later layer that redefines the key still supersedes it).
    """
    value: str | None = None
    source: str | None = None
    pending_error: str | None = None
    for layer in chain:
        resolved_expr = _interpolate_env_file_path(layer.path_expr, lookup)
        if resolved_expr is None:
            return _ChainResolution(
                error=(
                    f"env_file path expression {layer.path_expr!r} cannot be "
                    "resolved by the preflight — effective binding unverifiable"
                )
            )
        path = Path(resolved_expr)
        if not path.is_absolute():
            path = compose_dir / path
        if not path.exists():
            if layer.required:
                return _ChainResolution(
                    error=(
                        f"required env_file layer {str(path)!r} is missing — "
                        "compose would refuse to start; effective binding "
                        "unverifiable"
                    )
                )
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            pending_error = (
                f"env_file layer {str(path)!r} exists but cannot be read — "
                "effective binding unverifiable"
            )
            continue
        layer_values = _parse_env_file_text(text)
        if key in layer_values:
            value = layer_values[key]
            source = str(path)
            pending_error = None  # later definition supersedes unreadable layers
    if pending_error is not None:
        return _ChainResolution(error=pending_error)
    if source is not None and value is None:
        return _ChainResolution(
            error=(
                f"env_file layer {source!r} unsets {key} (bare key, no '='): "
                "compose drops the binding or passes the host environment "
                "through at compose-up time — effective binding unverifiable "
                "at preflight time"
            )
        )
    return _ChainResolution(value=value, source=source)


def _env_file_chain_error(
    chain: list[EnvFileLayer],
    compose_dir: Path,
    lookup: Callable[[str], str | None],
) -> str | None:
    """Return structural env_file chain errors that make a service unverifiable.

    Explicit ``environment`` DSNs override env_file values, but Compose still
    has to resolve and load the declared env_file chain for the service. Missing
    required layers, unreadable layers, and unresolvable path expressions are
    therefore fail-closed even when channel-critical DSNs are explicit.
    """
    for layer in chain:
        resolved_expr = _interpolate_env_file_path(layer.path_expr, lookup)
        if resolved_expr is None:
            return (
                f"env_file path expression {layer.path_expr!r} cannot be "
                "resolved by the preflight — env_file chain unverifiable"
            )
        path = Path(resolved_expr)
        if not path.is_absolute():
            path = compose_dir / path
        if not path.exists():
            if layer.required:
                return (
                    f"required env_file layer {str(path)!r} is missing — "
                    "compose would refuse to start; env_file chain unverifiable"
                )
            continue
        try:
            path.read_text(encoding="utf-8")
        except OSError:
            return (
                f"env_file layer {str(path)!r} exists but cannot be read — "
                "env_file chain unverifiable"
            )
    return None


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
    base_compose_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    load_dotenv: bool = True,
) -> PreflightResult:
    """Check that *compose_path* overlay binds correctly for *channel*.

    Reads the overlay YAML from disk (working-tree copy) so uncommitted drift
    is caught immediately. DSN bindings are checked against the *effective*
    value after compose layering: the overlay value when declared, else the
    value resolved through the service's full env_file chain in the merged
    compose model (base + overlay, declaration order, later files win —
    Issue #1769). Omitted bindings whose effective value resolves to another
    channel — or cannot be verified at all — are violations (Issue #1655).

    *base_compose_path* overrides the base compose file (default:
    ``docker-compose.yaml`` next to the overlay). When no base compose file
    exists, the base layering is modeled as the single committed defaults
    file (``config/runtime.defaults.env``). *environ* overrides the
    interpolation environment for env_file path expressions (default:
    ``os.environ``, matching how compose is invoked).

    *load_dotenv* controls whether a ``.env`` next to the compose files is read
    as an interpolation default (compose's normal behaviour). Set it to
    ``False`` to make resolution hermetic from any repo-root ``.env`` — e.g. a
    test that asserts the *committed* env_file fallback, where a stray ``.env``
    on the runner would otherwise inject a winning layer and mask config drift.

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
    compose_dir = compose_path.resolve().parent

    lookup = _make_var_lookup(
        os.environ if environ is None else environ,
        _load_dotenv(compose_dir) if load_dotenv else {},
    )

    base_compose = base_compose_path or (compose_dir / BASE_COMPOSE_FILENAME)
    base_services: dict[str, Any] | None = None
    if base_compose.is_file():
        base_services = _load_compose(base_compose).get("services") or {}

    result = PreflightResult(channel=channel, compose_path=str(compose_path))

    for svc_name in CHANNEL_SERVICES:
        # Channel-critical services are checked even when absent from the
        # overlay: compose layering still starts them from the base file with
        # the base env_file chain.
        svc = services.get(svc_name) or {}
        env = _service_env(svc)

        # Merged env_file chain: base layers first, overlay layers appended
        # (compose sequence-merge semantics). Note: an overlay `env_file:
        # !override` would replace the base chain in compose; the tag is not
        # modeled here, so base layers are still checked — the stricter,
        # fail-closed direction.
        overlay_layers = _service_env_file_layers(svc)
        if base_services is None:
            chain = [EnvFileLayer(path_expr=str(BASE_ENV_DEFAULTS_REL))]
            check_explicit_chain_errors = bool(overlay_layers)
        else:
            chain = _service_env_file_layers(base_services.get(svc_name) or {})
            check_explicit_chain_errors = bool(chain or overlay_layers)
        chain = chain + overlay_layers

        _check_pkm_environment(result, svc_name, env, spec)
        _check_db_dsn(
            result,
            svc_name,
            env,
            spec,
            chain,
            compose_dir,
            lookup,
            check_explicit_chain_errors=check_explicit_chain_errors,
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


def _check_db_dsn(
    result: PreflightResult,
    svc_name: str,
    env: dict[str, str | None],
    spec: dict[str, Any],
    chain: list[EnvFileLayer],
    compose_dir: Path,
    lookup: Callable[[str], str | None],
    *,
    check_explicit_chain_errors: bool,
) -> None:
    """Validate effective DATABASE_URL / DB_DSN bindings match the channel.

    The effective binding is the overlay value when declared, else the value
    resolved through the service's env_file *chain* (declaration order, later
    files win — Issue #1769). Fail closed (Issue #1655): an omitted binding is
    a violation when its effective value resolves to another channel, and also
    when the chain cannot be verified — an unverifiable binding is never safe.
    """
    db_fragment = spec.get("db_name_fragment")
    chain_error = (
        _env_file_chain_error(chain, compose_dir, lookup)
        if check_explicit_chain_errors
        else None
    )
    for key in CHANNEL_CRITICAL_DSN_KEYS:
        dsn = env.get(key)
        if dsn is not None:
            resolved_dsn = _interpolate_env_file_path(dsn, lookup)
            if resolved_dsn is None:
                result.violations.append(
                    BindingViolation(
                        service=svc_name,
                        field=key,
                        expected=(
                            f"resolvable {key} expression containing "
                            f"{db_fragment!r}"
                        ),
                        actual=dsn,
                    )
                )
                continue
            expected_on_violation = _dsn_violation(resolved_dsn, spec)
            if expected_on_violation:
                result.violations.append(
                    BindingViolation(
                        service=svc_name,
                        field=key,
                        expected=expected_on_violation,
                        actual=resolved_dsn,
                    )
                )
            if chain_error is not None:
                result.violations.append(
                    BindingViolation(
                        service=svc_name,
                        field=key,
                        expected=(
                            f"DSN containing {db_fragment!r} declared with a "
                            "verifiable env_file chain"
                        ),
                        actual=f"explicit DSN present; {chain_error}",
                    )
                )
            continue

        # Key omitted from the overlay (or whole service absent): compose
        # resolves it through the service's env_file chain — later files win.
        resolution = _resolve_key_through_chain(key, chain, compose_dir, lookup)

        if resolution.error is not None:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay, "
                        "or a verifiable channel-correct env_file binding"
                    ),
                    actual=f"omitted from overlay; {resolution.error}",
                )
            )
            continue

        if resolution.value is None:
            # No overlay value and no env_file layer defines the key: the
            # service would start without this binding at all. Fail closed.
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=(
                        f"DSN containing {db_fragment!r} declared in the overlay "
                        "or via an env_file layer"
                    ),
                    actual="omitted from overlay and absent from every env_file layer",
                )
            )
            continue

        expected_on_violation = _dsn_violation(resolution.value, spec)
        if expected_on_violation:
            result.violations.append(
                BindingViolation(
                    service=svc_name,
                    field=key,
                    expected=f"{expected_on_violation} (explicit in the overlay)",
                    actual=(
                        f"omitted from overlay; falls back to {resolution.value!r} "
                        f"(winning env_file layer: {resolution.source})"
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
