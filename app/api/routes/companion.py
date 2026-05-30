"""Companion UI workspace endpoints: read aggregate, vault browser, body update."""

from __future__ import annotations

import datetime
import os
import heapq
from pathlib import Path, PurePosixPath
from uuid import uuid4

import yaml

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.routes.artifacts import _content_hash, _extract_title
from app.chat.canvas_writer import _body_contains_frontmatter, _split_frontmatter
from app.config.paths import resolve_vault_root
from app.knowledge.write_ops import write_note_from_absolute
from app.observability.status_service import OrientationSignals, get_orientation_signals
from app.orientation.runtime import build_orientation_frame
from app.resurfacing.runtime import evaluate_resurfacing_candidates
from app.services.artifact_identity import resolve_note_artifact_identity
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

router = APIRouter(prefix="/companion", tags=["companion"])


class ArtifactState(BaseModel):
    artifact_id: str | None
    artifact_kind: str = "human_note"
    note_path: str
    title: str
    body: str
    content_hash: str
    identity_source: str = "unknown"
    identity_state: str = "unknown"
    companion_of: str | None = None
    owns_identity: bool = True


class VaultIdentityState(BaseModel):
    vault_name: str
    channel: str
    provenance: str


_BROWSE_EXCLUDE_DIR_PREFIXES = (".", "__")


def _parse_browse_max_notes() -> int:
    raw = (os.getenv("VAULT_BROWSE_MAX_NOTES") or "").strip()
    try:
        value = int(raw) if raw else 500
    except ValueError:
        return 500
    return value if value > 0 else 500


_BROWSE_MAX_NOTES = _parse_browse_max_notes()


class VaultNoteEntry(BaseModel):
    path: str
    title: str
    size_bytes: int


class VaultNoteListResponse(BaseModel):
    notes: list[VaultNoteEntry]
    vault_identity: VaultIdentityState
    total_count: int


class RuntimeState(BaseModel):
    environment_label: str
    api_base_url_label: str
    trace_id: str
    vault_identity: VaultIdentityState
    reorient: dict[str, list[dict[str, str | bool]]] = Field(default_factory=dict)
    resurface: dict[str, list[dict[str, str | list[str]]]] = Field(default_factory=dict)


class CanvasState(BaseModel):
    session_id: str | None
    session_state: str | None
    user_present: bool
    can_edit_body: bool
    recovery_needed: bool
    session_log_path: str | None
    undo_available: bool = False
    applied_edit_count: int = 0
    undone_edit_count: int = 0
    session_persistence: str = "in_memory"


class PanelState(BaseModel):
    state: str
    proposal_count: int
    receipt_count: int
    latest_receipt_outcome: str | None
    blocked_reason: str | None
    no_match_reason: str | None


class SuggestionsState(BaseModel):
    current_suggestion_state: str | None = None
    server_declared_classification: str | None = None
    pending_receipts: list[dict[str, str]] = Field(default_factory=list)


class WorkspaceUpdateCapabilityState(BaseModel):
    available: bool
    state: str
    reason: str
    scope: str = "active_note_body"
    governance_actions_enabled: bool = False
    config_mode: str = "inherited"


class GuardState(BaseModel):
    canvas_enabled: bool
    writeguard_status: str
    update_flow_available: bool
    degraded: bool
    workspace_update: WorkspaceUpdateCapabilityState


class WorkspaceStateResponse(BaseModel):
    artifact: ArtifactState
    runtime: RuntimeState
    canvas: CanvasState
    panel: PanelState
    suggestions: SuggestionsState
    guards: GuardState


class WorkspaceBodyUpdateRequest(BaseModel):
    active_note_path: str
    target_note_path: str
    new_body: str
    content_hash: str | None = None


class WorkspaceBodyUpdateResponse(BaseModel):
    ok: bool
    state: str
    note_path: str
    reason: str | None = None
    content_hash_before: str
    content_hash_after: str


class VaultBrowserNoteState(BaseModel):
    note_path: str
    title: str
    zone: str
    # Normalized artifact metadata (server-owned; client never parses YAML)
    uuid: str | None = None
    kind: str | None = None
    review_state: str | None = None
    trust: str | None = None
    origin: str | None = None
    source_ref: str | None = None
    created: str | None = None
    updated: str | None = None
    frontmatter_valid: bool = False
    missing_required_fields: list[str] = Field(default_factory=list)


