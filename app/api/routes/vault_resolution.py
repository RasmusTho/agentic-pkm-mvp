from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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


class SelectedVaultUninitializedError(RuntimeError):
    """Raised when a write request targets a selected but uninitialized vault."""

    def __init__(self, selected_path: Path | None = None) -> None:
        self.selected_path = selected_path
        super().__init__("selected vault is not initialized")


@contextmanager
def active_vault_selection_window() -> Iterator[None]:
    """Coordinate a scalar route's effects with the real shared selector."""
    with get_vault_manager().selection_window():
        yield


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
    if (
        require_initialized
        and context.status == "uninitialized"
        and context.active_vault_path
    ):
        raise SelectedVaultUninitializedError(
            Path(context.active_vault_path).expanduser().resolve()
        )
    configured = resolve_optional_vault_root(
        environment=active_environment()
    )  # raises on set-but-missing
    raise NoSelectedVaultError(configured)


# --- MVR-05B3: named compatibility adapters ---------------------------------
#
# Route modules no longer resolve the process-selected vault themselves. A
# carrier-bearing read binds its own ActiveContextSet
# (``app.api.request_active_context.route_read_vault_root_or_selection_required``)
# and a carrier-bearing write is sealed (``app.api.compatibility_mutation``).
# Only a carrier-free legacy request reaches the three adapters below, and a
# legacy *write* reaches them only inside the compatibility write-target window,
# which proves the selection is the sole freshly revalidated compatibility
# binding. They retire with the single-binding compatibility selector (MVR-06);
# tests/architecture/context_boundary_inventory.py lists them by name.


def compatibility_vault_root(*, require_initialized: bool = False) -> Path:
    """Carrier-free compatibility adapter: the process-selected binding's root (raising)."""

    return resolve_active_vault_root(require_initialized=require_initialized)


def compatibility_vault_root_or_selection_required(
    *,
    requested_note_path: str | None = None,
    require_initialized: bool = False,
) -> Path | JSONResponse:
    """Carrier-free compatibility adapter: the selected root, or the picker state."""

    return active_vault_root_or_selection_required(
        requested_note_path=requested_note_path,
        require_initialized=require_initialized,
    )


@contextmanager
def compatibility_selection_window() -> Iterator[None]:
    """Carrier-free compatibility adapter: pin the process selection through an effect."""

    with active_vault_selection_window():
        yield


def compatibility_selected_vault_root() -> Path | None:
    """The process selection's root (selected or uninitialized), or ``None`` without one.

    Used by the pre-05C write seal to compare a legacy write's target with the
    durable compatibility binding. Never raises for a missing selection.
    """

    try:
        return compatibility_vault_root()
    except (NoSelectedVaultError, VaultRootMisconfiguredError):
        return None


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


def vault_uninitialized_json(
    *,
    requested_note_path: str | None = None,
    selected_vault_root: Path | None = None,
) -> JSONResponse:
    content = {
        "state": "vault_selection_required",
        "reason": "uninitialized",
        "message": (
            "The selected vault is not initialized yet. Initialize it to enable "
            "writes, or open a different vault to continue."
        ),
        "configured_vault_root": str(selected_vault_root)
        if selected_vault_root is not None
        else None,
        "context": {
            "status": "uninitialized",
            "active_vault_path": str(selected_vault_root)
            if selected_vault_root is not None
            else None,
        },
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
    except SelectedVaultUninitializedError as exc:
        return vault_uninitialized_json(
            requested_note_path=requested_note_path,
            selected_vault_root=exc.selected_path,
        )
    except NoSelectedVaultError as exc:
        return vault_selection_required_json(
            requested_note_path=requested_note_path,
            configured_vault_root=exc.configured_path,
        )
