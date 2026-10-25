"""DEBRIEF-01: closure plumbing plus projection-derived, idempotent reconciliation."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Final

from app.events.models import new_event
from app.events.types import DEBRIEF_TRIGGER_CREATED
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.services.outbox import derive_idempotency_key, write_outbox_event
from app.stores import episode_debrief as store
from app.workers.outbox_binding_gate import current_binding_effect_window
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

# Provisional floor, pending real usage and eventual Settings Spine governance.
EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT: Final[int] = 3
TRIGGER_WRITE_ACTION: Final[str] = "episode_debrief.trigger"
_CONTENT_FINGERPRINT: Final[str] = "episode-debrief-trigger-v1"


class DebriefReconciliationError(RuntimeError):
    """The canonical episode could not be reconciled; its cursor stays unread."""


def debrief_id_for_episode(episode_id: str) -> str:
    return "debrief-" + hashlib.sha256(episode_id.encode("utf-8")).hexdigest()


def _closure_payload_is_valid(value: Any) -> bool:
    """Historical malformed events are plumbing; keep their raw position."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if not isinstance(value, dict):
        return False
    payload = value.get("payload", value)
    if not isinstance(payload, dict):
        return False
    count = payload.get("bound_artifact_count", 0)
    return (
        isinstance(payload.get("episode_id"), str)
        and bool(payload["episode_id"])
        and isinstance(payload.get("scope"), str)
        and bool(payload["scope"])
        and isinstance(payload.get("closed_at"), str)
        and bool(payload["closed_at"])
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
    )


def _resolve_inside(root: Path, relative: Path | str, subject: str) -> Path:
    # Cyclic or unreadable links are a per-item reconciliation failure, never
    # an abort that suppresses later healthy episodes.
    try:
        return (root / relative).resolve()
    except (OSError, RuntimeError) as exc:
        raise DebriefReconciliationError(f"{subject} cannot be reconciled") from exc


def _episode_fields(root: Path, row: store.EpisodeRow) -> dict[str, Any]:
    path = _resolve_inside(root, row.note_path, f"episode note {row.episode_id}")
    if path == root or not path.is_relative_to(root):
        raise DebriefReconciliationError("episode projection points outside the selected vault")
    try:
        fields, _ = load_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DebriefReconciliationError(f"episode note cannot be reconciled: {row.episode_id}") from exc
    if fields.get("episode_id") != row.episode_id or not isinstance(fields.get("scope"), str) or not fields["scope"]:
        raise DebriefReconciliationError(f"episode identity/scope cannot be reconciled: {row.episode_id}")
    time = fields.get("time")
    if not isinstance(time, dict) or not isinstance(time.get("closed"), bool):
        raise DebriefReconciliationError(f"episode closure cannot be reconciled: {row.episode_id}")
    return fields


def _already_debriefed(root: Path, fields: dict[str, Any], debrief_id: str) -> bool:
    # DEBRIEF-02's declared staging-adjacent artifact location. Check the
    # deterministic artifact too: synthesis may crash before appending its ref.
    refs = fields.get("debrief_ref") or []
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise DebriefReconciliationError("episode debrief_ref cannot be reconciled")
    for ref in [debrief_id, *refs]:
        # References are identities, not authority to read arbitrary paths.
        if not ref or Path(ref).name != ref or ref in {".", ".."}:
            raise DebriefReconciliationError("episode debrief_ref is not an artifact identity")
        path = _resolve_inside(
            root, Path("_system") / "episode-debriefs" / f"{ref}.md", f"debrief artifact {ref}"
        )
        if not path.is_relative_to(root):
            raise DebriefReconciliationError("debrief artifact points outside the selected vault")
        try:
            if path.is_file():
                return True
        except OSError as exc:
            raise DebriefReconciliationError(f"debrief artifact {ref} cannot be reconciled") from exc
    return False


def run_debrief_tick(
    *, vault_root: Path | str, vault_binding_id: str = COMPATIBILITY_BINDING_ID,
    limit: int = 1000, write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Reconcile every closed episode, then acknowledge the raw closure frontier.

    Emission commits before the cursor. Crash/retry re-derives the same owed
    episodes and the canonical outbox key prevents a second durable trigger.
    Reconciliation also runs with no unread events, repairing missed plumbing.
    """
    root = Path(vault_root).expanduser().resolve(strict=True)
    runtime = resolve_scalar_binding_runtime(requested_binding_id=vault_binding_id, vault_root=root)
    binding_id = runtime.vault_binding_id if runtime is not None else vault_binding_id
    # Closures, cursor and triggers follow the resolved runtime binding. The
    # scalar request reads the compatibility projection the current ERE
    # producers still write; an explicit native binding reads only its own.
    projection_binding_id = (
        COMPATIBILITY_BINDING_ID if vault_binding_id == COMPATIBILITY_BINDING_ID else binding_id
    )
    write_guard.assert_writes_allowed(TRIGGER_WRITE_ACTION)
    # Freeze the selected root so nested outbox writes never borrow ambient
    # scalar root authority.
    with current_binding_effect_window(runtime) if runtime is not None else nullcontext():
        return _reconcile(root, binding_id, projection_binding_id, limit)


def _reconcile(root: Path, binding_id: str, projection_binding_id: str, limit: int) -> dict[str, Any]:
    rows = store.read_closures(vault_binding_id=binding_id, limit=limit)
    summary: dict[str, Any] = {
        "triggered": [], "pending_debrief": [], "consumed": len(rows),
        "malformed_events": sum(not _closure_payload_is_valid(row.payload) for row in rows),
        "skipped_ineligible": 0, "skipped_already_debriefed": 0, "skipped_open": 0,
    }
    failures: list[str] = []
    for episode in store.closed_episodes(vault_binding_id=projection_binding_id):
        if episode.bound_artifact_count < EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT:
            summary["skipped_ineligible"] += 1
            continue
        debrief_id = debrief_id_for_episode(episode.episode_id)
        try:
            fields = _episode_fields(root, episode)
            if not fields["time"]["closed"]:
                summary["skipped_open"] += 1
                continue
            already_debriefed = _already_debriefed(root, fields, debrief_id)
        except DebriefReconciliationError as exc:
            # One malformed/missing note must not suppress healthy episodes.
            # The whole raw frontier remains unread until all can reconcile.
            failures.append(str(exc))
            continue
        if already_debriefed:
            summary["skipped_already_debriefed"] += 1
            continue
        scope = fields["scope"]  # Exact SoR value: no normalization or fallback.
        summary["pending_debrief"].append(debrief_id)
        event = new_event(
            event_type=DEBRIEF_TRIGGER_CREATED, source="episode_debrief.trigger",
            payload={"episode_id": episode.episode_id, "debrief_id": debrief_id,
                     "scope": scope, "bound_artifact_count": episode.bound_artifact_count},
            context_dimensions={"scope": scope, "sphere_memberships": [], "situated_identity": None},
        )
        inserted = write_outbox_event(
            event, idempotency_key=derive_idempotency_key(
                DEBRIEF_TRIGGER_CREATED, episode.episode_id, _CONTENT_FINGERPRINT,
            ), vault_binding_id=binding_id, required_db=True,
        )
        if inserted:
            summary["triggered"].append(debrief_id)
    if failures:
        raise DebriefReconciliationError("; ".join(failures))
    if rows:
        # Includes malformed terminal rows, and only after successful
        # reconciliation. Atomic advancement rejects stale completions.
        store.advance_cursor(rows[-1].position, vault_binding_id=binding_id)
    return summary
