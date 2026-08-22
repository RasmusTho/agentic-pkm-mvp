"""Heimdal hard-retention ops job + deletion receipts (#3032).

Slice A12 of Epic #3019 (Heimdal v1). Ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#13 (Retention). Enacts
Charter FIXED #7 / D-RETENTION and closes the `future_runtime` half of
HEIM-7 (`heim_decay_event_triggered`,
`tests/heimdal/test_invariants_heim.py::test_heim_7_decay_event_triggered`):

    The raw layer is the one place true erasure exists, by design, and its
    execution must be a governed, auditable, receipted act.

What this module builds (build-now per §11#13):

- **A bounded hard-retention bound**, executed regardless of decay signals.
  :func:`enforce_hard_retention_bound` hard-deletes every raw record whose
  `ingested_at` is older than the configured retention window, via the ONE
  governed exception to the raw store's append-only trigger
  (`app.heimdal.raw_store.hard_delete_raw_record`, D-RETENTION).
- **A durable deletion receipt for every deletion**, in the same operation
  that performs it -- there is no "delete now, receipt later" step, exactly
  mirroring the raw-read-receipt discipline in `app.heimdal.raw_read_gate`.
  A deletion is never silent; a deletion without a receipt is a defect.
- **Markdown-first policy** (ADR-0049 §2): the retention window is read from
  `_heimdal/settings.md` (`app.heimdal.settings_notes.SETTINGS`,
  `retention_window_days`, A14 substrate) -- never a hidden store or an
  env-var-only knob. A missing/unset window is a fail-loud configuration
  error (KERNEL-03/I-S4 precedent): this module refuses to guess a default
  bound for an irreversible governed act.

What this module explicitly does NOT touch (Constraints, binding):

- The append-only observation log (`app.heimdal.observation_log`, HEIM-1)
  and its projections -- retention operates on raw evidence and receipts
  only (noncanonical, HEIM-8 unaffected). A published event's `raw_ref`
  becomes a **declared dangling reference** after its raw record is
  deleted; `app.heimdal.raw_read_gate.read_raw_record` already returns
  `RawReadRefusedError` for any `raw_ref` that does not resolve to a known
  raw record (declared-absent, never a silent None/empty return) -- no
  change to that gate was needed for this slice.

Out of scope (declared v2 contract-stub gaps per §11#13/#14, not built
here): event-triggered relevance-decay (the decay-model half of HEIM-7
stays a named future runtime, see `docs/HEIMDAL/FABLE_COMPANION.md` §8);
consent-revocation-triggered deletion runtime (§11#14); cryptographic
erasure of published event content (v2 hardening candidate).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from app.heimdal import raw_liveness, raw_store
from app.heimdal.raw_liveness import DeletionReceipt
from app.heimdal.settings_notes import (
    DEFAULT_SETTINGS_DIR,
    SETTINGS,
    apply_agent_update,
    read_settings_note,
)

# The only reason value this v1 job ever writes: the bounded window fired,
# independent of any decay signal (§11#13 "executing regardless of decay
# signals"). Event-triggered decay (HEIM-7's decay-model half) is v2 and
# would introduce additional reason values when it lands -- declared, not
# silently precluded.
REASON_HARD_RETENTION_BOUND = "hard_retention_bound"
REASON_SCREEN_FRAME_RETENTION_BUFFER = "screen_frame_retention_buffer"


class RetentionWindowMissingError(RuntimeError):
    """Raised when `_heimdal/settings.md` has no `retention_window_days` set.

    Fail-loud (KERNEL-03/I-S4 precedent, mirrors
    `raw_store.resolve_raw_store_key` / `raw_read_gate.resolve_read_allowlist`):
    an irreversible governed deletion job never guesses a default bound.
    """


DeletionReceiptSchemaMissingError = raw_liveness.RawLivenessSchemaMissingError


AppendOnlyViolationError = raw_liveness.RawLivenessUnavailableError


@dataclass(frozen=True)
class RetentionEnforcementReceipt:
    """The result of one `enforce_hard_retention_bound` run.

    ``receipted`` is ``True`` whenever the run completed and every deletion
    it performed (if any) has a persisted :class:`DeletionReceipt` --
    including the zero-deletions case, since "nothing was past the bound"
    is itself a receipted, honest outcome, never a silent no-op.
    """

    deleted_count: int
    retention_window_days: int
    deletions: tuple[DeletionReceipt, ...]
    receipted: bool = True


def _reconcile_pending_cold_cleanup() -> None:
    """Retry durable post-commit cold cleanup after scanning active records.

    A completed DB erasure is no longer present in ``all_raw_records``. The
    receipt log is therefore the scheduled retry index; the governed delete
    path re-acquires the same fence and reconciles only its durable queue.
    Failed external cleanup remains queued for the next run.
    """
    for receipt in raw_liveness.all_deletion_receipts():
        if not receipt.payload.get("cold_cleanup_location_refs"):
            continue
        try:
            raw_liveness.governed_delete_raw_record(
                record_id=receipt.record_id,
                reason=receipt.reason,
                retention_window_days=receipt.retention_window_days,
                deleted_at=receipt.deleted_at,
                payload=receipt.payload,
            )
        except raw_store.RawRepresentationDeletionError:
            continue


def _resolve_retention_window_days(vault_root: Path, *, settings_dir: str = DEFAULT_SETTINGS_DIR) -> int:
    """Read the hard-retention bound from `_heimdal/settings.md` (A14, markdown-first).

    Fail-loud: no note, or a note without `retention_window_days` set, or a
    non-positive value, all raise :class:`RetentionWindowMissingError` --
    this job never assumes a default bound for an irreversible act.
    """
    note = read_settings_note(vault_root, SETTINGS, settings_dir=settings_dir)
    raw_value = note.values.get("retention_window_days") if note is not None else None
    if raw_value is None or raw_value == "":
        raise RetentionWindowMissingError(
            f"_heimdal/settings.md has no retention_window_days set (D-RETENTION, Charter "
            "FIXED #7): the hard-retention ops job refuses to assume a default bound for "
            "an irreversible governed deletion. Set retention_window_days in "
            f"{settings_dir}/settings.md."
        )
    try:
        window_days = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise RetentionWindowMissingError(
            f"_heimdal/settings.md retention_window_days must be a positive integer, got "
            f"{raw_value!r}"
        ) from exc
    if window_days <= 0:
        raise RetentionWindowMissingError(
            f"_heimdal/settings.md retention_window_days must be a positive integer, got "
            f"{window_days!r}"
        )
    return window_days


def resolve_retention_window_days(
    vault_root: Optional[Path] = None, *, settings_dir: str = DEFAULT_SETTINGS_DIR
) -> int:
    """Public wrapper over :func:`_resolve_retention_window_days` for callers/tests
    that want to resolve the configured window without running the job."""
    from app.config.paths import resolve_optional_vault_root

    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise RetentionWindowMissingError(
            "No vault root configured: the hard-retention ops job reads its policy from "
            "_heimdal/settings.md and cannot resolve a retention window without a bound vault."
        )
    return _resolve_retention_window_days(root, settings_dir=settings_dir)


def resolve_screen_frame_retention_minutes(
    vault_root: Optional[Path] = None, *, settings_dir: str = DEFAULT_SETTINGS_DIR
) -> int:
    """Resolve SCREEN-01's short raw-frame buffer without inventing a default."""
    from app.config.paths import resolve_optional_vault_root

    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise RetentionWindowMissingError("No vault root configured for screen_frame_retention_minutes")
    note = read_settings_note(root, SETTINGS, settings_dir=settings_dir)
    raw_value = note.values.get("screen_frame_retention_minutes") if note is not None else None
    try:
        minutes = int(str(raw_value))
    except (TypeError, ValueError) as exc:
        raise RetentionWindowMissingError(
            "_heimdal/settings.md must set a positive screen_frame_retention_minutes; no default is safe"
        ) from exc
    if minutes <= 0:
        raise RetentionWindowMissingError("screen_frame_retention_minutes must be a positive integer")
    return minutes


