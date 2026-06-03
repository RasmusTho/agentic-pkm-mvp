"""Companion UI workspace endpoints: read aggregate, vault browser, body update."""

from __future__ import annotations

import datetime
import heapq
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

import yaml

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.agent_memory.posture_projection import (
    AgentMemoryPostureTarget,
    agent_memory_posture_for_artifacts,
)
from app.api.routes.artifacts import _content_hash, _extract_title
from app.chat.canvas_writer import _body_contains_frontmatter, _split_frontmatter
from app.config.paths import resolve_vault_root
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelEventSource,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.knowledge.write_ops import write_note_from_absolute
from app.observability.status_service import OrientationSignals, get_orientation_signals
from app.orientation.leave_point_cursor import latest_leave_point_projection
from app.orientation.runtime import build_orientation_frame
from app.panel.checkbox_projection import (
    PanelSelectableOption,
    extract_panel_selectable_options,
)
from app.panel.confirmation import StagedProposal
from app.receipts.artifact_receipts import ArtifactReceiptTarget, receipts_for_artifacts
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
    selectable_options: list[PanelSelectableOption] = Field(default_factory=list)


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


ORIENTATION_CONTRACT_VERSION = "workspace_orientation.v1"
ORIENTATION_OPEN_LOOPS_CAP = 8
ORIENTATION_NOTABLE_CHANGES_CAP = 8
ORIENTATION_RESURFACE_CANDIDATES_CAP = 5
ORIENTATION_MUTATION_INTENTS_CAP = 3
ORIENTATION_SOURCE_REFS_PER_ITEM_CAP = 3
ORIENTATION_STALE_AFTER_SECONDS = 300
ORIENTATION_MEMORY_INTENT_TRACE_EVENT_TYPE = "orientation.memory_candidate_intent.emitted.v1"
ORIENTATION_MEMORY_INTENT_TRACE_PATH_ENV = "MEMORY_INTENT_TRACE_PATH"
ORIENTATION_MEMORY_INTENT_TARGET_QUEUE = "agent_memory.review_queue"
ORIENTATION_MEMORY_INTENT_HANDOFF_HINT = "panel_governance_review"


_MEMORY_CANDIDATE_REVIEW_QUEUE = MemoryCandidateReviewQueue()


class WorkspaceOrientationScope(BaseModel):
    kind: Literal["workspace"] = "workspace"
    artifact_ref: dict[str, str | None] | None = None
    vault_id: str
    channel: str


class WorkspaceOrientationCaps(BaseModel):
    open_loops: int = ORIENTATION_OPEN_LOOPS_CAP
    notable_changes: int = ORIENTATION_NOTABLE_CHANGES_CAP
    resurface_candidates: int = ORIENTATION_RESURFACE_CANDIDATES_CAP
    mutation_intents: int = ORIENTATION_MUTATION_INTENTS_CAP
    source_refs_per_item: int = ORIENTATION_SOURCE_REFS_PER_ITEM_CAP


class WorkspaceOrientationMeta(BaseModel):
    contract_version: str = ORIENTATION_CONTRACT_VERSION
    as_of: str
    trace_id: str
    freshness: str
    stale_after: str
    degraded_reasons: list[str] = Field(default_factory=list)
    caps: WorkspaceOrientationCaps = Field(default_factory=WorkspaceOrientationCaps)


class WorkspaceOrientationSourceRef(BaseModel):
    kind: str
    ref: str
    label: str | None = None


class WorkspaceOrientationMemory(BaseModel):
    pending_candidate_count: int = 0
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationArtifactRef(BaseModel):
    artifact_uuid: str | None = None
    logical_ref: str | None = None
    title: str | None = None


class WorkspaceOrientationLeavePointSourceRef(BaseModel):
    kind: str | None = None
    trace_id: str | None = None


class WorkspaceOrientationLeavePoint(BaseModel):
    status: Literal["absent", "present", "stale", "artifact_missing", "degraded"] = "absent"
    artifact_ref: WorkspaceOrientationArtifactRef = Field(default_factory=WorkspaceOrientationArtifactRef)
    captured_at: str | None = None
    last_session_id: str | None = None
    authority_role: Literal["operational_trace_pointer", "derived_runtime_projection"] = "derived_runtime_projection"
    source_ref: WorkspaceOrientationLeavePointSourceRef = Field(default_factory=WorkspaceOrientationLeavePointSourceRef)


class WorkspaceOrientationOpenLoop(BaseModel):
    id: str
    label: str
    status: str
    handoff_hint: str
    artifact_ref: dict[str, str | None] | None = None
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationNotableChange(BaseModel):
    id: str
    label: str
    summary: str
    changed_at: str | None = None
    artifact_ref: dict[str, str | None] | None = None
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationResurfaceCandidate(BaseModel):
    id: str
    label: str
    why_now: str
    signal_labels: list[str] = Field(default_factory=list)
    artifact_ref: dict[str, str | None] | None = None
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationResurface(BaseModel):
    candidates: list[WorkspaceOrientationResurfaceCandidate] = Field(default_factory=list)


class WorkspaceOrientationGovernance(BaseModel):
    pending_proposal_count: int
    pending_receipt_count: int
    latest_receipt_outcome: str | None = None
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationGuards(BaseModel):
    read_only: bool = True
    runtime_posture: str
    degraded: bool
    reasons: list[str] = Field(default_factory=list)
    authority_role: str = "derived"
    source_ref: WorkspaceOrientationSourceRef


class WorkspaceOrientationMutationIntent(BaseModel):
    intent_id: str
    kind: Literal["MemoryCandidate"] = "MemoryCandidate"
    target_queue: str = ORIENTATION_MEMORY_INTENT_TARGET_QUEUE
    handoff_hint: str = ORIENTATION_MEMORY_INTENT_HANDOFF_HINT
    reason: str
    authority_role: Literal["reference"] = "reference"
    source_ref: WorkspaceOrientationSourceRef
    threshold_signals: list[str] = Field(default_factory=list)
    trace_id: str


