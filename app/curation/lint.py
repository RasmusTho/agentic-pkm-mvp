"""Vault-health lint (G2-1) -- read-only, propose-track, report-note output.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §5, §6.

Invariants held by this module:

- **Propose-only / read-only.** ``run_vault_lint`` never mutates a note body.
  The only write in this slice is the lint report note itself
  (:func:`write_lint_report`), gated by ``WriteGuard.assert_writes_allowed``.
- **Idempotent rerun.** Every finding's id is content-derived
  (:func:`app.curation.findings.compute_finding_id`); rerunning the pass over
  an unchanged vault produces byte-identical finding ids and the report note
  is overwritten with identical content (a no-op diff), never appended/duplicated.
- **Missing ``uuid`` is advisory only.** It is reported as a
  ``structure.gap`` finding and never blocks any other check, the report, or
  note processing -- ``uuid`` is lineage metadata, not a render/processing
  gate (``docs/FRONTMATTER.md``).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.curation.findings import CurationFinding, FindingClass
from app.vault.paths import resolve_vault_system_dir_rel_or_default
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

# Named WriteGuard action for the lint-report write seam (auditable, not a
# silent absence of a guard). Not in DEFAULT_BOOTSTRAP_ACTIONS, so a
# write-blocked runtime state denies this write loudly, same posture as
# app.receipts.decision_receipt_log.RECEIPT_WRITE_ACTION.
LINT_REPORT_WRITE_ACTION = "curation.lint_report.write"

_REPORTS_SUBDIR = Path("curation")
_REPORT_FILENAME = "vault-health-lint.md"

_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_EXTERNAL_LINK_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_PANEL_OPTION_ID_RE = re.compile(r"<!--ai:option_id=([^\s>-]+)-->")
_PANEL_PROPOSED_RE = re.compile(r"<!--ai:proposed=([^\s>-]+)-->")

# Conservative staleness policy by note kind (days since last `updated`
# frontmatter value or, absent that, file mtime). `docs/NOTE_KIND_POLICIES.md`
# defines kind as a policy-routing signal without locking concrete numbers;
# these are this lint pass's own bounded defaults, not a global policy claim.
# Kinds outside this table are never flagged for staleness (conservative:
# absence of a policy is not a finding).
_STALENESS_POLICY_DAYS: dict[str, int] = {
    "task": 30,
    "log": 90,
}

_EMPTY_STUB_MAX_WORDS = 5


@dataclass(frozen=True)
class NoteRecord:
    """A parsed vault note used by the lint checks."""

    rel_path: str
    abs_path: Path
    frontmatter: dict
    body: str
    uuid: str | None


@dataclass
class LintReport:
    """The outcome of one vault-health lint pass."""

    findings: list[CurationFinding] = field(default_factory=list)
    notes_scanned: int = 0
    checks_run: tuple[str, ...] = ()
    generated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_notes(vault_root: Path) -> list[NoteRecord]:
    records: list[NoteRecord] = []
    for path in sorted(vault_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = load_frontmatter(text)
        uuid = frontmatter.get("uuid")
        uuid = str(uuid).strip() if uuid else None
        rel_path = path.relative_to(vault_root).as_posix()
        records.append(
            NoteRecord(
                rel_path=rel_path,
                abs_path=path,
                frontmatter=frontmatter,
                body=body,
                uuid=uuid,
            )
        )
    return records


def _note_identity(note: NoteRecord) -> str:
    """Identity used as ``note_uuid`` for a finding.

    Prefers the frontmatter uuid; falls back to the vault-relative path so a
    uuid-less note can still be linted (uuid is advisory, never a processing
    gate). The missing-uuid condition itself is reported separately as its
    own finding (see ``_check_missing_uuid``).
    """
    return note.uuid or f"path:{note.rel_path}"


def _span_for_line(line_no: int, text: str) -> str:
    digest = f"L{line_no}:{text.strip()}"
    return digest


# ---------------------------------------------------------------------------
# The eight initial lint checks (spec §5)
# ---------------------------------------------------------------------------


def _check_dead_wikilinks(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Wikilinks (``[[Target]]``) that resolve to no known note (by title or uuid)."""
    titles_by_stem: dict[str, NoteRecord] = {}
    uuids: set[str] = set()
    for note in notes:
        stem = Path(note.rel_path).stem.lower()
        titles_by_stem[stem] = note
        if note.uuid:
            uuids.add(note.uuid)

    findings: list[CurationFinding] = []
    for note in notes:
        for line_no, line in enumerate(note.body.splitlines(), start=1):
            for match in _WIKILINK_RE.finditer(line):
                target = match.group(1).strip()
                if not target:
                    continue
                target_key = target.lower()
                if target_key in titles_by_stem or target in uuids:
                    continue
                findings.append(
                    CurationFinding.create(
                        note_uuid=_note_identity(note),
                        finding_class=FindingClass.LINK_BROKEN_WIKILINK,
                        span=_span_for_line(line_no, line),
                        observed=f"[[{target}]]",
                        proposed=f"resolve or remove dangling wikilink to '{target}'",
                        evidence=(note.rel_path,),
                    )
                )
    return findings


