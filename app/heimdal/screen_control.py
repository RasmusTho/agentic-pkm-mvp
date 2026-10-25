"""Host control contract consumed by SCREEN-03; this module never captures.

The Settings Spine owns Markdown, guarded acceptance, and durable receipts.
The external client must combine this permission with its own live capture
state; a host settings read is not evidence that a client is observing.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.settings.models import SCREEN_CONTROL_KEYS, ScreenControlSettings
from app.vault.manager import VaultContext
from app.vault.settings_service import SettingsService


@dataclass(frozen=True)
class ScreenControlResolution:
    controls: ScreenControlSettings
    errors: tuple[str, ...]
    accepted_keys: frozenset[str] = frozenset()


def revoke_screen_control_grants(*, actor: str, context: VaultContext) -> None:
    """Complete pause's canonical consent revocation before settings acceptance.

    Durable revocation is never compensated with a grant. If immediate erasure
    fails, its ledger row remains the existing recovery work item; a pause retry
    reconciles that screen-only work even though the grant is already inactive.
    Resume settings never call a grant writer.
    """
    from app.heimdal.consent_ledger import (
        list_active_grants, reconcile_revoked_consent_erasure, revoke_consent,
    )
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    failures: list[Exception] = []
    for grant in list_active_grants(scope=SCREEN_CAPTURE_SCOPE):
        try:
            revoke_consent(
                grant_ref=grant.grant_ref,
                revoked_by=actor,
                payload={
                    "reason": "screen_pause",
                    "vault_id": context.active_vault_id,
                    "local_instance_id": context.local_instance_id,
                },
            )
        except Exception as exc:
            # The canonical call can commit revocation and then fail erasure.
            # Continue revoking the remaining grants so cleanup trouble cannot
            # leave an older/newer grant admitting capture. Preserve failure:
            # settings acceptance still waits for a successful erasure retry.
            failures.append(exc)
    if failures:
        raise RuntimeError("screen grant revocation/erasure incomplete; retry required") from failures[0]
    reconcile_revoked_consent_erasure(scope=SCREEN_CAPTURE_SCOPE)
    if list_active_grants(scope=SCREEN_CAPTURE_SCOPE):
        raise RuntimeError("screen consent changed during pause; retry required")


def legacy_screen_retention(context: VaultContext) -> tuple[bool, Any]:
    """Keep an existing SCREEN-01 policy from silently becoming a default.

    This is migration evidence only. The legacy value is never consumed as a
    second effective screen configuration. An explicit Settings Spine write
    establishes the new authority and preserves the old value in its receipt.
    """
    from app.heimdal.settings_notes import SETTINGS, read_settings_note

    if not context.active_vault_path:
        return False, None
    try:
        note = read_settings_note(Path(context.active_vault_path), SETTINGS)
    except (ValueError, OSError):
        return True, None
    key = "screen_frame_retention_minutes"
    return (True, note.values[key]) if note is not None and key in note.values else (False, None)


def resolve_screen_controls(
    context: VaultContext, *, service: SettingsService | None = None,
) -> ScreenControlResolution:
    from app.services.outbox import JsonlOutboxCorruptionError

    service = service or SettingsService()
    try:
        accepted = service.resolve_accepted_runtime_gating(context)
    except (OSError, JsonlOutboxCorruptionError):
        return ScreenControlResolution(ScreenControlSettings(), ("accepted screen control receipt history unavailable",))
    controls = ScreenControlSettings.model_validate({key: accepted[key].value for key in SCREEN_CONTROL_KEYS})
    accepted_keys = frozenset(
        key for key in SCREEN_CONTROL_KEYS
        if accepted[key].source == "accepted-runtime-gating-receipt"
    )
    if (
        context.status != "selected" or not context.settings_path
        or not context.active_vault_id or not context.local_instance_id
    ):
        return ScreenControlResolution(controls, ("no selected initialized vault",), accepted_keys)
    path = Path(context.settings_path) / "screen_control.md"
    if not path.is_file():
        return ScreenControlResolution(controls, ("missing settings/screen_control.md; capture remains paused",), accepted_keys)
    try:
        document = service.markdown_store.read(path)
        if any(not isinstance(key, str) for key in document.frontmatter):
            raise ValueError("screen control source contains non-string keys")
        ScreenControlSettings.model_validate({
            key: value for key, value in document.frontmatter.items() if key.startswith("screen_")
        })
        resolution = service.resolve(context)
    except (ValueError, OSError) as exc:
        return ScreenControlResolution(controls, (str(exc),), accepted_keys)
    errors = [
        error.message for error in resolution.validation_errors
        if error.key in SCREEN_CONTROL_KEYS or error.source_file == str(path)
    ]
    legacy_present, _legacy_value = legacy_screen_retention(context)
    if legacy_present and accepted["screen_frame_retention_minutes"].source == "accepted-runtime-gating-default":
        errors.append("legacy screen retention requires an explicit Settings Spine write before activation")
    for key in sorted(SCREEN_CONTROL_KEYS):
        if resolution.settings[key].value != accepted[key].value:
            errors.append(f"{key} is pending durable Settings Spine acceptance")
    return ScreenControlResolution(controls, tuple(errors), accepted_keys)


def screen_control_status(
    context: VaultContext, *, app_id: str | None = None, scopes: Sequence[str] = (),
) -> dict[str, Any]:
    from app.heimdal.consent_ledger import resolve_active_grant
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    resolution = resolve_screen_controls(context)
    controls, errors = resolution.controls, resolution.errors
    try:
        consent_active = resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is not None
    except Exception:
        consent_active = False
        errors = (*errors, "screen consent state unavailable")
    mapped_scopes = {
        scope for scope, apps in controls.screen_scope_app_mapping.items() if app_id in apps
    }
    effective_scopes = set(scopes) | mapped_scopes
    excluded = app_id in controls.screen_excluded_apps or bool(
        effective_scopes.intersection(controls.screen_excluded_scopes)
    )
    paused = controls.screen_paused or bool(errors) or not consent_active
    return {
        "state": "degraded" if errors else "paused" if paused else "ready",
        "requested_state": "paused" if controls.screen_paused else "resume_requested",
        "paused": paused,
        "settings_state": ("degraded_last_valid" if resolution.accepted_keys else "invalid_sources") if errors else "ok",
        "errors": list(errors),
        "controls": controls.model_dump(),
        "consent_active": consent_active and not controls.screen_paused,
        "capture_permitted": not paused and bool(app_id) and not excluded,
        "excluded": excluded,
        "app_id": app_id,
        "scopes": sorted(effective_scopes),
        "capture_state": "unknown_external_client",
        "vault_id": context.active_vault_id,
        "local_instance_id": context.local_instance_id,
    }