class WorkspaceOrientationResponse(BaseModel):
    scope: WorkspaceOrientationScope
    meta: WorkspaceOrientationMeta
    leave_point: WorkspaceOrientationLeavePoint | None = None
    open_loops: list[WorkspaceOrientationOpenLoop] = Field(default_factory=list)
    notable_changes: list[WorkspaceOrientationNotableChange] = Field(default_factory=list)
    resurface: WorkspaceOrientationResurface
    memory: WorkspaceOrientationMemory
    governance: WorkspaceOrientationGovernance
    guards: WorkspaceOrientationGuards
    mutation_intents: list[WorkspaceOrientationMutationIntent] = Field(default_factory=list)


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


class VaultReceiptState(BaseModel):
    receipt_id: str
    trace_id: str | None = None
    action_id: str | None = None
    action_type: str | None = None
    artifact_uuid: str | None = None
    artifact_path: str | None = None
    path: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    status: str
    timestamp: str
    state: str


class VaultAgentMemoryPostureItemState(BaseModel):
    candidate_id: str
    title: str
    status: Literal["pending", "promoted", "rejected", "revised"]
    review_state: str
    memory_type: str
    inferred: bool
    source_refs: list[str] = Field(default_factory=list)
    derived_from: str | None = None
    generated_by: str | None = None
    revision_of: str | None = None


class VaultAgentMemoryPostureState(BaseModel):
    source: Literal["agent_memory.review_queue"] = "agent_memory.review_queue"
    authority: Literal["non_authoritative"] = "non_authoritative"
    state: Literal[
        "no_agent_memory",
        "pending",
        "promoted",
        "rejected",
        "revised",
        "mixed",
    ]
    counts: dict[str, int]
    items: list[VaultAgentMemoryPostureItemState] = Field(default_factory=list)


class VaultBrowserNoteState(BaseModel):
    note_path: str
    title: str
    zone: str
    # Zone projection envelope (#1488): where this zone came from, so the UI can distinguish a
    # durable frontmatter zone from a path-derived runtime projection. Additive to ``zone``.
    zone_source: str = "unavailable"
    zone_authority_role: str = "unavailable"
    zone_provenance: str = "unavailable"
    zone_degradation: str = "frontmatter_absent"
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
    receipts: list[VaultReceiptState] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    agent_memory_posture: VaultAgentMemoryPostureState | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class VaultBrowserPaginationState(BaseModel):
    mode: Literal["cursor"] = "cursor"
    cursor: str | None = None
    next_cursor: str | None = None
    previous_cursor: str | None = None
    page_size: int
    returned_notes: int
    total_filtered_notes: int
    has_next: bool
    has_previous: bool


class VaultBrowserStateResponse(BaseModel):
    notes: list[VaultBrowserNoteState]
    query: str
    total_notes: int
    filtered_notes: int
    read_only: bool = True
    vault_identity: VaultIdentityState
    identity_available: bool
    active_filters: dict[str, list[str]] = Field(default_factory=dict)
    pagination: VaultBrowserPaginationState


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


class VaultRelatedScopeState(BaseModel):
    note_path: str
    artifact_uuid: str | None = None


class VaultRelatedSignalState(BaseModel):
    signal: str
    value: str
    weight: int
    provenance: str


class VaultRelatedResultState(BaseModel):
    note_path: str
    title: str
    artifact_uuid: str | None = None
    kind: str | None = None
    zone: str | None = None
    data_mode: str = "read_only"
    ranking_score: int
    ranking_signals: list[VaultRelatedSignalState]


class VaultRelatedResponse(BaseModel):
    scope: VaultRelatedScopeState
    results: list[VaultRelatedResultState]
    read_only: bool = True
    data_mode: str = "read_only"
    vault_identity: VaultIdentityState
    identity_available: bool


class VaultBrowserQueueReviewRequest(BaseModel):
    note_path: str | None = None
    artifact_uuid: str | None = None


class VaultBrowserQueueReviewResponse(BaseModel):
    intent_id: str
    proposal_id: str
    artifact_id: str
    artifact_uuid: str | None = None
    note_path: str
    state: Literal["pending_intent"] = "pending_intent"
    action_type: Literal["note_lifecycle"] = "note_lifecycle"
    operation: Literal["queue_review"] = "queue_review"
    receipt_state: Literal["pending_intent_not_durable_receipt"] = (
        "pending_intent_not_durable_receipt"
    )
    execution_path: Literal["/api/panel/confirm"] = "/api/panel/confirm"
    data_mode: Literal["governance_write"] = "governance_write"
    requires_confirmation: bool = True
    requires_receipt: bool = True


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
    # Strip any URL fragment / section anchor — the canonical note identity never
    # includes a "#section" suffix; a leaked anchor must not turn a valid edit
    # into a confusing 404 (#1447). Obsidian note filenames cannot contain '#'.
    note_path_raw = (note_path_raw or "").split("#", 1)[0]
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
    """Resolve a validated note path while preserving direct lookup latency.

    Workspace reads are restricted to markdown notes. The direct O(1) lookup
    replaced an earlier ``rglob("*.md")`` scan that was implicitly
    markdown-only; without this suffix guard a read such as
    ``note_path=attachments/private.txt`` would surface arbitrary non-note vault
    content (the GET read path validates with ``_validate_workspace_note_path``,
    not the ``.md``-enforcing validator used by write endpoints).
    """
    if not safe_note_path.endswith(".md"):
        return None
    root_real = os.path.realpath(vault_root)
    target_real = os.path.realpath(os.path.join(root_real, safe_note_path))
    if not target_real.startswith(root_real + os.sep):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "path_escape",
                "message": "Resolved note path is outside the vault.",
            },
        )
    if not os.path.isfile(target_real):
        return None
    return Path(target_real)


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


