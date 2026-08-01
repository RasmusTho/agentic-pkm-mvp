"""Heimdal `consent.md` readout -- Epic #3019 slice A19 (#3044).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
§2 (markdown-first, UI is a lens) and §3 (Posture A / discrete capture v1,
the consent note already writes the B-shaped mechanism, dormant), and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §9-k / §6.1-§6.4.

Contract (binding for this slice):

- **`consent.md` is a human-readable READOUT that mirrors the append-only
  consent LEDGER (A5, `app.heimdal.consent_ledger`).** The ledger is the
  mechanism and the sole source of record; this note is the legible lens
  over it. Rendering ``consent.md`` is a pure function of ledger state --
  :func:`render_consent_readout` reads active grants via
  :func:`app.heimdal.consent_ledger.list_active_grants` and builds the note
  from what it finds. There is no code path in this module that starts from
  a note edit and produces a ledger mutation; the module exposes exactly one
  write function (:func:`write_consent_readout`) and it always derives its
  content from the ledger, never from caller-supplied grant data.
- **Read-mostly, not read-only.** The note is a governed vault write (same
  seam every other Heimdal control note uses,
  `app.heimdal.settings_notes.write_settings_note` ->
  `app.knowledge.write_ops.write_note_relative` + `WriteGuard`) -- but the
  write is always a *rebuild from the ledger*, never an independent mutation
  of consent state. This keeps the readout "derived, rebuildable" (governing
  Issue's SBS Impact) rather than a second consent mechanism that could drift
  from, or worse override, the ledger (the named boundary risk: "the readout
  must not become a control that mutates consent independently of the
  ledger").
- **v1 exercises only the `self_record` basis.** The readout renders whatever
  grants are active; v1's only populated basis is `self_record`. Since #4492
  that basis has **two** standing grants -- the voice-memo grant
  (`SELF_RECORD_SCOPE`) and the media-capture grant (`MEDIA_CAPTURE_SCOPE`) --
  so v1's `consent.md` reflects both, distinguished by `scope` and
  `grant_ref`, not by `basis`. A consumer that needs one specific lane's grant
  must key on `scope`; a "the one self_record grant" read is wrong.
- **B-shaped fields present-but-dormant (ADR-0049 §3).** The rendered readout
  always includes a `withhold_span_review` block and a `retention_erasure`
  block, both structurally present but inert in v1 (`enabled: False` /
  `supported: False`, no queued items, no executed erasures) -- present so
  Posture B inherits a working surface without a schema change, per the same
  discipline `consent_ledger.py`'s B-shaped grant fields already follow.

This module reuses the A14 `_heimdal/**` settings-note substrate's `CONSENT`
`SettingsNoteSpec` (`app.heimdal.settings_notes.CONSENT`) for path resolution
and the governed write seam, but the note's *content* here is always the
ledger mirror this module builds -- not a caller-authored "declared grants"
payload. `settings_notes.py`'s generic `grants` field (human-editable in the
A14 schema) is populated here with the ledger's own resolved state, not with
free-form human input; this slice does not add a code path for a human to
hand-edit the mirrored fields back into the ledger (that would be the UI-only
capability `break` ADR-0049 forbids). A future write-intent path (human edits
`consent.md` to *propose* a grant/revoke, an agent reconciles it into the
ledger) is out of scope here, per the governing Issue.

Out of scope for this slice (per governing Issue #3044): withhold-span
review execution, retention/erasure execution, place/session consent grant
UI, any runtime that lets a `consent.md` edit mutate the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.heimdal.consent_ledger import ConsentGrant, list_active_grants
from app.heimdal.settings_notes import (
    CONSENT,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSENT_READOUT_WRITE_ACTION = "heimdal.consent_surface.write"

# B-shaped-but-dormant field defaults (ADR-0049 §3): present, structurally
# real, and inert in v1. `enabled`/`supported` gate whether any runtime ever
# reads these; v1 code never sets them True.
_WITHHOLD_SPAN_REVIEW_DORMANT: Dict[str, Any] = {
    "enabled": False,
    "pending_review_count": 0,
    "queue": [],
}
_RETENTION_ERASURE_DORMANT: Dict[str, Any] = {
    "supported": False,
    "hard_retention_days": None,
    "erasure_requests": [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Grant readout shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantReadout:
    """One active grant, projected into the human-readable readout shape.

    A faithful field-for-field mirror of :class:`ConsentGrant` -- no field is
    summarized away or renamed into something the ledger does not carry.
    """

    grant_ref: str
    basis: str
    scope: str
    granted_by: str
    granted_at: str
    expiry: Optional[str]
    capture_profile: Dict[str, Any]
    third_party_policy: str
    vad_gate: Dict[str, Any]
    third_party: Dict[str, Any]
    retention: Dict[str, Any]
    erasure: Dict[str, Any]

    @classmethod
    def from_grant(cls, grant: ConsentGrant) -> "GrantReadout":
        return cls(
            grant_ref=grant.grant_ref,
            basis=grant.basis,
            scope=grant.scope,
            granted_by=grant.granted_by,
            granted_at=grant.granted_at.isoformat(),
            expiry=grant.expiry.isoformat() if grant.expiry is not None else None,
            capture_profile=dict(grant.capture_profile),
            third_party_policy=grant.third_party_policy,
            vad_gate=dict(grant.vad_gate),
            third_party=dict(grant.third_party),
            retention=dict(grant.retention),
            erasure=dict(grant.erasure),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "grant_ref": self.grant_ref,
            "basis": self.basis,
            "scope": self.scope,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "expiry": self.expiry,
            "capture_profile": self.capture_profile,
            "third_party_policy": self.third_party_policy,
            "vad_gate": self.vad_gate,
            "third_party": self.third_party,
            "retention": self.retention,
            "erasure": self.erasure,
        }


def _active_grant_readouts(*, at: Optional[datetime] = None) -> List[GrantReadout]:
    """Every currently-active ledger grant, projected to the readout shape.

    Pure query: reads the ledger via :func:`list_active_grants` (no scope
    filter -- the readout mirrors the whole ledger, not one adapter's
    scope), never mutates it. Ordered by ledger sequence so the readout's
    grant list matches append order (oldest standing grant first).
    """
    grants = list_active_grants(at=at)
    ordered = sorted(grants, key=lambda g: g.sequence)
    return [GrantReadout.from_grant(g) for g in ordered]


# ---------------------------------------------------------------------------
# Readout construction -- a pure function of ledger state
# ---------------------------------------------------------------------------


def build_consent_readout_values(*, at: Optional[datetime] = None) -> Dict[str, Any]:
    """Build the `consent.md` frontmatter `values` dict from ledger state.

    Pure function: given the ledger's current active grants, returns exactly
    the values `consent.md` should carry. No caller-supplied grant data is
    accepted here -- the only input is what the ledger itself reports, which
    is what makes this a mirror rather than an independent grant-authoring
    surface.
    """
    active = _active_grant_readouts(at=at)
    return {
        "grants": [g.as_dict() for g in active],
        "last_ledger_sync": _now_iso(),
        "withhold_span_review": dict(_WITHHOLD_SPAN_REVIEW_DORMANT),
        "retention_erasure": dict(_RETENTION_ERASURE_DORMANT),
    }


def render_consent_readout(*, at: Optional[datetime] = None) -> SettingsNote:
    """Build the in-memory `SettingsNote` for `consent.md`, mirroring the ledger.

    Uses the A14 `CONSENT` `SettingsNoteSpec` (`app.heimdal.settings_notes`)
    for schema/authority; the note's field values are always freshly derived
    from :func:`build_consent_readout_values`, never carried over from a
    prior on-disk read -- there is nothing for a human edit to preserve
    across a rebuild because the note owns no independent state (contrast
    with `apply_agent_update`'s human/agent field-preservation cycle, which
    is for genuinely mixed-authority notes; this note is entirely mirror).
    """
    values = build_consent_readout_values(at=at)
    return SettingsNote(spec=CONSENT, values=values)


# ---------------------------------------------------------------------------
# Write -- the real production entry point
# ---------------------------------------------------------------------------


def write_consent_readout(
    vault_root: Path,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    action: str = CONSENT_READOUT_WRITE_ACTION,
    at: Optional[datetime] = None,
) -> SettingsNote:
    """Rebuild and write `_heimdal/consent.md` from the current ledger state.

    The one production call site that materializes the consent readout onto
    disk. Always rebuilds the note's full content from
    :func:`render_consent_readout` (i.e. from the ledger) and writes it
    through the governed `_heimdal/**` seam
    (`app.heimdal.settings_notes.write_settings_note` ->
    `app.knowledge.write_ops.write_note_relative` + `WriteGuard`) -- so a
    health-blocked runtime cannot silently corrupt the readout either, and a
    write here can never diverge from the ledger it just read.
    """
    note = render_consent_readout(at=at)
    write_settings_note(vault_root, note, write_guard=write_guard, action=action)
    return note


def read_consent_readout(vault_root: Path) -> Optional[SettingsNote]:
    """Read the on-disk `consent.md`, if it has been written yet.

    Thin, read-only convenience wrapper over
    `app.heimdal.settings_notes.read_settings_note` scoped to the `CONSENT`
    spec -- provided so callers do not need to import the generic settings-
    notes API just to check the readout's current on-disk shape.
    """
    return read_settings_note(vault_root, CONSENT)


__all__ = [
    "CONSENT_READOUT_WRITE_ACTION",
    "GrantReadout",
    "build_consent_readout_values",
    "read_consent_readout",
    "render_consent_readout",
    "write_consent_readout",
]