class VaultBrowserStateResponse(BaseModel):
    notes: list[VaultBrowserNoteState]
    query: str
    total_notes: int
    filtered_notes: int
    read_only: bool = True
    vault_identity: VaultIdentityState
    identity_available: bool
    active_filters: dict[str, list[str]] = Field(default_factory=dict)


class VaultLinkIndexResponse(BaseModel):
    """Complete, read-only listing of active-vault note paths for link resolution.

    The Companion UI seeds its ``VaultLinkResolver`` from ``note_paths`` so that
    vault-internal wikilinks resolve and navigate (#1431). Unlike the vault
    browser, this is **not** paginated/filtered — it is the full link index. The
    resolver expands each path into its lookup keys (full path, stem path, name,
    stem); the server returns the raw paths so the UI never reads the filesystem.
    """

    note_paths: list[str]
    total_notes: int
    truncated: bool = False
    read_only: bool = True
    vault_identity: VaultIdentityState
    identity_available: bool


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_environment_label() -> str:
    raw = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("PKM_ENVIRONMENT")
        or os.getenv("CHANNEL")
        or os.getenv("PKM_CHANNEL")
        or ""
    ).strip().lower()
    if raw in {"dev", "test", "prod"}:
        return raw
    return "unknown"


def _safe_api_label() -> str:
    return (os.getenv("COMPANION_API_BASE_URL_LABEL") or "local-dev").strip() or "local-dev"


def _configured_vault_name() -> str | None:
    """Return the operator-configured vault name from settings, if any.

    Vault identity is a first-class, hot-reloadable setting
    (``instance.vault.name``). Reading it here means a renamed or switched vault
    takes effect on the next request with no restart, and it is the seam where
    future multi-vault selection will resolve the active vault.
    """
    try:
        from app.settings.runtime import get_settings_bundle

        bundle = get_settings_bundle()
    except Exception:
        return None
    vault = getattr(getattr(bundle, "instance", None), "vault", None)
    name = getattr(vault, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _vault_identity_state(vault_root: Path) -> VaultIdentityState:
    raw_channel = (
        os.getenv("PKM_ENVIRONMENT")
        or os.getenv("CHANNEL")
        or os.getenv("PKM_CHANNEL")
        or ""
    ).strip().lower()
    channel = raw_channel if raw_channel in {"dev", "test", "prod"} else "unknown"

    # A configured vault name is authoritative. It survives the container's
    # host-VAULT_ROOT-vs-/app/vault path divergence that previously mislabeled a
    # correctly-mounted vault as `fallback`/`vault`.
    configured_name = _configured_vault_name()
    if configured_name:
        return VaultIdentityState(
            vault_name=configured_name,
            channel=channel,
            provenance="settings",
        )

    # No configured name: infer identity from the VAULT_ROOT path as before.
    vault_root_raw = os.getenv("VAULT_ROOT", "").strip()
    vault_name = vault_root.name or str(vault_root)
    if not vault_root_raw:
        provenance = "default"
    else:
        try:
            env_path = Path(vault_root_raw).resolve()
            provenance = "env" if env_path == vault_root.resolve() else "fallback"
        except Exception:
            provenance = "fallback"
    return VaultIdentityState(
        vault_name=vault_name,
        channel=channel,
        provenance=provenance,
    )


def _list_vault_notes(vault_root: Path, q: str = "") -> list[VaultNoteEntry]:
    if not vault_root.exists():
        return []
    q_lower = q.strip().lower()
    notes: list[VaultNoteEntry] = []
    for path in vault_root.rglob("*.md"):
        try:
            parts = path.relative_to(vault_root).parts
            if any(p.startswith(_BROWSE_EXCLUDE_DIR_PREFIXES) for p in parts):
                continue
            rel = path.relative_to(vault_root).as_posix()
            if q_lower and q_lower not in rel.lower():
                body_preview = path.read_text(encoding="utf-8", errors="replace")
                title = _extract_title(body_preview, fallback=path.stem)
                if q_lower not in title.lower():
                    continue
            else:
                body_preview = path.read_text(encoding="utf-8", errors="replace")
                title = _extract_title(body_preview, fallback=path.stem)
            notes.append(VaultNoteEntry(path=rel, title=title, size_bytes=path.stat().st_size))
            if len(notes) >= _BROWSE_MAX_NOTES:
                break
        except Exception:
            continue
    return notes


@router.get("/vault/notes", response_model=VaultNoteListResponse)
def list_vault_notes(
    q: str = Query("", description="Optional search filter by title or path"),
) -> VaultNoteListResponse:
    vault_root = resolve_vault_root()
    notes = _list_vault_notes(vault_root, q=q)
    return VaultNoteListResponse(
        notes=notes,
        vault_identity=_vault_identity_state(vault_root),
        total_count=len(notes),
    )


def _validate_workspace_note_path(note_path_raw: str) -> str:
    candidate = PurePosixPath(note_path_raw)
    if (
        not note_path_raw
        or note_path_raw.startswith("/")
        or ".." in candidate.parts
        or candidate.as_posix() in {"", "."}
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_note_path",
                "message": "note_path must be a relative runtime note path",
                "trace_id": uuid4().hex,
            },
        )
    return candidate.as_posix()