def _panel_state(
    artifact_id: str | None,
    selectable_options: list[PanelSelectableOption] | None = None,
) -> PanelState:
    options = list(selectable_options or [])
    proposal_count = _proposal_count_for_artifact(artifact_id)
    selectable_count = sum(1 for option in options if option.selectable)
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
    elif proposal_count or selectable_count:
        state = "proposals-staged"
    elif latest_outcome == "success":
        state = "receipt-displayed"
    else:
        state = "idle"
    return PanelState(
        state=state,
        proposal_count=proposal_count + selectable_count,
        receipt_count=len(relevant),
        latest_receipt_outcome=latest_outcome,
        blocked_reason=blocked_reason,
        no_match_reason=None,
        selectable_options=options,
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
        item(loop, panel_handoff=True)
        for loop in frame.explanation.open_items
        if not loop.startswith("No unresolved")
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


def _orientation_iso(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _orientation_source_ref(kind: str, ref: str, label: str | None = None) -> WorkspaceOrientationSourceRef:
    return WorkspaceOrientationSourceRef(kind=kind, ref=ref, label=label)


def _orientation_memory_review_queue() -> MemoryCandidateReviewQueue:
    return _MEMORY_CANDIDATE_REVIEW_QUEUE


def _orientation_memory_summary() -> WorkspaceOrientationMemory:
    pending = len(_orientation_memory_review_queue().pending())
    return WorkspaceOrientationMemory(
        pending_candidate_count=pending,
        source_ref=_orientation_source_ref(
            "agent_memory.review_queue",
            ORIENTATION_MEMORY_INTENT_TARGET_QUEUE,
            "memory candidate review queue",
        ),
    )


def _orientation_item_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index + 1}"


def _orientation_leave_point(
    signals: OrientationSignals,
    *,
    frame_label: str | None,
    identity: VaultIdentityState,
) -> WorkspaceOrientationLeavePoint:
    projection = latest_leave_point_projection(
        vault_id=identity.vault_name,
        channel=identity.channel,
        vault_root=resolve_vault_root(),
        derived_label=frame_label,
        derived_at=_orientation_iso(signals.ingestion.last_run_at),
    )
    return WorkspaceOrientationLeavePoint(
        status=projection.status,
        artifact_ref=WorkspaceOrientationArtifactRef(
            artifact_uuid=projection.artifact_ref.artifact_uuid,
            logical_ref=projection.artifact_ref.logical_ref,
            title=projection.artifact_ref.title,
        ),
        captured_at=projection.captured_at,
        last_session_id=projection.last_session_id,
        authority_role=projection.authority_role,
        source_ref=WorkspaceOrientationLeavePointSourceRef(
            kind=projection.source_ref.kind,
            trace_id=projection.source_ref.trace_id,
        ),
    )


def _orientation_open_loops(open_items: list[str]) -> list[WorkspaceOrientationOpenLoop]:
    loops: list[WorkspaceOrientationOpenLoop] = []
    unresolved_items = [
        label
        for label in open_items
        if not label.startswith("No unresolved")
    ][:ORIENTATION_OPEN_LOOPS_CAP]
    for index, label in enumerate(unresolved_items):
        loops.append(
            WorkspaceOrientationOpenLoop(
                id=_orientation_item_id("open-loop", index),
                label=label,
                status="open",
                handoff_hint="panel",
                source_ref=_orientation_source_ref(
                    "runtime_signal",
                    "orientation.open_items",
                    "orientation open items",
                ),
            )
        )
    return loops


def _orientation_notable_changes(
    signals: OrientationSignals,
    *,
    label: str,
) -> list[WorkspaceOrientationNotableChange]:
    return [
        WorkspaceOrientationNotableChange(
            id="notable-change-1",
            label=label,
            summary=label,
            changed_at=_orientation_iso(signals.ingestion.last_run_at),
            source_ref=_orientation_source_ref(
                "runtime_signal",
                "orientation.notable_change",
                "orientation notable change",
            ),
        )
    ][:ORIENTATION_NOTABLE_CHANGES_CAP]


def _orientation_resurface_source_ref(candidate_id: str) -> WorkspaceOrientationSourceRef:
    source_link = _safe_resurface_source_link(candidate_id)
    kind = "runtime_signal" if source_link.startswith("status.") else "derived"
    return _orientation_source_ref(kind, source_link, "resurfacing signal")


def _orientation_resurface_candidates(signals: OrientationSignals) -> list[WorkspaceOrientationResurfaceCandidate]:
    evaluation = evaluate_resurfacing_candidates(signals=signals)
    candidates: list[WorkspaceOrientationResurfaceCandidate] = []
    for candidate in evaluation.candidates[:ORIENTATION_RESURFACE_CANDIDATES_CAP]:
        signal_labels = [
            f"{signal.name}={signal.value}"
            for signal in candidate.why_now.signals[:ORIENTATION_SOURCE_REFS_PER_ITEM_CAP]
        ]
        candidates.append(
            WorkspaceOrientationResurfaceCandidate(
                id=candidate.candidate_id,
                label=candidate.label,
                why_now=candidate.why_now.explanation,
                signal_labels=signal_labels,
                source_ref=_orientation_resurface_source_ref(candidate.candidate_id),
            )
        )
    return candidates


_ORIENTATION_MEMORY_SIGNAL_CATEGORIES = {
    "pending_promotions": "promotion_backlog",
    "promote_created_total": "promotion_backlog",
    "promotion_executed_total": "promotion_backlog",
    "worker_queue_pending": "worker_queue",
    "watcher_runs_24h": "watcher_activity",
    "promote_created_24h": "promotion_activity",
}


def _orientation_memory_signal_category(signal_label: str) -> str | None:
    signal_name = signal_label.split("=", 1)[0].strip()
    return _ORIENTATION_MEMORY_SIGNAL_CATEGORIES.get(signal_name)


def _orientation_memory_threshold_signals(
    candidate: WorkspaceOrientationResurfaceCandidate,
) -> list[str]:
    threshold_signals: list[str] = []
    seen: set[str] = set()
    for signal_label in candidate.signal_labels:
        category = _orientation_memory_signal_category(signal_label)
        if category is None or category in seen:
            continue
        seen.add(category)
        threshold_signals.append(signal_label)
        if len(threshold_signals) >= ORIENTATION_SOURCE_REFS_PER_ITEM_CAP:
            break
    return threshold_signals


def _orientation_memory_intent_trace_path() -> Path:
    configured = (os.getenv(ORIENTATION_MEMORY_INTENT_TRACE_PATH_ENV) or "").strip()
    if configured:
        return Path(configured)
    return Path("runtime") / "orientation-memory-intents.jsonl"


def _append_orientation_memory_intent_trace(
    intent: WorkspaceOrientationMutationIntent,
    *,
    emitted_at: datetime.datetime,
) -> None:
    trace_path = _orientation_memory_intent_trace_path()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event_type": ORIENTATION_MEMORY_INTENT_TRACE_EVENT_TYPE,
        "event_id": f"{intent.intent_id}:{intent.trace_id}",
        "trace_id": intent.trace_id,
        "source_ref": intent.source_ref.model_dump(),
        "threshold_signals": list(intent.threshold_signals),
        "intent_id": intent.intent_id,
        "emitted_at": _orientation_iso(emitted_at) or emitted_at.isoformat(),
        "target_queue": intent.target_queue,
    }
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _orientation_memory_mutation_intents(
    candidates: list[WorkspaceOrientationResurfaceCandidate],
    *,
    trace_id: str,
    emitted_at: datetime.datetime,
) -> list[WorkspaceOrientationMutationIntent]:
    intents: list[WorkspaceOrientationMutationIntent] = []
    for candidate in candidates:
        if len(intents) >= ORIENTATION_MUTATION_INTENTS_CAP:
            break
        threshold_signals = _orientation_memory_threshold_signals(candidate)
        if len(threshold_signals) < 2:
            continue
        if not candidate.authority_role or not candidate.source_ref.ref:
            continue
        intent = WorkspaceOrientationMutationIntent(
            intent_id=f"memory-candidate-intent-{candidate.id}",
            reason=(
                "Review queue handoff suggested by multiple independent runtime "
                "signals; orientation carries references only and creates no candidate."
            ),
            source_ref=candidate.source_ref,
            threshold_signals=threshold_signals,
            trace_id=trace_id,
        )
        _append_orientation_memory_intent_trace(intent, emitted_at=emitted_at)
        intents.append(intent)
    return intents


