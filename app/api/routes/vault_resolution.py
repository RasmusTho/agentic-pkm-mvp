from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse

from app.config.environment import active_environment
from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.vault.manager import get_vault_manager

_READABLE_SELECTED_STATUSES: frozenset[str] = frozenset({"selected", "uninitialized"})


class NoSelectedVaultError(RuntimeError):
    """Raised when a request needs an active vault but none is selected."""

    def __init__(self, configured_path: Path | None = None) -> None:
        self.configured_path = configured_path
        super().__init__("no vault is selected")


def resolve_active_vault_root(*, require_initialized: bool = False) -> Path:
    """Return the selected vault root for request paths.

    A configured ``VAULT_ROOT`` is only offered back to the picker. It is not
    treated as active until the human selects it through ``VaultManager``.
    """

    manager = get_vault_manager()
    context = manager.context
    if context.status == "none":
        context = manager.load_last_active()
    allowed = frozenset({"selected"}) if require_initialized else _READABLE_SELECTED_STATUSES
    if context.status in allowed and context.active_vault_path:
        return Path(context.active_vault_path).expanduser().resolve()
    configured = resolve_optional_vault_root(
        environment=active_environment()
    )  # raises on set-but-missing
    raise NoSelectedVaultError(configured)


def vault_selection_required_json(
    *,
    requested_note_path: str | None = None,
    configured_vault_root: Path | None = None,
    misconfigured: VaultRootMisconfiguredError | None = None,
) -> JSONResponse:
    if misconfigured is not None:
        content = {
            "state": "vault_selection_required",
            "reason": "vault_root_misconfigured",
            "message": (
                "The configured vault path is missing. Open an existing vault "
                "or choose a recent vault to continue."
            ),
            "configured_vault_root": str(misconfigured.configured_path),
        }
    else:
        content = {
            "state": "vault_selection_required",
            "reason": "no_vault_bound",
            "message": (
                "No vault is selected. Open the configured vault, choose a "
                "recent vault, or create a new vault to continue."
                if configured_vault_root is not None
                else "No vault is bound. Open an existing vault, choose a "
                "recent vault, or create a new vault to continue."
            ),
            "configured_vault_root": str(configured_vault_root)
            if configured_vault_root is not None
            else None,
        }
    if requested_note_path is not None:
        content["requested_note_path"] = requested_note_path
    return JSONResponse(status_code=200, content=content)


def active_vault_root_or_selection_required(
    *,
    requested_note_path: str | None = None,
    require_initialized: bool = False,
) -> Path | JSONResponse:
    try:
        return resolve_active_vault_root(require_initialized=require_initialized)
    except VaultRootMisconfiguredError as exc:
        return vault_selection_required_json(
            requested_note_path=requested_note_path,
            misconfigured=exc,
        )
    except NoSelectedVaultError as exc:
        return vault_selection_required_json(
            requested_note_path=requested_note_path,
            configured_vault_root=exc.configured_path,
        )