def _validate_workspace_markdown_note_path(note_path_raw: str) -> str:
    safe_note_path = _validate_workspace_note_path(note_path_raw)
    if not safe_note_path.endswith(".md"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "not_a_note_file",
                "message": "Body updates are restricted to markdown note files (.md)",
            },
        )
    return safe_note_path


def _find_workspace_note(vault_root: Path, safe_note_path: str) -> Path | None:
    candidate = vault_root / safe_note_path
    return candidate if candidate.is_file() else None


def _vault_relative(path: Path, vault_root: Path) -> str | None:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return None


def _active_canvas_session(safe_note_path: str, vault_root: Path) -> object | None:
    for session in canvas_module._sessions.values():
        session_note_path = _vault_relative(Path(session.note_path), vault_root)
        if session_note_path == safe_note_path:
            return session
    return None


def _canvas_state(safe_note_path: str, vault_root: Path, canvas_enabled: bool) -> CanvasState:
    session = _active_canvas_session(safe_note_path, vault_root)
    if session is None:
        return CanvasState(
            session_id=None,
            session_state=None,
            user_present=False,
            can_edit_body=False,
            recovery_needed=False,
            session_log_path=None,
        )

    log_path = _vault_relative(Path(session.log_path), vault_root)
    applied_edits = getattr(canvas_module, "_edit_history", {}).get(session.session_id, [])
    undone_edits = getattr(canvas_module, "_undone_history", {}).get(session.session_id, [])
    undo_available = _undo_available_for_session(session=session, applied_edits=applied_edits)
    return CanvasState(
        session_id=session.session_id,
        session_state="active",
        user_present=canvas_enabled,
        can_edit_body=canvas_enabled,
        recovery_needed=False,
        session_log_path=log_path,
        undo_available=undo_available,
        applied_edit_count=len(applied_edits),
        undone_edit_count=len(undone_edits),
    )


def _undo_available_for_session(*, session: object, applied_edits: list[object]) -> bool:
    if not applied_edits:
        return False
    latest = applied_edits[-1]
    try:
        current_body = canvas_module._note_body(Path(session.note_path))
    except Exception:
        return False
    return current_body == getattr(latest, "body_after", None)


def _proposal_count_for_artifact(artifact_id: str | None) -> int:
    if artifact_id is None:
        return 0
    proposals = getattr(confirm_module._proposal_store, "_proposals", {})
    return sum(1 for proposal in proposals.values() if proposal.artifact_id == artifact_id)


def _panel_state(artifact_id: str | None) -> PanelState:
    proposal_count = _proposal_count_for_artifact(artifact_id)
    cache = getattr(confirm_module._idempotency_store, "_cache", {})
    relevant = [resp for resp in cache.values() if resp.artifact_id == artifact_id]
    latest = relevant[-1] if relevant else None
    blocked_reason = None
    latest_outcome = None
    if latest is not None:
        latest_outcome = latest.outcome
        if latest.block_reason is not None:
            blocked_reason = latest.block_reason.message
    if blocked_reason:
        state = "blocked"
    elif proposal_count:
        state = "proposals-staged"
    elif latest_outcome == "success":
        state = "receipt-displayed"
    else:
        state = "idle"
    return PanelState(
        state=state,
        proposal_count=proposal_count,
        receipt_count=len(relevant),
        latest_receipt_outcome=latest_outcome,
        blocked_reason=blocked_reason,
        no_match_reason=None,
    )


