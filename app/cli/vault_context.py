"""One explicit vault context per CLI invocation (MVR-05B4a, #6160).

Every vault-bound CLI entrypoint calls :func:`resolve_cli_vault_context` exactly
once, at its start, and passes the returned immutable ``VaultCarrier`` down. The
precedence is the instance's own (``docs/MULTI_VAULT_RUNTIME/README.md :: Active
context and isolation``):

1. the operator's explicit per-invocation selection (``--vault-root`` and friends);
2. when an instance registry is bound, the registry's selection chain -- instance
   default, then the legacy bootstrap binding named by the channel env root --
   ending in a valid no-vault result;
3. without a registry, the named compatibility journey: the entrypoint's legacy
   environment keys, then (where the command always used it) the process
   selection, then the command's documented default path;
4. otherwise no-vault.

Only this module reads a process-global vault environment key or the process
vault manager for the CLI; after resolution nothing below the entrypoint does.
The compatibility branch retires with the single-binding selector (MVR-06).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.instance.default_vault import VaultSelectionError, resolve_vault_selection
from app.instance.vault_carrier import VaultCarrier
from app.instance.vault_registry import VaultRegistryStore
from app.vault.manager import VaultContext, VaultManager, get_vault_manager, no_vault_context

#: The legacy environment keys each CLI entrypoint family honoured, in order.
#: ``channel`` is the configured ``VAULT_ROOT`` (env-scoped variants included).
CliEnvPolicy = Literal["channel", "mcp", "episodes", "none"]

_CLI_VAULT_ENV_KEYS = (
    "MCP_VAULT_ROOT",
    "VAULT_DIR",
    "EPISODES_VAULT_ROOT",
    "WATCHER_VAULT_PATH",
    "VAULT_ROOT",
)
_POLICY_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "channel": (),
    "mcp": ("MCP_VAULT_ROOT", "VAULT_DIR"),
    # The episodes CLI always read its keys verbatim, VAULT_ROOT last, unvalidated.
    "episodes": ("EPISODES_VAULT_ROOT", "WATCHER_VAULT_PATH", "VAULT_ROOT"),
    "none": (),
}
#: Policies whose final fallback is the validated channel ``VAULT_ROOT``.
_POLICY_USES_CHANNEL_ROOT = frozenset({"channel", "mcp"})
#: Policies whose legacy keys must name an existing directory when set.
_POLICY_VALIDATES_ENV = frozenset({"mcp"})


class CliVaultContextError(RuntimeError):
    """The invocation's vault context cannot be resolved; the command must not run."""


def _legacy_env_snapshot() -> dict[str, str]:
    """Named compatibility adapter: read the legacy CLI vault keys once."""

    values = {name: (os.getenv(name) or "").strip() for name in _CLI_VAULT_ENV_KEYS}
    return {name: value for name, value in values.items() if value}


def _compatibility_channel_root() -> Path | None:
    """Named compatibility adapter: the configured channel ``VAULT_ROOT``."""

    return resolve_optional_vault_root()


def _compatibility_process_selection() -> VaultContext:
    """Named compatibility adapter: the process-selected (or last-active) vault."""

    manager = get_vault_manager()
    if manager.context.is_selected:
        return manager.context
    return manager.load_last_active()


def _registry_store() -> VaultRegistryStore | None:
    raw = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve(strict=False)
    return VaultRegistryStore(path) if path.is_file() else None


def resolve_cli_vault_context(
    explicit: Path | str | None = None,
    *,
    env_policy: CliEnvPolicy = "channel",
    use_process_selection: bool = False,
    default_path: Path | None = None,
) -> VaultCarrier:
    """Resolve the one vault context of this CLI invocation.

    ``explicit`` is the operator's per-invocation selection and always wins.
    ``env_policy`` names the legacy environment keys the entrypoint honoured
    before MVR-05B4a; ``use_process_selection`` keeps the commands that always
    followed the picker's selection; ``default_path`` is a command's documented
    default root. A set-but-missing legacy root fails loud.
    """

    if explicit is not None and str(explicit).strip():
        return VaultCarrier(
            source="explicit_selection",
            root=Path(explicit).expanduser(),
            provenance="cli_option",
        )

    def channel_root() -> Path | None:
        if env_policy not in _POLICY_USES_CHANNEL_ROOT:
            return None
        try:
            return _compatibility_channel_root()
        except VaultRootMisconfiguredError as exc:
            raise CliVaultContextError(str(exc)) from exc

    legacy = _legacy_env_snapshot()
    registry = _registry_store()
    if registry is not None:
        snapshot = registry.load()
        bootstrap = channel_root()
        if bootstrap is None and env_policy == "episodes" and "VAULT_ROOT" in legacy:
            bootstrap = Path(legacy["VAULT_ROOT"]).expanduser()
        try:
            selection = resolve_vault_selection(snapshot, legacy_bootstrap_vault_root=bootstrap)
        except VaultSelectionError as exc:
            raise CliVaultContextError(str(exc)) from exc
        if selection.registration is not None:
            return VaultCarrier(
                source="instance_default",
                root=Path(selection.registration.path).expanduser().resolve(strict=False),
                vault_binding_id=selection.vault_binding_id,
                provenance=selection.provenance,
            )
        if default_path is None:
            return VaultCarrier(source="no_vault", root=None, provenance=selection.provenance)
        return VaultCarrier(source="compatibility", root=default_path, provenance="cli_default_path")

    for name in _POLICY_ENV_KEYS[env_policy]:
        value = legacy.get(name)
        if value is None:
            continue
        root = Path(value).expanduser()
        if env_policy in _POLICY_VALIDATES_ENV and not root.exists():
            raise CliVaultContextError(str(VaultRootMisconfiguredError(name, root)))
        return VaultCarrier(
            source="compatibility",
            root=root.resolve() if env_policy in _POLICY_VALIDATES_ENV else root,
            provenance=f"env:{name}",
        )
    configured = channel_root()
    if configured is not None:
        return VaultCarrier(source="compatibility", root=configured, provenance="env:VAULT_ROOT")
    if use_process_selection:
        selected = _compatibility_process_selection()
        if selected.status != "none" and selected.active_vault_path:
            return VaultCarrier(
                source="compatibility",
                root=Path(selected.active_vault_path).expanduser().resolve(),
                provenance="process_selection",
            )
    if default_path is not None:
        return VaultCarrier(source="compatibility", root=default_path, provenance="cli_default_path")
    return VaultCarrier(source="no_vault", root=None, provenance="no_vault")


def carrier_vault_context(carrier: VaultCarrier) -> VaultContext:
    """The validated vault context of a resolved carrier, without re-resolving selection."""

    if carrier.root is None:
        return no_vault_context()
    return VaultManager().validate_vault(carrier.root)


__all__ = [
    "CliEnvPolicy",
    "CliVaultContextError",
    "carrier_vault_context",
    "resolve_cli_vault_context",
]
