"""Server-side entry-state resolution for the Companion UI shell (#1783, SEP-01).

Implements the entry-point state model from
``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Entry-point state model
(NORMATIVE)`` as a pure function wrapping — not replacing — the existing
orientation/workspace renderer branch in ``serve_dev_page.py``.

State enum (exactly five; adding or removing one is a spec change):

- ``boot``         runtime handshake in progress (orientation fetch unresolved;
                   the state any client-side ``entry.retry`` returns to).
                   Server-rendered pages resolve the fetch before emitting
                   HTML, so handler output always declares a post-boot state.
- ``no_vault``     runtime aggregate unreachable (HTTP 503
                   ``runtime_unavailable`` per
                   ``WORKSPACE_ORIENTATION_CONTRACT.md §Runtime Unavailable``).
- ``cold_start``   first contact or cold trajectory (> 14 days): no admissible
                   leave point. Renders no re-entry overlay of any kind.
- ``orienting``    returning with a recoverable trajectory; carries a re-entry
                   shape derived from the gap per the latency ladder in
                   ``CONTINUITY_AND_DECAY.md``.
- ``shell_active`` document anchor open.

``degraded`` and ``stale`` are cross-flags that may decorate ``orienting`` and
``shell_active`` only — never separate states. Input combinations outside the
enumerated transitions resolve to the nearest declared state and are surfaced
as degraded reasons (``entry_state_*`` codes), never as a new implicit state.

The server declares; the UI renders. Nothing in this module is derived
client-side.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from datetime import datetime, timezone

ENTRY_STATES: tuple[str, ...] = (
    "boot",
    "no_vault",
    "cold_start",
    "orienting",
    "shell_active",
)

REENTRY_SHAPES: tuple[str, ...] = (
    "no_mist",
    "thread_fade",
    "soft_mist",
    "full_mist",
    "long_mist",
)

# States the degraded/stale cross-flags may decorate (spec: "Two cross-flags
# may decorate `orienting` and `shell_active` without being separate states").
_CROSS_FLAG_STATES: frozenset[str] = frozenset({"orienting", "shell_active"})

# leave_point.status values declared by WORKSPACE_ORIENTATION_CONTRACT.md.
_LEAVE_STATUS_ABSENT = "absent"
_LEAVE_STATUS_PRESENT = "present"
_LEAVE_STATUS_STALE: frozenset[str] = frozenset({"stale", "artifact_missing", "degraded"})

# Resolver-surfaced degraded reason codes for out-of-contract inputs.
REASON_NOTE_LOAD_FAILED = "entry_state_note_load_failed"
REASON_UNRESOLVED_RUNTIME_ERROR = "entry_state_unresolved_runtime_error"
REASON_LEAVE_POINT_STATUS_UNDECLARED = "entry_state_leave_point_status_undeclared"
REASON_REENTRY_GAP_UNKNOWN = "entry_state_reentry_gap_unknown"

# Latency-ladder gap boundaries in seconds (CONTINUITY_AND_DECAY.md).
_GAP_NO_MIST_MAX = 90  # < 90s
_GAP_THREAD_FADE_MAX = 15 * 60  # 90s – 15m
_GAP_SOFT_MIST_MAX = 2 * 60 * 60  # 15m – 2h
_GAP_FULL_MIST_MAX = 3 * 24 * 60 * 60  # 2h – 3d
_GAP_COLD_THRESHOLD = 14 * 24 * 60 * 60  # > 14d → cold_start, not a shape


@dataclass(frozen=True)
class EntryStateResolution:
    """The server-resolved entry state for one page render.

    Constructing a resolution outside the declared contract raises
    ``ValueError`` — undeclared states, undeclared shapes, shapes on
    non-orienting states, and cross-flags on states they may not decorate
    are all rejected at the type level.
    """

    state: str
    reentry_shape: str | None = None
    degraded: bool = False
    stale: bool = False
    degraded_reasons: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.state not in ENTRY_STATES:
            raise ValueError(
                f"undeclared entry state {self.state!r}; allowed: {ENTRY_STATES}"
            )
        if self.reentry_shape is not None:
            if self.reentry_shape not in REENTRY_SHAPES:
                raise ValueError(
                    f"undeclared re-entry shape {self.reentry_shape!r}; "
                    f"allowed: {REENTRY_SHAPES}"
                )
            if self.state != "orienting":
                raise ValueError(
                    "a re-entry shape may only decorate the 'orienting' state, "
                    f"not {self.state!r}"
                )
        if (self.degraded or self.stale) and self.state not in _CROSS_FLAG_STATES:
            raise ValueError(
                "degraded/stale cross-flags may only decorate "
                f"{sorted(_CROSS_FLAG_STATES)}, not {self.state!r}"
            )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _shape_for_gap(gap_seconds: float) -> str | None:
    """Latency-ladder shape for a gap; ``None`` means cold (> 14 days)."""
    if gap_seconds < _GAP_NO_MIST_MAX:
        return "no_mist"
    if gap_seconds < _GAP_THREAD_FADE_MAX:
        return "thread_fade"
    if gap_seconds < _GAP_SOFT_MIST_MAX:
        return "soft_mist"
    if gap_seconds < _GAP_FULL_MIST_MAX:
        return "full_mist"
    if gap_seconds <= _GAP_COLD_THRESHOLD:
        return "long_mist"
    return None


def _is_runtime_unavailable_error(error: str) -> bool:
    """True when an error string signals the runtime aggregate is unreachable.

    Covers the contract's HTTP 503 ``runtime_unavailable`` payload and
    request-level network failures (connection refused, timeout, DNS).
    """
    lowered = error.lower()
    if "runtime_unavailable" in lowered:
        return True
    if lowered.startswith("http 503"):
        return True
    return any(
        marker in lowered
        for marker in ("connection refused", "timed out", "timeout", "network")
    )


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _payload_degraded_reasons(orientation: dict) -> list[str]:
    """Collect declared degraded reasons from meta and guards, deduplicated."""
    meta = _as_dict(orientation.get("meta"))
    guards = _as_dict(orientation.get("guards"))
    collected: list[str] = []
    for source in (meta.get("degraded_reasons"), guards.get("reasons")):
        if not isinstance(source, list):
            continue
        for reason in source:
            text = str(reason) if reason is not None else ""
            if text and text not in collected:
                collected.append(text)
    return collected


def _gap_seconds(orientation: dict, leave_point: dict) -> float | None:
    """Gap between the server-declared snapshot time and the leave point.

    Derived purely from server-declared payload fields (``meta.as_of`` and
    ``leave_point.captured_at``, with the legacy ``last_interaction_at`` as
    fallback) — the UI never derives the gap from a local clock.
    """
    as_of = _parse_timestamp(_as_dict(orientation.get("meta")).get("as_of"))
    captured = _parse_timestamp(leave_point.get("captured_at")) or _parse_timestamp(
        leave_point.get("last_interaction_at")
    )
    if as_of is None or captured is None:
        return None
    return max(0.0, (as_of - captured).total_seconds())


def _resolve_from_orientation(orientation: dict) -> EntryStateResolution:
    reasons = _payload_degraded_reasons(orientation)
    leave_point = _as_dict(orientation.get("leave_point"))
    status = leave_point.get("status")
    status_text = status if isinstance(status, str) else ""

    if not leave_point or status_text == _LEAVE_STATUS_ABSENT:
        # First contact: no admissible leave point → cold_start, no overlay.
        return EntryStateResolution(state="cold_start", degraded_reasons=tuple(reasons))

    stale = status_text in _LEAVE_STATUS_STALE
    if status_text != _LEAVE_STATUS_PRESENT and not stale:
        # A leave point exists but its status is outside the declared
        # contract: resolve to the nearest declared state (orienting) and
        # surface the divergence as a degraded reason.
        reasons.append(REASON_LEAVE_POINT_STATUS_UNDECLARED)

    gap = _gap_seconds(orientation, leave_point)
    if gap is None:
        # Gap underivable from server-declared fields: keep the canonical
        # re-entry shape and surface the divergence.
        shape: str | None = "full_mist"
        reasons.append(REASON_REENTRY_GAP_UNKNOWN)
    else:
        shape = _shape_for_gap(gap)
        if shape is None:
            # Cold trajectory (> 14 days) is not an orienting shape — it
            # resolves to cold_start and renders no re-entry overlay.
            return EntryStateResolution(state="cold_start", degraded_reasons=tuple(reasons))

    return EntryStateResolution(
        state="orienting",
        reentry_shape=shape,
        degraded=bool(reasons),
        stale=stale,
        degraded_reasons=tuple(reasons),
    )


def resolve_entry_state(
    *,
    note_path: str = "",
    note_loaded: bool = False,
    error: str = "",
    orientation: dict | None = None,
    orientation_error: str = "",
) -> EntryStateResolution:
    """Resolve the entry-point state for one server render — pure function.

    Inputs mirror the existing ``render_index_html`` branch exactly, in the
    same precedence order, so the declared state always matches the page the
    renderer actually emits:

    - orientation page (orientation present, no fields, no error):
      ``no_vault`` when the orientation fetch failed (``orientation_error``),
      otherwise ``cold_start`` / ``orienting`` from ``leave_point.status``;
    - error page: ``no_vault`` when the runtime is unreachable, otherwise the
      nearest declared state with the failure surfaced as a degraded reason;
    - workspace page (note anchor loaded): ``shell_active``;
    - no resolved orientation outcome at all: ``boot`` (handshake in
      progress — the pre-resolution state).
    """
    if orientation is not None and not note_loaded and not error:
        if orientation_error:
            # The orientation fetch failed; the page renders the
            # orientation-unavailable frame. Runtime aggregate unreachable.
            reasons = _payload_degraded_reasons(orientation)
            if not _is_runtime_unavailable_error(orientation_error):
                reasons.append(REASON_UNRESOLVED_RUNTIME_ERROR)
            return EntryStateResolution(state="no_vault", degraded_reasons=tuple(reasons))
        return _resolve_from_orientation(orientation)

    if error:
        if _is_runtime_unavailable_error(error):
            return EntryStateResolution(state="no_vault")
        if note_path:
            # A note anchor was requested and the shell rendered, but the
            # anchor failed to load: nearest declared state is shell_active,
            # with the failure surfaced as a degraded reason.
            return EntryStateResolution(
                state="shell_active",
                degraded=True,
                degraded_reasons=(REASON_NOTE_LOAD_FAILED,),
            )
        return EntryStateResolution(
            state="no_vault",
            degraded_reasons=(REASON_UNRESOLVED_RUNTIME_ERROR,),
        )

    if note_loaded:
        return EntryStateResolution(state="shell_active")

    # No orientation outcome, no error, no note: the handshake is unresolved.
    return EntryStateResolution(state="boot")


def entry_state_attributes(resolution: EntryStateResolution) -> str:
    """Render the resolution as shell-root (``<body>``) data attributes.

    Emits ``data-entry-state`` always, ``data-reentry-shape`` only when
    orienting, the ``data-degraded`` / ``data-stale`` cross-flags only when
    set, and ``data-entry-degraded-reasons`` as the surfacing channel for
    out-of-contract inputs (SYSTEM_ENTRY_POINT_SPEC.md §Data-attribute
    vocabulary; adding attributes is permitted).
    """
    parts = [f'data-entry-state="{resolution.state}"']
    if resolution.reentry_shape is not None:
        parts.append(f'data-reentry-shape="{resolution.reentry_shape}"')
    if resolution.degraded:
        parts.append('data-degraded="true"')
    if resolution.stale:
        parts.append('data-stale="true"')
    if resolution.degraded_reasons:
        joined = _html.escape(" ".join(resolution.degraded_reasons))
        parts.append(f'data-entry-degraded-reasons="{joined}"')
    return " ".join(parts)