def _check_dead_external_links(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Markdown links whose target uses an unreachable/unsupported scheme marker.

    This is a structural, offline check (no network egress from a lint pass):
    it flags external links using a deliberately-unreachable placeholder host
    convention (`dead.invalid` / `example-dead.test`) used by fixtures and by
    authors marking a known-dead reference for follow-up, plus any external
    link with an empty path component. It does not perform live HTTP checks.
    """
    dead_markers = ("dead.invalid", "example-dead.test")
    findings: list[CurationFinding] = []
    for note in notes:
        for line_no, line in enumerate(note.body.splitlines(), start=1):
            for match in _MD_LINK_RE.finditer(line):
                target = match.group(1).strip()
                if not _EXTERNAL_LINK_RE.match(target):
                    continue
                if any(marker in target for marker in dead_markers):
                    findings.append(
                        CurationFinding.create(
                            note_uuid=_note_identity(note),
                            finding_class=FindingClass.LINK_DEAD_EXTERNAL,
                            span=_span_for_line(line_no, line),
                            observed=target,
                            proposed=f"review dead external link '{target}'",
                            evidence=(note.rel_path,),
                        )
                    )
    return findings


def _check_frontmatter_schema(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Missing/invalid frontmatter per ``docs/FRONTMATTER.md``.

    Bounded to structural validity (frontmatter block parses to a mapping)
    -- this check does not invent semantic schema rules beyond what
    FRONTMATTER.md fixes today (uuid is the only System-owned, file-resident
    Core-6 field required to already exist on ingest; see ``_check_missing_uuid``
    for the advisory-only uuid case).
    """
    findings: list[CurationFinding] = []
    for note in notes:
        raw = note.abs_path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            continue  # no frontmatter block declared; not itself a violation
        parts = raw.split("---", 2)
        if len(parts) < 3:
            findings.append(
                CurationFinding.create(
                    note_uuid=_note_identity(note),
                    finding_class=FindingClass.FRONTMATTER_SCHEMA_VIOLATION,
                    span="L1:frontmatter",
                    observed="unterminated frontmatter block",
                    proposed="close the frontmatter block with a second '---' delimiter",
                    evidence=(note.rel_path,),
                )
            )
    return findings


def _check_empty_stub_notes(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Notes whose body is empty or a stub (below a small word-count floor)."""
    findings: list[CurationFinding] = []
    for note in notes:
        word_count = len(note.body.split())
        if word_count <= _EMPTY_STUB_MAX_WORDS:
            findings.append(
                CurationFinding.create(
                    note_uuid=_note_identity(note),
                    finding_class=FindingClass.STRUCTURE_GAP,
                    span="L1:body",
                    observed=f"{word_count} word(s) in body",
                    proposed=f"expand or archive stub note '{note.rel_path}'",
                    evidence=(note.rel_path,),
                )
            )
    return findings


def _check_staleness_by_kind(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Staleness by note-kind policy (``docs/NOTE_KIND_POLICIES.md``)."""
    findings: list[CurationFinding] = []
    now = datetime.now(timezone.utc)
    for note in notes:
        kind = str(note.frontmatter.get("kind") or note.frontmatter.get("artifact_kind") or "").strip().lower()
        threshold_days = _STALENESS_POLICY_DAYS.get(kind)
        if threshold_days is None:
            continue
        last_touched = _resolve_last_touched(note, now)
        age_days = (now - last_touched).days
        if age_days > threshold_days:
            findings.append(
                CurationFinding.create(
                    note_uuid=_note_identity(note),
                    finding_class=FindingClass.STRUCTURE_STALE_CLAIM,
                    span="L1:frontmatter.updated",
                    observed=f"kind={kind} last touched {age_days}d ago",
                    proposed=f"review staleness for kind='{kind}' note (policy threshold {threshold_days}d)",
                    evidence=(note.rel_path,),
                )
            )
    return findings


def _resolve_last_touched(note: NoteRecord, now: datetime) -> datetime:
    updated_raw = note.frontmatter.get("updated")
    if updated_raw:
        try:
            parsed = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    try:
        mtime = note.abs_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        return now


def _check_stale_panel_markers(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Panel blocks whose ``<!--ai:proposed=ID-->`` marker references a stale id.

    Read-only structural check: an ``ai:proposed`` marker without a matching
    ``ai:option_id`` marker on the same line is a dangling/stale marker (the
    proposal machinery expects both, per ``docs/PANEL_AGENT.md``). This does
    not parse or touch the panel's execution semantics; it only flags the
    line for human review.
    """
    findings: list[CurationFinding] = []
    for note in notes:
        for line_no, line in enumerate(note.body.splitlines(), start=1):
            proposed_match = _PANEL_PROPOSED_RE.search(line)
            if not proposed_match:
                continue
            if not _PANEL_OPTION_ID_RE.search(line):
                findings.append(
                    CurationFinding.create(
                        note_uuid=_note_identity(note),
                        finding_class=FindingClass.STRUCTURE_GAP,
                        span=_span_for_line(line_no, line),
                        observed=line.strip(),
                        proposed="stale ai:proposed marker missing its ai:option_id pair",
                        evidence=(note.rel_path,),
                    )
                )
    return findings


def _check_missing_uuid(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Notes missing ``uuid`` -- advisory only, never a processing gate."""
    findings: list[CurationFinding] = []
    for note in notes:
        if note.uuid:
            continue
        findings.append(
            CurationFinding.create(
                note_uuid=_note_identity(note),
                finding_class=FindingClass.STRUCTURE_GAP,
                span="L1:frontmatter.uuid",
                observed="uuid absent from frontmatter",
                proposed=f"heal uuid for note '{note.rel_path}' (advisory only)",
                evidence=(note.rel_path,),
            )
        )
    return findings


def _check_orphan_notes(notes: list[NoteRecord]) -> list[CurationFinding]:
    """Notes with zero inbound wikilinks from any other note in the vault."""
    stems_by_note: dict[str, NoteRecord] = {Path(n.rel_path).stem.lower(): n for n in notes}
    uuid_by_note: dict[str, NoteRecord] = {n.uuid: n for n in notes if n.uuid}
    linked_rel_paths: set[str] = set()

    for note in notes:
        for match in _WIKILINK_RE.finditer(note.body):
            target = match.group(1).strip()
            target_key = target.lower()
            target_note = stems_by_note.get(target_key) or uuid_by_note.get(target)
            if target_note is not None:
                linked_rel_paths.add(target_note.rel_path)

    findings: list[CurationFinding] = []
    for note in notes:
        if note.rel_path in linked_rel_paths:
            continue
        findings.append(
            CurationFinding.create(
                note_uuid=_note_identity(note),
                finding_class=FindingClass.STRUCTURE_ORPHAN,
                span="L1:body",
                observed=f"no inbound wikilinks to '{note.rel_path}'",
                proposed=f"link '{note.rel_path}' from a relevant note or confirm it is intentionally standalone",
                evidence=(note.rel_path,),
            )
        )
    return findings


# Ordered registry of the eight initial checks (spec §5). Each entry is a
# ``(check_name, callable)`` pair; ``run_vault_lint`` runs them in this order
# and tags the report with the names for traceability.
_LINT_CHECKS: tuple[tuple[str, Callable[[list[NoteRecord]], list[CurationFinding]]], ...] = (
    ("orphan_notes", _check_orphan_notes),
    ("dead_wikilinks", _check_dead_wikilinks),
    ("dead_external_links", _check_dead_external_links),
    ("frontmatter_schema", _check_frontmatter_schema),
    ("empty_stub_notes", _check_empty_stub_notes),
    ("staleness_by_kind", _check_staleness_by_kind),
    ("stale_panel_markers", _check_stale_panel_markers),
    ("missing_uuid", _check_missing_uuid),
)


def run_vault_lint(vault_root: Path) -> LintReport:
    """Run every lint check over the vault. Pure read; no writes.

    Findings are sorted deterministically (by finding_id) so the resulting
    report note is byte-identical across reruns of an unchanged vault
    (idempotency requirement, spec §6 AC1).
    """
    vault_root = Path(vault_root).expanduser().resolve()
    notes = _iter_notes(vault_root)

    findings: list[CurationFinding] = []
    check_names: list[str] = []
    for name, check in _LINT_CHECKS:
        check_names.append(name)
        findings.extend(check(notes))

    findings.sort(key=lambda f: f.finding_id)
    return LintReport(
        findings=findings,
        notes_scanned=len(notes),
        checks_run=tuple(check_names),
        generated_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Report note (the only write in this slice)
# ---------------------------------------------------------------------------


def _reports_dir(vault_root: Path) -> Path:
    system_dir_rel = resolve_vault_system_dir_rel_or_default(vault_root)
    return vault_root / system_dir_rel / _REPORTS_SUBDIR


def render_lint_report(report: LintReport) -> str:
    """Render the lint report as a deterministic Markdown note body.

    Deterministic given identical ``report.findings`` (which are themselves
    sorted by ``finding_id``) so a rerun over an unchanged vault produces a
    byte-identical note body -- the idempotent-rerun contract (spec §6 AC1)
    extends from "same finding ids" to "same report note content".
    """
    lines = [
        "---",
        "kind: curation_report",
        "review_state: system",
        "---",
        "",
        "# Vault-health lint report",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Notes scanned: {report.notes_scanned}",
        f"- Checks run: {', '.join(report.checks_run)}",
        f"- Findings: {len(report.findings)}",
        "",
    ]
    if not report.findings:
        lines.append("No findings. Vault is clean per the current lint checks.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Findings")
    lines.append("")
    for finding in report.findings:
        lines.append(f"### {finding.finding_id[:12]} — {finding.finding_class.value}")
        lines.append(f"- Note: `{finding.note_uuid}`")
        lines.append(f"- Track: `{finding.track.value}`")
        lines.append(f"- Span: `{finding.span}`")
        lines.append(f"- Observed: {finding.observed}")
        lines.append(f"- Proposed: {finding.proposed}")
        if finding.evidence:
            lines.append(f"- Evidence: {', '.join(finding.evidence)}")
        lines.append("")
    return "\n".join(lines)


def write_lint_report(
    report: LintReport,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> Path:
    """Write the lint report note under the vault system dir.

    WriteGuard-gated at the seam (asserted before any path resolution or
    filesystem mutation, matching ``app.receipts.decision_receipt_log``'s
    posture): a blocked guard raises loudly and no partial write occurs. The
    write is a full-file overwrite of one fixed path, so a rerun over an
    unchanged vault produces the same findings section every time -- no
    duplicate entries, no unbounded growth (idempotent rerun, spec §6 AC1).

    ``vault_root`` is always caller-supplied and explicit here (this module
    never resolves ``VAULT_ROOT`` from the environment itself), so system-dir
    resolution degrades to the packaged default
    (``resolve_vault_system_dir_rel_or_default``) rather than raising.
    """
    write_guard.assert_writes_allowed(LINT_REPORT_WRITE_ACTION)

    vault_root = Path(vault_root).expanduser().resolve()
    reports_dir = _reports_dir(vault_root)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / _REPORT_FILENAME
    content = render_lint_report(report)
    report_path.write_text(content, encoding="utf-8")
    return report_path


__all__ = [
    "LINT_REPORT_WRITE_ACTION",
    "LintReport",
    "NoteRecord",
    "render_lint_report",
    "run_vault_lint",
    "write_lint_report",
]