def _orientation_governance_summary() -> WorkspaceOrientationGovernance:
    proposals = getattr(confirm_module._proposal_store, "_proposals", {})
    receipts = getattr(confirm_module._idempotency_store, "_cache", {})
    receipt_values = list(receipts.values()) if isinstance(receipts, dict) else []
    latest = receipt_values[-1] if receipt_values else None
    latest_outcome = getattr(latest, "outcome", None) if latest is not None else None
    source_kind = "receipt" if receipt_values else "runtime_signal"
    source_ref = "panel.receipts" if receipt_values else "panel.governance_summary"
    return WorkspaceOrientationGovernance(
        pending_proposal_count=len(proposals) if isinstance(proposals, dict) else 0,
        pending_receipt_count=len(receipt_values),
        latest_receipt_outcome=latest_outcome,
        source_ref=_orientation_source_ref(
            source_kind,
            source_ref,
            "governance summary",
        ),
    )


def _orientation_identity() -> VaultIdentityState:
    return _vault_identity_state(resolve_vault_root())


def _orientation_error(trace_id: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "runtime_unavailable",
            "message": message,
            "trace_id": trace_id,
            "contract_version": ORIENTATION_CONTRACT_VERSION,
        },
    )


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


def _zone_projection_envelope(
    *, zone: str, path_derived_zone: str, frontmatter_zone_used: bool, frontmatter_invalid: bool
) -> dict:
    """Describe where an artifact's ``zone`` came from per the #1488 topology decision.

    Every topology-derived Vault Browser field must carry ``source`` / ``authority_role`` /
    ``provenance`` / ``degradation`` so a durable, human-authored zone is distinguishable from a
    path-derived fallback (``docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`` → "Runtime topology authority
    decision (#1488)"). This is additive metadata over the existing source — no new topology source.
    """
    if frontmatter_zone_used:
        return {
            "zone_source": "frontmatter.zone",
            "zone_authority_role": "durable_vault_metadata",
            "zone_provenance": "frontmatter.zone",
            "zone_degradation": "none",
        }
    degradation = "frontmatter_invalid" if frontmatter_invalid else "frontmatter_absent"
    if not zone:
        # Neither frontmatter nor a path segment yielded a zone — never fabricate one.
        return {
            "zone_source": "unavailable",
            "zone_authority_role": "unavailable",
            "zone_provenance": "unavailable",
            "zone_degradation": degradation,
        }
    return {
        "zone_source": "vault_path_segment",
        "zone_authority_role": "runtime_projection",
        "zone_provenance": f"vault_path[0]={path_derived_zone}",
        "zone_degradation": degradation,
    }