def reset_memory_deletion_receipts() -> None:
    """Test-only reset hook for the unified liveness authority."""

    raw_liveness.reset_memory_deletion_receipts()


def all_deletion_receipts() -> List[DeletionReceipt]:
    """Return every deletion receipt in insertion order (diagnostic/test/audit helper)."""
    return raw_liveness.all_deletion_receipts()


# ---------------------------------------------------------------------------
# The real production job entry point
# ---------------------------------------------------------------------------


def enforce_hard_retention_bound(
    *,
    vault_root: Optional[Path] = None,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    now: Optional[datetime] = None,
    record_last_enforced: bool = True,
) -> RetentionEnforcementReceipt:
    """The one sanctioned hard-retention job entry point (D-RETENTION, HEIM-7).

    Resolves the retention window from `_heimdal/settings.md`
    (`retention_window_days`, fail-loud if unset -- see
    :func:`_resolve_retention_window_days`), then hard-deletes every raw
    record in `app.heimdal.raw_store` whose `ingested_at` is strictly older
    than ``now - retention_window_days`` -- **regardless of decay signals**
    (§11#13: event-triggered decay is a declared v2 stub, this bound
    executes unconditionally on age alone). Each deletion is paired with
    exactly one durable :class:`DeletionReceipt` in the same call -- there
    is no code path that removes a raw record without also persisting its
    receipt (Constraints: "no silent hard delete").

    Records within the window are left untouched (negative case). The
    published observation log (HEIM-1) is never read or written by this
    function -- retention operates on raw evidence and receipts only. Media
    admission history is append-only too: after the governed raw deletion,
    `media_ingress.receipt_answer` derives the receipt's client-visible
    ``erased`` outcome instead of leaving it falsely admitted.

    Returns a :class:`RetentionEnforcementReceipt` naming how many records
    were deleted (``deleted_count`` -- ``0`` is a valid, honestly-receipted
    outcome) and the individual :class:`DeletionReceipt` rows produced.
    """
    from app.config.paths import resolve_optional_vault_root

    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise RetentionWindowMissingError(
            "No vault root configured: the hard-retention ops job reads its policy from "
            "_heimdal/settings.md and cannot resolve a retention window without a bound vault."
        )

    window_days = _resolve_retention_window_days(root, settings_dir=settings_dir)
    reference_time = now if now is not None else datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(days=window_days)

    deletions: List[DeletionReceipt] = []
    for record in raw_store.all_raw_records():
        ingested_at = record.ingested_at
        if ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=timezone.utc)
        if ingested_at >= cutoff:
            continue  # within the bound: not deleted (negative AC)

        result = raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=REASON_HARD_RETENTION_BOUND,
            retention_window_days=window_days,
            deleted_at=reference_time,
        )
        if result.outcome != "deleted":
            # A concurrent run may already have erased this generation, while
            # a valid response lease makes this bounded run skip and retry on
            # its next schedule. Neither case fabricates another receipt.
            continue
        assert result.receipt is not None
        deletions.append(result.receipt)

    # Read the durable retry queue only after active generations have entered
    # the governed delete path.  The memory receipt snapshot takes the same
    # liveness fence as response-lease issuance; consuming it first would wait
    # behind an in-flight response before the retention writer could announce
    # its own fence entry, inverting the producer/retention handshake.
    _reconcile_pending_cold_cleanup()

    if record_last_enforced:
        apply_agent_update(
            root,
            SETTINGS,
            {"last_enforced_at": reference_time.isoformat().replace("+00:00", "Z")},
            settings_dir=settings_dir,
        )

    return RetentionEnforcementReceipt(
        deleted_count=len(deletions),
        retention_window_days=window_days,
        deletions=tuple(deletions),
    )