def _writeguard_status() -> str:
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.workspace.read")
    except WritesBlockedError:
        return "blocked"
    except Exception:
        return "unknown"
    return "ok"


def _workspace_update_capability(
    *,
    canvas_enabled: bool,
    writeguard_status: str,
) -> WorkspaceUpdateCapabilityState:
    raw = os.getenv("COMPANION_WORKSPACE_UPDATE_ENABLED")
    explicit = raw is not None
    if explicit:
        config_enabled = raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        # Backwards-compatible fallback when older clients only reason about Canvas.
        config_enabled = canvas_enabled

    if not canvas_enabled:
        return WorkspaceUpdateCapabilityState(
            available=False,
            state="disabled",
            reason="canvas_disabled",
            config_mode="explicit" if explicit else "inherited",
        )
    if not config_enabled:
        return WorkspaceUpdateCapabilityState(
            available=False,
            state="disabled",
            reason="disabled_by_config" if explicit else "disabled_by_canvas_policy",
            config_mode="explicit" if explicit else "inherited",
        )
    if writeguard_status == "blocked":
        return WorkspaceUpdateCapabilityState(
            available=False,
            state="disabled",
            reason="writeguard_blocked",
            config_mode="explicit" if explicit else "inherited",
        )
    if writeguard_status == "unknown":
        return WorkspaceUpdateCapabilityState(
            available=False,
            state="degraded",
            reason="writeguard_unknown",
            config_mode="explicit" if explicit else "inherited",
        )

    return WorkspaceUpdateCapabilityState(
        available=True,
        state="available",
        reason="explicit_dev_config" if explicit else "canvas_inherited",
        config_mode="explicit" if explicit else "inherited",
    )


def _reorient_state(signals: OrientationSignals | None = None) -> dict[str, list[dict[str, str | bool]]]:
    def item(
        label: str,
        *,
        source_link: str = "runtime:orientation",
        panel_handoff: bool = False,
    ) -> dict[str, str | bool]:
        return {
            "label": label,
            "source_link": source_link,
            "panel_handoff": panel_handoff,
        }

    try:
        frame = build_orientation_frame(signals=signals)
    except Exception:
        return {
            "facts": [],
            "inferences": [],
            "candidates": [],
            "stale_context": [
                item(
                    "Orientation runtime unavailable; Reorient metadata is degraded.",
                    source_link="runtime:orientation#unavailable",
                )
            ],
            "recent_deltas": [],
            "open_loops": [],
        }

    open_loops = [
        item(loop, panel_handoff=not loop.startswith("No unresolved"))
        for loop in frame.explanation.open_items
    ]
    candidates = [
        item(intent, panel_handoff=True)
        for intent in frame.mutation_intents
    ]
    if not candidates:
        candidates = [
            item(
                "No direct action candidate is staged by the orientation runtime.",
                panel_handoff=False,
            )
        ]
    return {
        "facts": [
            item(frame.explanation.leave_point),
        ],
        "inferences": [
            item(frame.frame),
        ],
        "candidates": candidates,
        "stale_context": [
            item(
                "No stale context marker is present in the current orientation runtime snapshot.",
            )
        ],
        "recent_deltas": [
            item(frame.explanation.notable_change),
        ],
        "open_loops": open_loops,
    }


def _resurface_state(safe_note_path: str, signals: OrientationSignals | None = None) -> dict[str, list[dict[str, str | list[str]]]]:
    evaluation = evaluate_resurfacing_candidates(signals=signals)
    candidates: list[dict[str, str | list[str]]] = []
    for candidate in evaluation.candidates:
        signals = candidate.why_now.signals
        source_link = _safe_resurface_source_link(candidate.candidate_id)
        signal_labels = [f"{signal.name}={signal.value}" for signal in signals]
        candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "label": candidate.label,
                "why_now": candidate.why_now.explanation,
                "relation_to_active_artifact": (
                    f"Runtime resurfacing signal evaluated while {safe_note_path} is active."
                ),
                "source_link": source_link,
                "signal_labels": signal_labels,
            }
        )
    return {"candidates": candidates}


def _safe_resurface_source_link(candidate_id: str) -> str:
    if candidate_id == "resurface-worker-queue":
        return "status.worker_queue"
    if candidate_id in {"resurface-pending-promotions", "resurface-new-activity"}:
        return "status.events"
    return "runtime:resurfacing"