def _parse_note_artifact_metadata(body: str, *, path_derived_zone: str) -> dict:
    """Parse frontmatter from a note body and return normalized artifact metadata.

    Server-side only — clients must never parse raw YAML.
    Returns a dict with all VaultBrowserNoteState metadata fields populated.
    Missing YAML or malformed YAML → frontmatter_valid=False + missing_required_fields.
    The ``zone_*`` envelope describes the zone source/authority/provenance/degradation (#1488).
    """
    fm_inner, _ = _split_frontmatter(body)
    if fm_inner is None:
        return {
            "uuid": None,
            "kind": None,
            "zone": path_derived_zone,
            **_zone_projection_envelope(
                zone=path_derived_zone,
                path_derived_zone=path_derived_zone,
                frontmatter_zone_used=False,
                frontmatter_invalid=False,
            ),
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
    frontmatter_zone_used = bool(fm_zone)
    zone = str(fm_zone).strip() if fm_zone else path_derived_zone

    return {
        "uuid": normalized_uuid,
        "kind": _str_or_none(fm.get("kind")),
        "zone": zone,
        **_zone_projection_envelope(
            zone=zone,
            path_derived_zone=path_derived_zone,
            frontmatter_zone_used=frontmatter_zone_used,
            frontmatter_invalid=parse_error,
        ),
        "review_state": _str_or_none(fm.get("review_state")),
        "trust": _str_or_none(fm.get("trust")),
        "origin": _str_or_none(fm.get("origin")),
        "source_ref": _str_or_none(fm.get("source_ref")),
        "created": _timestamp_str_or_none(fm.get("created")),
        "updated": _timestamp_str_or_none(fm.get("updated")),
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


def _timestamp_str_or_none(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return _format_timestamp_datetime(val)
    if isinstance(val, datetime.date):
        return val.isoformat()
    s = str(val).strip()
    if not s:
        return None
    return _normalize_timestamp_string(s)


def _normalize_timestamp_string(value: str) -> str:
    if not any(separator in value for separator in ("T", "t", " ")):
        return value
    parse_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(parse_value)
    except ValueError:
        return value
    if parsed.tzinfo is not None and parsed.utcoffset() != datetime.timedelta(0):
        return value
    return _format_timestamp_datetime(parsed)


def _format_timestamp_datetime(value: datetime.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.isoformat()
    if value.utcoffset() != datetime.timedelta(0):
        return value.isoformat()
    utc_value = value.astimezone(datetime.timezone.utc)
    iso_value = utc_value.isoformat()
    return f"{iso_value[:-6]}Z" if iso_value.endswith("+00:00") else iso_value


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
    cursor: str | None = None,
    filters: dict[str, list[str]] | None = None,
) -> tuple[list[VaultBrowserNoteState], int, int, bool, str | None]:
    needle = query.strip().lower()
    cursor_path = str(cursor or "").strip() or None
    active_filters = filters or {}
    total_notes = 0
    filtered_notes = 0
    page_window_limit = limit + 1
    # Keep only the lexicographically-smallest page window without
    # materializing the full sorted collection in memory.
    selected_heap: list[tuple[str, VaultBrowserNoteState]] = []
    previous_cursor_heap: list[str] = []
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
            zone_source=metadata["zone_source"],
            zone_authority_role=metadata["zone_authority_role"],
            zone_provenance=metadata["zone_provenance"],
            zone_degradation=metadata["zone_degradation"],
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
        if cursor_path is not None and note.note_path <= cursor_path:
            heapq.heappush(previous_cursor_heap, note.note_path)
            if len(previous_cursor_heap) > limit + 1:
                heapq.heappop(previous_cursor_heap)
            continue
        key = note.note_path
        if len(selected_heap) < page_window_limit:
            heapq.heappush(selected_heap, (_invert_lex(key), note))
        elif _invert_lex(key) > selected_heap[0][0]:
            heapq.heapreplace(selected_heap, (_invert_lex(key), note))

    selected = sorted((item[1] for item in selected_heap), key=lambda note: note.note_path)
    previous_window = sorted(previous_cursor_heap)
    previous_cursor = previous_window[0] if len(previous_window) > limit else None
    return selected[:limit], total_notes, filtered_notes, len(selected) > limit, previous_cursor


def _vault_browser_pagination(
    *,
    notes: list[VaultBrowserNoteState],
    cursor: str | None,
    limit: int,
    filtered_notes: int,
    has_next: bool,
    previous_cursor: str | None,
) -> VaultBrowserPaginationState:
    return VaultBrowserPaginationState(
        cursor=str(cursor).strip() if cursor else None,
        next_cursor=notes[-1].note_path if has_next else None,
        previous_cursor=previous_cursor,
        page_size=limit,
        returned_notes=len(notes),
        total_filtered_notes=filtered_notes,
        has_next=has_next,
        has_previous=bool(cursor),
    )


def _attach_receipts_to_notes(
    notes: list[VaultBrowserNoteState],
    *,
    vault_root: Path,
) -> list[VaultBrowserNoteState]:
    projection = receipts_for_artifacts(
        [
            ArtifactReceiptTarget(
                artifact_uuid=note.uuid,
                note_path=note.note_path,
            )
            for note in notes
        ],
        vault_root=vault_root,
    )
    if projection is None:
        return notes
    return [
        note.model_copy(
            update={
                "receipts": [
                    VaultReceiptState.model_validate(receipt)
                    for receipt in projection.get(note.note_path, [])
                ]
            }
        )
        for note in notes
    ]


def _attach_agent_memory_posture_to_notes(
    notes: list[VaultBrowserNoteState],
    *,
    vault_root: Path,
) -> list[VaultBrowserNoteState]:
    projection = agent_memory_posture_for_artifacts(
        [
            AgentMemoryPostureTarget(
                artifact_uuid=note.uuid,
                note_path=note.note_path,
            )
            for note in notes
        ],
        queue=_orientation_memory_review_queue(),
        vault_root=vault_root,
    )
    if projection is None:
        return notes
    return [
        note.model_copy(
            update={
                "agent_memory_posture": VaultAgentMemoryPostureState.model_validate(
                    projection[note.note_path]
                )
            }
        )
        for note in notes
    ]


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


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _normalize_relation_token(value: str) -> str:
    token = str(value or "").strip()
    if "|" in token:
        token = token.split("|", 1)[0]
    if "#" in token:
        token = token.split("#", 1)[0]
    token = token.strip()
    if token.endswith(".md"):
        token = token[:-3]
    return token.lower()


def _wikilink_targets(body: str) -> set[str]:
    targets: set[str] = set()
    for match in _WIKILINK_RE.finditer(body):
        token = _normalize_relation_token(match.group(1))
        if token:
            targets.add(token)
    return targets


def _coerce_relation_tags(raw: object) -> set[str]:
    if raw is None:
        return set()
    values: list[object]
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, tuple | set):
        values = list(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            values = [part.strip().strip('"').strip("'") for part in stripped[1:-1].split(",")]
        elif "," in stripped:
            values = [part.strip() for part in stripped.split(",")]
        else:
            values = [stripped]
    else:
        values = [raw]
    return {
        str(value).strip().lstrip("#").lower()
        for value in values
        if str(value).strip()
    }


def _frontmatter_dict(body: str) -> dict:
    fm_inner, _ = _split_frontmatter(body)
    if fm_inner is None:
        return {}
    try:
        raw = yaml.safe_load(fm_inner) or {}
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _collect_relation_notes(vault_root: Path) -> list[dict[str, object]]:
    notes: list[dict[str, object]] = []
    if not vault_root.exists():
        return notes
    for candidate in vault_root.rglob("*.md"):
        if not candidate.is_file():
            continue
        safe_path = _vault_relative(candidate, vault_root)
        if safe_path is None or _is_hidden_browser_path(safe_path):
            continue
        try:
            body = candidate.read_text(encoding="utf-8")
        except Exception:
            continue
        path_zone = _zone_for_path(safe_path)
        metadata = _parse_note_artifact_metadata(body, path_derived_zone=path_zone)
        frontmatter = _frontmatter_dict(body)
        tags = _coerce_relation_tags(frontmatter.get("tags") or frontmatter.get("tag"))
        title = _browser_title(body, fallback=candidate.stem)
        notes.append(
            {
                "note_path": safe_path,
                "title": title,
                "artifact_uuid": metadata["uuid"],
                "kind": metadata["kind"],
                "zone": metadata["zone"],
                "source_ref": metadata["source_ref"],
                "tags": tags,
                "wikilink_targets": _wikilink_targets(body),
            }
        )
    return notes


def _relation_link_keys(note: dict[str, object]) -> set[str]:
    note_path = str(note.get("note_path") or "")
    title = str(note.get("title") or "")
    uuid = str(note.get("artifact_uuid") or "")
    path = PurePosixPath(note_path)
    candidates = {
        note_path,
        note_path.removesuffix(".md"),
        path.name,
        path.name.removesuffix(".md"),
        title,
        uuid,
    }
    return {
        _normalize_relation_token(value)
        for value in candidates
        if str(value).strip()
    }


def _resolve_related_scope(
    notes: list[dict[str, object]],
    *,
    note_path: str | None,
    artifact_uuid: str | None,
) -> dict[str, object]:
    target: dict[str, object] | None = None
    if note_path:
        target = next((note for note in notes if note.get("note_path") == note_path), None)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "artifact_not_found",
                    "message": "No vault note exists for the requested note_path.",
                    "note_path": note_path,
                },
            )
    if artifact_uuid:
        uuid_match = next(
            (note for note in notes if note.get("artifact_uuid") == artifact_uuid),
            None,
        )
        if uuid_match is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "artifact_not_found",
                    "message": "No vault note exists for the requested artifact_uuid.",
                    "artifact_uuid": artifact_uuid,
                },
            )
        if target is not None and target.get("note_path") != uuid_match.get("note_path"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "artifact_scope_mismatch",
                    "message": "note_path and artifact_uuid identify different artifacts.",
                    "note_path": note_path,
                    "artifact_uuid": artifact_uuid,
                },
            )
        target = uuid_match
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "artifact_scope_required",
                "message": "Provide note_path and/or artifact_uuid for artifact-scoped Find.",
            },
        )
    return target