def enforce_screen_frame_retention(
    *, vault_root: Optional[Path] = None, settings_dir: str = DEFAULT_SETTINGS_DIR,
    now: Optional[datetime] = None,
) -> RetentionEnforcementReceipt:
    """Hard-delete only aged screen-frame records through the shared raw store.

    The existing receipt table's historical `retention_window_days` column is
    retained for compatibility; the exact minute bound is recorded in the
    receipt payload for this SCREEN-01-specific reason.
    """
    minutes = resolve_screen_frame_retention_minutes(vault_root, settings_dir=settings_dir)
    reference_time = now if now is not None else datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(minutes=minutes)
    deletions: List[DeletionReceipt] = []
    for record in raw_store.all_raw_records():
        if record.payload.get("modality") != "screen":
            continue
        ingested_at = record.ingested_at if record.ingested_at.tzinfo else record.ingested_at.replace(tzinfo=timezone.utc)
        if ingested_at >= cutoff:
            continue
        result = raw_liveness.governed_delete_raw_record(
            record_id=record.id,
            reason=REASON_SCREEN_FRAME_RETENTION_BUFFER,
            retention_window_days=0,
            deleted_at=reference_time,
            payload={"screen_frame_retention_minutes": minutes},
        )
        if result.outcome == "deleted":
            assert result.receipt is not None
            deletions.append(result.receipt)
    return RetentionEnforcementReceipt(deleted_count=len(deletions), retention_window_days=0, deletions=tuple(deletions))


__all__ = [
    "AppendOnlyViolationError",
    "DeletionReceipt",
    "DeletionReceiptSchemaMissingError",
    "REASON_HARD_RETENTION_BOUND",
    "REASON_SCREEN_FRAME_RETENTION_BUFFER",
    "RetentionEnforcementReceipt",
    "RetentionWindowMissingError",
    "all_deletion_receipts",
    "enforce_hard_retention_bound",
    "reset_memory_deletion_receipts",
    "resolve_retention_window_days",
    "resolve_screen_frame_retention_minutes",
    "enforce_screen_frame_retention",
]