_ARTIFACT_REQUIRED_FIELDS = ("uuid",)
_ARTIFACT_OPTIONAL_FIELDS = (
    "kind",
    "review_state",
    "trust",
    "origin",
    "source_ref",
    "created",
    "updated",
)


def _parse_note_artifact_metadata(body: str, *, path_derived_zone: str) -> dict:
    """Parse frontmatter from a note body and return normalized artifact metadata.

    Server-side only — clients must never parse raw YAML.
    Returns a dict with all VaultBrowserNoteState metadata fields populated.
    Missing YAML or malformed YAML → frontmatter_valid=False + missing_required_fields.
    """
    fm_inner, _ = _split_frontmatter(body)
    if fm_inner is None:
        return {
            "uuid": None,
            "kind": None,
            "zone": path_derived_zone,
            "review_state": None,
            "trust": None,
            "origin": None,
            "source_ref": None,
            "created": None,
            "updated": None,
            "frontmatter_valid": False,
            "missing_required_fields": list(_ARTIFACT_REQUIRED_FIELDS),
        }

    try:
        fm: dict = yaml.safe_load(fm_inner) or {}
        if not isinstance(fm, dict):
            fm = {}
        parse_error = False
    except Exception:
        fm = {}
        parse_error = True

    uuid_val = fm.get("uuid")
    normalized_uuid = _str_or_none(uuid_val)
    missing = ["uuid"] if normalized_uuid is None else []
    frontmatter_valid = not parse_error and not missing

    fm_zone = fm.get("zone")
    zone = str(fm_zone).strip() if fm_zone else path_derived_zone

    return {
        "uuid": normalized_uuid,
        "kind": _str_or_none(fm.get("kind")),
        "zone": zone,
        "review_state": _str_or_none(fm.get("review_state")),
        "trust": _str_or_none(fm.get("trust")),
        "origin": _str_or_none(fm.get("origin")),
        "source_ref": _str_or_none(fm.get("source_ref")),
        "created": _str_or_none(fm.get("created")),
        "updated": _str_or_none(fm.get("updated")),
        "frontmatter_valid": frontmatter_valid,
        "missing_required_fields": missing if not parse_error else list(_ARTIFACT_REQUIRED_FIELDS),
    }


def _str_or_none(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    s = str(val).strip()
    return s if s else None


def _zone_for_path(note_path: str) -> str:
    parts = PurePosixPath(note_path).parts
    return parts[0] if parts else "root"


def _is_hidden_browser_path(safe_path: str) -> bool:
    parts = PurePosixPath(safe_path).parts
    return any(part.startswith(".") for part in parts[:-1])



def _safe_vault_browse_max_notes() -> int:
    raw = os.getenv("VAULT_BROWSE_MAX_NOTES")
    if raw is None:
        return 250
    try:
        parsed = int(raw.strip())
    except (TypeError, ValueError):
        return 250
    return max(1, min(parsed, 1000))


_FILTER_FIELDS = ("kind", "zone", "review_state", "trust")


def _note_matches_filters(note: VaultBrowserNoteState, filters: dict[str, list[str]]) -> bool:
    """Return True if note satisfies all active metadata filters (AND across dimensions)."""
    for field, values in filters.items():
        if not values:
            continue
        note_val = getattr(note, field, None)
        if note_val not in values:
            return False
    return True


def _select_vault_notes(
    vault_root: Path,
    *,
    query: str,
    limit: int,
    filters: dict[str, list[str]] | None = None,
) -> tuple[list[VaultBrowserNoteState], int, int]:
    needle = query.strip().lower()
    active_filters = filters or {}
    total_notes = 0
    filtered_notes = 0
    # Keep only the lexicographically-smallest `limit` note paths without
    # materializing the full sorted collection in memory.
    selected_heap: list[tuple[str, VaultBrowserNoteState]] = []
    for candidate in vault_root.rglob("*.md"):
        if not candidate.is_file():
            continue
        safe_path = _vault_relative(candidate, vault_root)
        if safe_path is None:
            continue
        if _is_hidden_browser_path(safe_path):
            continue
        total_notes += 1
        body = candidate.read_text(encoding="utf-8")
        title = _browser_title(body, fallback=candidate.stem)
        if needle and needle not in safe_path.lower() and needle not in title.lower():
            continue
        path_zone = _zone_for_path(safe_path)
        metadata = _parse_note_artifact_metadata(body, path_derived_zone=path_zone)
        note = VaultBrowserNoteState(
            note_path=safe_path,
            title=title,
            zone=metadata["zone"],
            uuid=metadata["uuid"],
            kind=metadata["kind"],
            review_state=metadata["review_state"],
            trust=metadata["trust"],
            origin=metadata["origin"],
            source_ref=metadata["source_ref"],
            created=metadata["created"],
            updated=metadata["updated"],
            frontmatter_valid=metadata["frontmatter_valid"],
            missing_required_fields=metadata["missing_required_fields"],
        )
        if not _note_matches_filters(note, active_filters):
            continue
        filtered_notes += 1
        key = note.note_path
        if len(selected_heap) < limit:
            heapq.heappush(selected_heap, (_invert_lex(key), note))
        elif _invert_lex(key) > selected_heap[0][0]:
            heapq.heapreplace(selected_heap, (_invert_lex(key), note))

    selected = sorted((item[1] for item in selected_heap), key=lambda note: note.note_path)
    return selected, total_notes, filtered_notes


def _invert_lex(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(ch)) for ch in value)