def _resolve_vault_action_scope(
    notes: list[dict[str, object]],
    *,
    note_path: str | None,
    artifact_uuid: str | None,
    action_name: str,
) -> dict[str, object]:
    target: dict[str, object] | None = None
    if note_path:
        target = next((note for note in notes if note.get("note_path") == note_path), None)
        if target is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "artifact_not_found",
                    "message": f"No vault note exists for the requested {action_name} note_path.",
                    "note_path": note_path,
                },
            )
    if artifact_uuid:
        uuid_match = next(
            (note for note in notes if note.get("artifact_uuid") == artifact_uuid),
            None,
        )
        if uuid_match is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "artifact_not_found",
                    "message": f"No vault note exists for the requested {action_name} artifact_uuid.",
                    "artifact_uuid": artifact_uuid,
                },
            )
        if target is not None and target.get("note_path") != uuid_match.get("note_path"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "artifact_scope_mismatch",
                    "message": "note_path and artifact_uuid identify different artifacts.",
                    "note_path": note_path,
                    "artifact_uuid": artifact_uuid,
                },
            )
        target = uuid_match
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "artifact_scope_required",
                "message": f"Provide note_path and/or artifact_uuid for {action_name}.",
            },
        )
    return target


def _stage_queue_review_panel_proposal(target: dict[str, object]) -> str:
    note_path = str(target.get("note_path") or "").strip()
    artifact_uuid = _str_or_none(target.get("artifact_uuid"))
    artifact_id = artifact_uuid or note_path
    proposal_id = uuid4().hex
    payload = {
        "operation": "queue_review",
        "note_path": note_path,
        "artifact_uuid": artifact_uuid,
        "source": "vault_browser",
    }
    intent_event = PanelIntentEvent(
        source=PanelEventSource(component="vault_browser", trigger="queue_review"),
        trace_id=proposal_id,
        payload=PanelIntentPayload(
            note=NoteRef(
                uuid=artifact_id,
                path=note_path,
                origin="vault_browser/queue_review",
            ),
            panel=PanelInfo(
                panel_id=proposal_id,
                instruction="vault browser governance: queue_review",
            ),
            actions=[
                PanelIntentAction(
                    id=proposal_id,
                    label="Queue for review",
                    checked=True,
                    mapping=PanelActionMapping(
                        id="queue_review",
                        intent_type="note_lifecycle",
                        downstream_event="panel.governance.requested",
                        trust_verb="APPLY",
                        params=payload,
                    ),
                )
            ],
        ),
    )
    confirm_module._proposal_store.stage(
        proposal_id,
        StagedProposal(
            artifact_id=artifact_id,
            intent_event=intent_event,
            trace_id=proposal_id,
        ),
    )
    return proposal_id


def _signal(signal: str, value: str, *, weight: int, provenance: str) -> dict[str, object]:
    return {
        "signal": signal,
        "value": value,
        "weight": weight,
        "provenance": provenance,
    }


def _related_signals(
    target: dict[str, object],
    candidate: dict[str, object],
) -> list[dict[str, object]]:
    target_path = str(target.get("note_path") or "")
    candidate_path = str(candidate.get("note_path") or "")
    target_keys = _relation_link_keys(target)
    candidate_keys = _relation_link_keys(candidate)
    target_links = target.get("wikilink_targets") or set()
    candidate_links = candidate.get("wikilink_targets") or set()
    target_tags = target.get("tags") or set()
    candidate_tags = candidate.get("tags") or set()
    signals: list[dict[str, object]] = []

    if isinstance(target_links, set) and target_links.intersection(candidate_keys):
        signals.append(
            _signal(
                "wikilink_outlink",
                candidate_path,
                weight=100,
                provenance=f"{target_path} wikilinks to candidate",
            )
        )
    if isinstance(candidate_links, set) and candidate_links.intersection(target_keys):
        signals.append(
            _signal(
                "wikilink_backlink",
                target_path,
                weight=100,
                provenance=f"{candidate_path} wikilinks to scope artifact",
            )
        )
    if isinstance(target_tags, set) and isinstance(candidate_tags, set):
        for tag in sorted(target_tags.intersection(candidate_tags)):
            signals.append(
                _signal(
                    "shared_tag",
                    tag,
                    weight=30,
                    provenance="frontmatter.tags",
                )
            )
    target_source = str(target.get("source_ref") or "")
    candidate_source = str(candidate.get("source_ref") or "")
    target_uuid = str(target.get("artifact_uuid") or "")
    candidate_uuid = str(candidate.get("artifact_uuid") or "")
    if candidate_source and candidate_source in {target_path, target_uuid}:
        signals.append(
            _signal(
                "source_ref_points_to_scope",
                candidate_source,
                weight=80,
                provenance=f"{candidate_path} frontmatter.source_ref",
            )
        )
    if target_source and target_source in {candidate_path, candidate_uuid}:
        signals.append(
            _signal(
                "scope_source_ref_points_to_candidate",
                target_source,
                weight=80,
                provenance=f"{target_path} frontmatter.source_ref",
            )
        )
    if target_source and candidate_source and target_source == candidate_source:
        signals.append(
            _signal(
                "shared_source_ref",
                target_source,
                weight=60,
                provenance="frontmatter.source_ref",
            )
        )
    target_zone = str(target.get("zone") or "")
    candidate_zone = str(candidate.get("zone") or "")
    if target_zone and candidate_zone and target_zone == candidate_zone:
        signals.append(
            _signal(
                "shared_zone",
                target_zone,
                weight=10,
                provenance="frontmatter.zone/path zone",
            )
        )
    return signals


