"""Propose-track materialization for curation findings (G2-2).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §1, §2, §6
(slice G2-2). This module is the "Panel suggested-checkbox materialization"
path the issue calls for: it turns :class:`app.curation.findings.CurationFinding`
records into unchecked ``AI-åtgärder`` checkboxes via the *existing* PanelAgent
write-back surface (PA2-SUGGESTED-CHECKBOXES / Option B,
``docs/PANEL_AGENT.md:126,132``) -- it does not invent a new note surface.

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.curation.lint``'s posture):

- **Propose-only by construction.** :func:`write_curation_proposals` only
  ever inserts unchecked (``- [ ]``) checkbox lines. There is no code path in
  this module that checks a box or edits note body content outside the
  governed checkbox block. Materialization never executes in the same pass
  (PA2-SUGGESTED-CHECKBOXES invariant): the box is inert until a human later
  checks it through the ordinary Panel confirm flow.
- **``AUTOFIX_APPLY`` gate.** :func:`autofix_apply_enabled` reads the flag;
  absent/false means every finding -- including mechanical-allowlist classes
  -- materializes as propose (spec §6 G2-2: "AUTOFIX apply path built but
  hard-disabled"). This module never contains a body-edit ``act``-tier
  writer: that writer is explicitly out of scope for G2-2 (deferred to the
  not-yet-filed G2-3, gated on ADR-0048 ratification) -- see parent #2980
  ("Track P... is a parallel program deferred to a later breakdown... only
  the deferred, not-filed auto-fix flip (P9) is" gated on ADR-0048).
- **WriteGuard-gated, named action.** :data:`CURATION_PROPOSE_WRITE_ACTION`
  (``curation.propose_write``) is asserted before any file I/O, matching the
  dotted ``<module>.<verb>`` convention used elsewhere
  (``curation.lint_report.write``, ``panel.writeback``).
- **Idempotent per (note, finding_id).** Reuses
  ``app.agents.panel_agent.runtime._write_proposals_to_panel``'s own
  idempotency keys (``stable_action_id`` of the label, and the raw label
  text) unchanged -- the label embeds the finding's short id so a rerun over
  an unchanged vault produces zero new lines and zero new receipts.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.agents.panel_agent.runtime import _write_proposals_to_panel
from app.curation.findings import CurationFinding
from app.events.panel import NoteRef, PanelActionLoggedEvent, PanelEventSource
from app.services.outbox import append_jsonl_outbox_event
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Named WriteGuard action for the propose-track write seam (auditable, not a
# silent absence of a guard) -- dotted <module>.<verb> convention, mirroring
# ``curation.lint_report.write`` (app.curation.lint) and ``panel.writeback``
# (app.agents.panel_agent.runtime).
CURATION_PROPOSE_WRITE_ACTION = "curation.propose_write"

# Absent/false ⇒ every finding materializes as propose regardless of class or
# transform outcome (spec §6 G2-2, ADR-0048 enactment sequence step 3). This
# slice never reads this flag to unlock a body-edit writer -- only
# ``write_curation_proposals`` consults it, and only to decide whether to
# *skip* materializing mechanical-allowlist findings that a future,
# not-yet-built ``act``-tier writer (G2-3) would otherwise have applied
# directly. Until G2-3 ships, this module has no branch that does anything
# other than propose.
AUTOFIX_APPLY_ENV = "AUTOFIX_APPLY"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def autofix_apply_enabled() -> bool:
    """Read the ``AUTOFIX_APPLY`` gate. Absent/false is the ratified default."""
    return (os.getenv(AUTOFIX_APPLY_ENV, "") or "").strip().lower() in _TRUE_VALUES


def _proposal_label(finding: CurationFinding) -> str:
    """Render one finding as a self-contained, human-readable checkbox label.

    The short finding id is embedded so the label is unique per finding
    content (mirrors the report note's ``finding_id[:12]`` convention in
    ``app.curation.lint.render_lint_report``) without requiring the reader to
    cross-reference a separate report note to know what a checkbox refers to.
    """
    short_id = finding.finding_id[:12]
    return (
        f"[curation:{finding.finding_class.value}] {finding.proposed} "
        f"(finding {short_id})"
    )


def _note_path_from_finding(finding: CurationFinding, vault_root: Path) -> Path | None:
    """Resolve a vault-relative note path for *finding*.

    ``CurationFinding.note_uuid`` is either a real frontmatter uuid or the
    ``path:<rel>`` fallback identity ``app.curation.lint._note_identity``
    uses for uuid-less notes -- this module accepts either shape rather than
    require a uuid (uuid is advisory lineage metadata, never a processing
    gate, per ``docs/FRONTMATTER.md``). Findings carrying a real uuid also
    always carry the note's relative path in ``evidence[0]`` (every lint
    check populates evidence with ``note.rel_path``); this function falls
    back to that rather than requiring a separate uuid->path index.
    """
    vault_root = Path(vault_root).expanduser().resolve()
    if finding.note_uuid.startswith("path:"):
        candidate = vault_root / finding.note_uuid[len("path:") :]
        return candidate if candidate.exists() else None
    if finding.evidence:
        candidate = vault_root / finding.evidence[0]
        if candidate.exists():
            return candidate
    return None


def write_curation_proposals(
    findings: list[CurationFinding],
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path,
) -> list[CurationFinding]:
    """Materialize *findings* as unchecked propose-track panel checkboxes.

    Groups findings by resolved note file, inserts one checkbox line per
    finding via the existing PanelAgent write-back
    (``_write_proposals_to_panel``), and emits one ``panel.action.logged``
    receipt per newly-written proposal. WriteGuard is asserted once, before
    any file is touched, matching the guard-at-seam posture used by
    ``app.curation.lint.write_lint_report`` and
    ``app.agents.panel_agent.runtime.execute_panel_intent``.

    Returns the subset of *findings* that were skipped because their note
    file could not be resolved (empty list means every finding resolved).
    While ``AUTOFIX_APPLY`` is unset (the ratified-default state), every
    finding is materialized here regardless of ``finding.track`` -- the
    class->track wall (``app.curation.findings.track_for_class``) decides
    what an eventual ``act`` tier would apply directly; it never decides
    whether this propose-track writer runs. This function contains no
    ``act``-tier body-edit branch: G2-3 (out of scope here) is the only
    slice that would ever add one.
    """
    write_guard.assert_writes_allowed(CURATION_PROPOSE_WRITE_ACTION)

    vault_root = Path(vault_root).expanduser().resolve()
    unresolved: list[CurationFinding] = []

    by_note: dict[Path, list[CurationFinding]] = {}
    for finding in findings:
        note_path = _note_path_from_finding(finding, vault_root)
        if note_path is None:
            unresolved.append(finding)
            continue
        by_note.setdefault(note_path, []).append(finding)

    for note_path, note_findings in by_note.items():
        _materialize_for_note(note_path, note_findings, outbox_path=outbox_path)

    return unresolved


def _materialize_for_note(
    note_path: Path,
    findings: list[CurationFinding],
    *,
    outbox_path: Path,
) -> None:
    try:
        original_text = note_path.read_text(encoding="utf-8")
    except OSError:
        return

    proposed_labels = [(finding.finding_id, _proposal_label(finding)) for finding in findings]
    updated_text = _write_proposals_to_panel(original_text, proposed_labels)

    if updated_text == original_text:
        # Every proposal already present (idempotent rerun) -- no write, no
        # receipt. Matches the "re-running... is a no-op" contract (spec §2).
        return

    note_path.write_text(updated_text, encoding="utf-8")

    # One panel.action.logged receipt per *newly inserted* finding. Detect
    # "newly inserted" the same way `_write_proposals_to_panel` itself dedupes
    # (label text presence), so a partially-already-proposed batch only
    # receipts the genuinely new subset.
    for finding in findings:
        label = _proposal_label(finding)
        if label not in original_text:
            _emit_proposal_receipt(finding, note_path=note_path, outbox_path=outbox_path)


def _emit_proposal_receipt(
    finding: CurationFinding,
    *,
    note_path: Path,
    outbox_path: Path,
) -> None:
    event = PanelActionLoggedEvent(
        source=PanelEventSource(component="curation.proposal_writer", trigger="curation_pass"),
        payload={
            "note": NoteRef(uuid=finding.note_uuid, path=str(note_path)).model_dump(mode="json"),
            "finding_id": finding.finding_id,
            "finding_class": finding.finding_class.value,
            "track": finding.track.value,
            "reason": "curation_finding_proposed",
        },
    )
    append_jsonl_outbox_event(Path(outbox_path), event, default_source="curation.proposal_writer")


__all__ = [
    "AUTOFIX_APPLY_ENV",
    "CURATION_PROPOSE_WRITE_ACTION",
    "autofix_apply_enabled",
    "write_curation_proposals",
]