def _filter_notes(
    notes: list[VaultBrowserNoteState],
    *,
    query: str,
) -> list[VaultBrowserNoteState]:
    if not query:
        return notes
    needle = query.strip().lower()
    if not needle:
        return notes
    return [
        note
        for note in notes
        if needle in note.note_path.lower() or needle in note.title.lower()
    ]


def _browser_title(body: str, *, fallback: str) -> str:
    if body.startswith("---\n"):
        lines = body.splitlines()
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() == "title":
                parsed = value.strip().strip('"').strip("'")
                if parsed:
                    return parsed
    return _extract_title(body, fallback=fallback)


def _compose_note_with_preserved_frontmatter(*, original_content: str, new_body: str) -> str:
    if _body_contains_frontmatter(new_body):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "frontmatter_update_not_allowed",
                "state": "failure",
                "message": (
                    "active-note body update only accepts body content; "
                    "frontmatter changes require a governed flow"
                ),
            },
        )
    frontmatter_inner, _ = _split_frontmatter(original_content)
    if frontmatter_inner is not None:
        return f"---{frontmatter_inner}\n---\n{new_body}"
    return new_body if new_body.endswith("\n") else f"{new_body}\n"


@router.get("/vault-browser", response_model=VaultBrowserStateResponse)
def read_companion_vault_browser(
    q: str = Query("", description="Case-insensitive path/title filter"),
    limit: int = Query(250, ge=1, le=1000),
    kind: list[str] = Query(default=[], description="Filter by artifact kind (multi-value)"),
    zone: list[str] = Query(default=[], description="Filter by zone (multi-value)"),
    review_state: list[str] = Query(default=[], description="Filter by review_state (multi-value)"),
    trust: list[str] = Query(default=[], description="Filter by trust tier (multi-value)"),
) -> VaultBrowserStateResponse:
    # Vault Browser MLP v0 surface. Contract:
    # docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md §6. Read-only Markdown
    # enumeration with deterministic title/path filtering, active-vault
    # identity, and explicit empty / error / identity-unavailable states.
    # Hidden / dot-prefixed folders are excluded.
    # Metadata filters (kind, zone, review_state, trust) added in #1254.
    vault_root = resolve_vault_root()
    effective_limit = min(limit, _safe_vault_browse_max_notes())
    active_filters: dict[str, list[str]] = {}
    if kind:
        active_filters["kind"] = list(kind)
    if zone:
        active_filters["zone"] = list(zone)
    if review_state:
        active_filters["review_state"] = list(review_state)
    if trust:
        active_filters["trust"] = list(trust)
    selected, total_notes, filtered_notes = _select_vault_notes(
        vault_root,
        query=q,
        limit=effective_limit,
        filters=active_filters,
    )
    identity = _vault_identity_state(vault_root)
    identity_available = (
        bool(identity.vault_name.strip()) and identity.channel in {"dev", "test", "prod"}
    )
    return VaultBrowserStateResponse(
        notes=selected,
        query=q,
        total_notes=total_notes,
        filtered_notes=filtered_notes,
        read_only=True,
        vault_identity=identity,
        identity_available=identity_available,
        active_filters=active_filters,
    )


def _safe_vault_link_index_max() -> int:
    raw = os.getenv("VAULT_LINK_INDEX_MAX")
    if raw is None:
        return 5000
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 5000