def _rank_related_notes(
    target: dict[str, object],
    notes: list[dict[str, object]],
    *,
    limit: int,
) -> list[VaultRelatedResultState]:
    results: list[VaultRelatedResultState] = []
    target_path = target.get("note_path")
    for candidate in notes:
        if candidate.get("note_path") == target_path:
            continue
        signals = _related_signals(target, candidate)
        if not signals:
            continue
        ranking_score = sum(int(signal["weight"]) for signal in signals)
        results.append(
            VaultRelatedResultState(
                note_path=str(candidate.get("note_path") or ""),
                title=str(candidate.get("title") or ""),
                artifact_uuid=_str_or_none(candidate.get("artifact_uuid")),
                kind=_str_or_none(candidate.get("kind")),
                zone=_str_or_none(candidate.get("zone")),
                ranking_score=ranking_score,
                ranking_signals=[
                    VaultRelatedSignalState.model_validate(signal)
                    for signal in signals
                ],
            )
        )
    results.sort(key=lambda result: (-result.ranking_score, result.note_path))
    return results[:limit]


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
    cursor: str | None = Query(None, description="Cursor note_path from the prior page"),
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
    selected, total_notes, filtered_notes, has_next_page, previous_cursor = _select_vault_notes(
        vault_root,
        query=q,
        limit=effective_limit,
        cursor=cursor,
        filters=active_filters,
    )
    pagination = _vault_browser_pagination(
        notes=selected,
        cursor=cursor,
        limit=effective_limit,
        filtered_notes=filtered_notes,
        has_next=has_next_page,
        previous_cursor=previous_cursor,
    )
    selected = _attach_receipts_to_notes(selected, vault_root=vault_root)
    selected = _attach_agent_memory_posture_to_notes(selected, vault_root=vault_root)
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
        pagination=pagination,
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


@router.get("/vault-related", response_model=VaultRelatedResponse)
def read_companion_vault_related(
    note_path: str | None = Query(
        default=None,
        description="Vault-relative markdown note path to use as the Find scope.",
    ),
    artifact_uuid: str | None = Query(
        default=None,
        description="Artifact UUID to use as the Find scope.",
    ),
    limit: int = Query(10, ge=1, le=50),
) -> VaultRelatedResponse:
    """Return deterministic, read-only related artifacts for one vault artifact.

    This intentionally does not reuse ``/search`` because that route is text /
    embedding search. Vault Browser ``find_related`` requires artifact scope and
    surfaced ranking/provenance signals so Browse and Find remain separate.
    """
    if note_path is None and artifact_uuid is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "artifact_scope_required",
                "message": "Provide note_path and/or artifact_uuid for artifact-scoped Find.",
            },
        )
    safe_note_path = (
        _validate_workspace_markdown_note_path(note_path)
        if note_path is not None
        else None
    )
    safe_artifact_uuid = artifact_uuid.strip() if artifact_uuid else None
    vault_root = resolve_vault_root()
    notes = _collect_relation_notes(vault_root)
    target = _resolve_related_scope(
        notes,
        note_path=safe_note_path,
        artifact_uuid=safe_artifact_uuid,
    )
    identity = _vault_identity_state(vault_root)
    identity_available = (
        bool(identity.vault_name.strip()) and identity.channel in {"dev", "test", "prod"}
    )
    target_note_path = str(target.get("note_path") or "")
    target_uuid = _str_or_none(target.get("artifact_uuid"))
    return VaultRelatedResponse(
        scope=VaultRelatedScopeState(
            note_path=target_note_path,
            artifact_uuid=target_uuid,
        ),
        results=_rank_related_notes(target, notes, limit=limit),
        read_only=True,
        data_mode="read_only",
        vault_identity=identity,
        identity_available=identity_available,
    )


@router.post(
    "/vault-browser/actions/queue-review",
    response_model=VaultBrowserQueueReviewResponse,
)
def queue_vault_browser_review(
    req: VaultBrowserQueueReviewRequest,
) -> VaultBrowserQueueReviewResponse:
    safe_note_path = (
        _validate_workspace_markdown_note_path(req.note_path)
        if req.note_path is not None
        else None
    )
    safe_artifact_uuid = req.artifact_uuid.strip() if req.artifact_uuid else None
    vault_root = resolve_vault_root()
    target = _resolve_vault_action_scope(
        _collect_relation_notes(vault_root),
        note_path=safe_note_path,
        artifact_uuid=safe_artifact_uuid,
        action_name="queue_review",
    )
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.vault_browser.queue_review")
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

    proposal_id = _stage_queue_review_panel_proposal(target)
    note_path = str(target.get("note_path") or "")
    artifact_uuid = _str_or_none(target.get("artifact_uuid"))
    artifact_id = artifact_uuid or note_path
    return VaultBrowserQueueReviewResponse(
        intent_id=proposal_id,
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        artifact_uuid=artifact_uuid,
        note_path=note_path,
    )