def _collect_vault_note_paths(vault_root: Path, *, limit: int) -> tuple[list[str], bool]:
    """Enumerate every non-hidden Markdown note path under the vault (read-only).

    Returns (sorted_paths, truncated). No file content is read and nothing is
    written; only paths are collected for link resolution (#1431).
    """
    paths: list[str] = []
    truncated = False
    for candidate in vault_root.rglob("*.md"):
        if not candidate.is_file():
            continue
        safe_path = _vault_relative(candidate, vault_root)
        if safe_path is None or _is_hidden_browser_path(safe_path):
            continue
        paths.append(safe_path)
        if len(paths) >= limit:
            truncated = True
            break
    paths.sort()
    return paths, truncated


@router.get("/vault-link-index", response_model=VaultLinkIndexResponse)
def read_companion_vault_link_index() -> VaultLinkIndexResponse:
    # #1431 — complete read-only note-path listing so the Companion UI can seed
    # VaultLinkResolver and resolve vault-internal wikilinks end-to-end. Mirrors
    # the vault browser's read-only posture (no mutation, no write path); the UI
    # must not read the filesystem directly (UI_RUNTIME_BOUNDARIES).
    vault_root = resolve_vault_root()
    note_paths, truncated = _collect_vault_note_paths(
        vault_root, limit=_safe_vault_link_index_max()
    )
    identity = _vault_identity_state(vault_root)
    identity_available = (
        bool(identity.vault_name.strip()) and identity.channel in {"dev", "test", "prod"}
    )
    return VaultLinkIndexResponse(
        note_paths=note_paths,
        total_notes=len(note_paths),
        truncated=truncated,
        read_only=True,
        vault_identity=identity,
        identity_available=identity_available,
    )


@router.get("/workspace", response_model=WorkspaceStateResponse)
def read_companion_workspace(
    note_path: str = Query(..., description="Runtime-relative note path"),
) -> WorkspaceStateResponse:
    trace_id = uuid4().hex
    safe_note_path = _validate_workspace_note_path(note_path)
    vault_root = resolve_vault_root()
    artifact_path = _find_workspace_note(vault_root, safe_note_path)
    if artifact_path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "note_not_found",
                "message": "No note exists for the requested note_path",
                "note_path": safe_note_path,
                "trace_id": trace_id,
            },
        )

    body = artifact_path.read_text(encoding="utf-8")
    identity = resolve_note_artifact_identity(
        artifact_path=artifact_path,
        vault_root=vault_root,
        safe_note_path=safe_note_path,
        body=body,
    )
    if identity.identity_state == "healed":
        body = artifact_path.read_text(encoding="utf-8")
    canvas_enabled = _truthy_env("CANVAS_ENABLED")
    writeguard_status = _writeguard_status()
    workspace_update = _workspace_update_capability(
        canvas_enabled=canvas_enabled,
        writeguard_status=writeguard_status,
    )
    orientation_signals = get_orientation_signals()

    return WorkspaceStateResponse(
        artifact=ArtifactState(
            artifact_id=identity.artifact_id,
            artifact_kind=identity.artifact_kind,
            note_path=safe_note_path,
            title=_extract_title(body, fallback=artifact_path.stem),
            body=body,
            content_hash=_content_hash(body),
            identity_source=identity.identity_source,
            identity_state=identity.identity_state,
            companion_of=identity.companion_of,
            owns_identity=identity.owns_identity,
        ),
        runtime=RuntimeState(
            environment_label=_safe_environment_label(),
            api_base_url_label=_safe_api_label(),
            trace_id=trace_id,
            vault_identity=_vault_identity_state(vault_root),
            reorient=_reorient_state(signals=orientation_signals),
            resurface=_resurface_state(safe_note_path, signals=orientation_signals),
        ),
        canvas=_canvas_state(safe_note_path, vault_root, canvas_enabled),
        panel=_panel_state(identity.artifact_id),
        suggestions=SuggestionsState(),
        guards=GuardState(
            canvas_enabled=canvas_enabled,
            writeguard_status=writeguard_status,
            update_flow_available=workspace_update.available,
            degraded=not canvas_enabled or writeguard_status == "unknown",
            workspace_update=workspace_update,
        ),
    )