@router.get("/orientation", response_model=WorkspaceOrientationResponse)
def read_companion_orientation() -> WorkspaceOrientationResponse:
    trace_id = uuid4().hex
    generated_at = datetime.datetime.now(datetime.timezone.utc)
    stale_after = generated_at + datetime.timedelta(seconds=ORIENTATION_STALE_AFTER_SECONDS)

    try:
        identity = _orientation_identity()
        orientation_signals = get_orientation_signals()
    except HTTPException:
        raise
    except Exception as exc:
        raise _orientation_error(
            trace_id,
            "The workspace orientation source could not be reached",
        ) from exc

    degraded_reasons: list[str] = []
    leave_point: WorkspaceOrientationLeavePoint | None = None
    open_loops: list[WorkspaceOrientationOpenLoop] = []
    notable_changes: list[WorkspaceOrientationNotableChange] = []
    resurface_candidates: list[WorkspaceOrientationResurfaceCandidate] = []
    mutation_intents: list[WorkspaceOrientationMutationIntent] = []

    try:
        frame = build_orientation_frame(signals=orientation_signals)
        leave_point = _orientation_leave_point(
            orientation_signals,
            frame_label=frame.explanation.leave_point,
            identity=identity,
        )
        open_loops = _orientation_open_loops(frame.explanation.open_items)
        notable_changes = _orientation_notable_changes(
            orientation_signals,
            label=frame.explanation.notable_change,
        )
    except Exception:
        degraded_reasons.append("orientation_source_unavailable")

    try:
        resurface_candidates = _orientation_resurface_candidates(orientation_signals)
    except Exception:
        degraded_reasons.append("resurfacing_source_unavailable")

    try:
        memory = _orientation_memory_summary()
    except Exception:
        degraded_reasons.append("memory_source_unavailable")
        memory = WorkspaceOrientationMemory(
            pending_candidate_count=0,
            source_ref=_orientation_source_ref(
                "derived",
                "unavailable",
                "memory source unavailable",
            ),
        )

    try:
        mutation_intents = _orientation_memory_mutation_intents(
            resurface_candidates,
            trace_id=trace_id,
            emitted_at=generated_at,
        )
    except Exception:
        degraded_reasons.append("memory_intent_trace_unavailable")

    try:
        governance = _orientation_governance_summary()
    except Exception:
        degraded_reasons.append("governance_source_unavailable")
        governance = WorkspaceOrientationGovernance(
            pending_proposal_count=0,
            pending_receipt_count=0,
            latest_receipt_outcome=None,
            source_ref=_orientation_source_ref(
                "derived",
                "unavailable",
                "governance source unavailable",
            ),
        )

    degraded = bool(degraded_reasons)
    return WorkspaceOrientationResponse(
        scope=WorkspaceOrientationScope(
            vault_id=identity.vault_name,
            channel=identity.channel,
        ),
        meta=WorkspaceOrientationMeta(
            as_of=_orientation_iso(generated_at) or generated_at.isoformat(),
            trace_id=trace_id,
            freshness="partial" if degraded else "fresh",
            stale_after=_orientation_iso(stale_after) or stale_after.isoformat(),
            degraded_reasons=degraded_reasons,
        ),
        leave_point=leave_point,
        open_loops=open_loops,
        notable_changes=notable_changes,
        resurface=WorkspaceOrientationResurface(candidates=resurface_candidates),
        memory=memory,
        governance=governance,
        guards=WorkspaceOrientationGuards(
            runtime_posture="degraded" if degraded else "healthy",
            degraded=degraded,
            reasons=degraded_reasons,
            source_ref=_orientation_source_ref(
                "status",
                "api-status-derived",
                "minimal status posture",
            ),
        ),
        mutation_intents=mutation_intents,
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

    content_hash = _content_hash(body)
    selectable_options: list[PanelSelectableOption] = []
    if identity.artifact_id:
        selectable_options = extract_panel_selectable_options(
            body,
            artifact_id=identity.artifact_id,
            note_path=safe_note_path,
            content_hash=content_hash,
        )

    return WorkspaceStateResponse(
        artifact=ArtifactState(
            artifact_id=identity.artifact_id,
            artifact_kind=identity.artifact_kind,
            note_path=safe_note_path,
            title=_extract_title(body, fallback=artifact_path.stem),
            body=body,
            content_hash=content_hash,
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
        panel=_panel_state(identity.artifact_id, selectable_options=selectable_options),
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


class NoteSaveRequest(BaseModel):
    note_path: str
    new_body: str
    # Optional optimistic-concurrency token: the content_hash the editor loaded
    # with. When provided and stale, the save is refused so a concurrent change
    # is not clobbered. Omit to force-save.
    expected_content_hash: str | None = None


class NoteSaveResponse(BaseModel):
    status: str
    note_path: str
    content_hash: str


@router.post("/note/save", response_model=NoteSaveResponse)
def save_note_body(req: NoteSaveRequest) -> NoteSaveResponse:
    """Human-initiated direct edit of the active note body.

    This is a first-class human operation over the user's own vault. It is
    intentionally **not** gated by ``CANVAS_ENABLED`` or
    ``WORKSPACE_UPDATE_FLOW_ENABLED`` (those govern AI/Canvas-mediated writes,
    not the human typing in their own note) and does not route through the
    Canvas-session/active-note-body-update state machine.

    The only retained guard is the runtime-health write block — pure data-safety
    that refuses writes while the runtime is in a broken/degraded state — which
    never trips in normal operation. Frontmatter is preserved verbatim; the body
    must not carry its own frontmatter block.
    """
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.note.human_edit")
    except WritesBlockedError as exc:
        # 409: transient runtime-health state, not a permission denial.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "runtime_write_blocked",
                "message": str(exc),
                "state": exc.state,
            },
        ) from exc
    except Exception:
        # The health snapshot could not even be evaluated (e.g. a minimally
        # configured vault). The human-edit path fails open — this courtesy
        # data-safety net must never block the user from editing their own note.
        pass

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
                "message": "new_body must not contain a frontmatter block; frontmatter is preserved automatically",
            },
        )

    current = note_path.read_text(encoding="utf-8")
    if req.expected_content_hash and _content_hash(current) != req.expected_content_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "content_hash_mismatch",
                "message": "The note changed since you opened it. Reload to pick up the latest, then re-apply your edit.",
                "content_hash": _content_hash(current),
            },
        )

    frontmatter_inner, _ = _split_frontmatter(current)
    if frontmatter_inner is not None:
        new_content = f"---{frontmatter_inner}\n---\n{req.new_body}"
    else:
        new_content = req.new_body if req.new_body.endswith("\n") else req.new_body + "\n"

    write_note_from_absolute(note_path, new_content, vault_root=vault_root)

    written = note_path.read_text(encoding="utf-8")
    return NoteSaveResponse(
        status="ok",
        note_path=safe_note_path,
        content_hash=_content_hash(written),
    )


__all__ = ["router"]