@router.post("/workspace/update", response_model=WorkspaceBodyUpdateResponse)
def update_companion_workspace_note_body(
    req: WorkspaceBodyUpdateRequest,
) -> WorkspaceBodyUpdateResponse:
    safe_active_note_path = _validate_workspace_markdown_note_path(req.active_note_path)
    safe_target_note_path = _validate_workspace_markdown_note_path(req.target_note_path)
    if safe_active_note_path != safe_target_note_path:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "active_note_scope_mismatch",
                "state": "blocked",
                "message": "Body update is scoped to the active note only.",
                "active_note_path": safe_active_note_path,
                "target_note_path": safe_target_note_path,
            },
        )

    vault_root = resolve_vault_root()
    note_path = _find_workspace_note(vault_root, safe_active_note_path)
    if note_path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "note_not_found",
                "state": "failure",
                "message": "No note exists for the requested active note path.",
                "note_path": safe_active_note_path,
            },
        )

    writeguard_status = _writeguard_status()
    workspace_update = _workspace_update_capability(
        canvas_enabled=_truthy_env("CANVAS_ENABLED"),
        writeguard_status=writeguard_status,
    )
    if not workspace_update.available:
        writeguard_blocked = workspace_update.reason == "writeguard_blocked"
        error = (
            "writeguard_blocked"
            if writeguard_blocked
            else "workspace_update_unavailable"
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": error,
                "state": "blocked",
                "message": (
                    "WriteGuard blocked active-note body update."
                    if writeguard_blocked
                    else "Workspace update capability is disabled for this runtime."
                ),
                "reason": workspace_update.reason,
            },
        )

    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.workspace.update.active_note_body")
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "writeguard_blocked",
                "state": "blocked",
                "message": str(exc),
                "reason": exc.reason,
            },
        ) from exc

    original_content = note_path.read_text(encoding="utf-8")
    content_hash_before = _content_hash(original_content)
    if req.content_hash is not None and req.content_hash != content_hash_before:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "content_hash_mismatch",
                "state": "failure",
                "message": "Active note changed since it was loaded; refresh before updating.",
                "content_hash_before": content_hash_before,
            },
        )

    new_content = _compose_note_with_preserved_frontmatter(
        original_content=original_content,
        new_body=req.new_body,
    )
    write_note_from_absolute(note_path, new_content, vault_root=vault_root)
    updated_content = note_path.read_text(encoding="utf-8")
    content_hash_after = _content_hash(updated_content)
    return WorkspaceBodyUpdateResponse(
        ok=True,
        state="success",
        note_path=safe_active_note_path,
        reason="active_note_body_updated",
        content_hash_before=content_hash_before,
        content_hash_after=content_hash_after,
    )


class BodyUpdateRequest(BaseModel):
    note_path: str
    new_body: str


class BodyUpdateResponse(BaseModel):
    status: str
    note_path: str
    content_hash: str


@router.post("/workspace/body", response_model=BodyUpdateResponse)
def update_workspace_body(req: BodyUpdateRequest) -> BodyUpdateResponse:
    if not _truthy_env("WORKSPACE_UPDATE_FLOW_ENABLED", default=False):
        raise HTTPException(
            status_code=403,
            detail={"error": "flow_disabled", "message": "WORKSPACE_UPDATE_FLOW_ENABLED is not set"},
        )
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.workspace.body")
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "writes_blocked", "message": str(exc)},
        ) from exc

    safe_note_path = _validate_workspace_markdown_note_path(req.note_path)
    vault_root = resolve_vault_root()
    note_path = _find_workspace_note(vault_root, safe_note_path)
    if note_path is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "note_not_found", "message": "No note exists for the requested note_path"},
        )

    if _body_contains_frontmatter(req.new_body):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "frontmatter_in_body",
                "message": "new_body must not contain a frontmatter block; frontmatter is governed separately",
            },
        )

    current = note_path.read_text(encoding="utf-8")
    frontmatter_block, _ = _split_frontmatter(current)
    if frontmatter_block is not None:
        new_content = f"---{frontmatter_block}\n---\n{req.new_body}"
    else:
        new_content = req.new_body if req.new_body.endswith("\n") else req.new_body + "\n"

    write_note_from_absolute(note_path, new_content, vault_root=vault_root)

    written = note_path.read_text(encoding="utf-8")
    return BodyUpdateResponse(
        status="ok",
        note_path=safe_note_path,
        content_hash=_content_hash(written),
    )


__all__ = ["router"]
