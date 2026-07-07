#!/usr/bin/env python3
"""One-time deep curation/connect pass run tooling (E9, #3000).

Spec anchors: ``docs/MIMER_CAPABILITY_HARDENING/README.md`` §Sequencing
(Track E, E9), §Risk register; ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md``
§4; ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §1-2.

This script is RUN TOOLING ONLY. It wires the already-reviewed, already-tested
E1-E8 harness library functions together end to end over a real vault and
emits one consolidated run receipt. It adds no new cognition, no new
authority tier, and no new write path -- every write this script triggers is
a call into one of those existing library functions, unchanged, using the
exact call shapes their own tests already exercise
(``tests/invariants/test_expansion_invariants.py::test_create_never_autowrites_canonical``,
``::test_connect_proposals_are_candidate_only`` and siblings).

Order (per issue #3000):
  1. E1 finding pipeline    -- ``app.curation.lint.run_vault_lint``
  2. E2 proposal writer     -- ``app.curation.proposal_writer.write_curation_proposals``
  3. E3 connect pass        -- ``app.expansion.connect.run_connect_pass``
  4. E7 cluster -> create   -- ``app.expansion.connect.find_cluster_emergence`` /
                                ``cluster_emergence_to_create_request`` feeding
                                ``app.expansion.create.run_create_pass`` (the ONLY
                                create-engine path this run uses)
  5. E8 contradiction pass  -- ``app.curation.contradiction.run_contradiction_pass``

Every pass that accepts a declined-ledger config knob is given the SAME
``app.proposals.declined_ledger.default_declined_ledger()`` instance, so a
human decline recorded during any earlier run of this script (or of the
normal per-slice UI) is honored uniformly across all five passes.

No model call, no LLM/Fable invocation of any kind happens here -- this is
deterministic harness wiring. The offline, owner-scheduled, Fable-5-or-best-
available-frontier-model judgment work this tooling exists to run is a
separate operational step (outside this script and this PR).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.curation.contradiction import ContradictionPassConfig, run_contradiction_pass
from app.curation.lint import run_vault_lint
from app.curation.proposal_writer import write_curation_proposals
from app.expansion.connect import (
    ClusterEmergenceConfig,
    ConnectPassConfig,
    cluster_emergence_to_create_request,
    find_cluster_emergence,
    run_connect_pass,
)
from app.expansion.create import DEFAULT_STALENESS_DAYS, SourceInput, UnresolvableCitationError, run_create_pass
from app.proposals.declined_ledger import default_declined_ledger
from app.runtime.runtime_loop import resolve_outbox_path
from app.services.outbox import append_jsonl_outbox_event
from app.vault.paths import resolve_vault_system_dir_rel_or_default
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Event name for the one consolidated receipt this script emits (dotted
# <module>.<verb> convention, mirroring ``curation.propose_write`` /
# ``expansion.create.proposed``). Never used to gate a write -- WriteGuard
# gating already happened inside each per-pass call this script makes; this
# receipt is pure observability, emitted through the same
# ``append_jsonl_outbox_event`` mechanism every other pass already uses.
DEEP_PASS_RECEIPT_EVENT = "expansion.deep_pass.completed"
DEEP_PASS_EVENT_SOURCE = "scripts.run_expansion_deep_pass"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PassCaps:
    """Per-pass cap / config knobs exposed as CLI flags, one field per knob
    each library pass config already accepts. Defaults mirror each library
    module's own private defaults exactly -- this script invents no new cap
    value, it only surfaces the existing ones as flags."""

    connect_max_findings_per_note: int
    connect_max_findings_total: int
    connect_retrieval_k: int
    connect_relatedness_floor: float
    cluster_min_size: int
    cluster_max_clusters: int
    contradiction_max_findings_per_note: int
    contradiction_max_findings_total: int
    contradiction_retrieval_k: int
    create_staleness_days: int
    max_query_notes: int


@dataclass
class PassOutcome:
    """One row in the consolidated receipt (per-pass observability numbers,
    AC-required shape: notes scanned / findings emitted / suppressed-by-
    decline / suppressed-by-cap)."""

    name: str
    notes_scanned: int = 0
    findings_emitted: int = 0
    suppressed_by_decline: int = 0
    suppressed_by_cap: int = 0
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "pass": self.name,
            "notes_scanned": self.notes_scanned,
            "findings_emitted": self.findings_emitted,
            "suppressed_by_decline": self.suppressed_by_decline,
            "suppressed_by_cap": self.suppressed_by_cap,
        }
        if self.extra:
            row["extra"] = self.extra
        return row


def _iter_vault_notes(vault_root: Path) -> list[Path]:
    """Every markdown note under *vault_root*, excluding the vault system
    dir (reports/drafts/companions live there and must not feed back into
    themselves as retrieval-seeding queries). Deterministic (sorted) order."""

    system_dir_rel = resolve_vault_system_dir_rel_or_default(vault_root)
    system_dir = (vault_root / system_dir_rel).resolve()
    notes: list[Path] = []
    for path in sorted(vault_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(system_dir)
        except ValueError:
            notes.append(path)
        else:
            continue
    return notes


def _note_query(path: Path, vault_root: Path) -> str:
    """A bounded, deterministic retrieval-seed query for one note: its
    frontmatter/H1 title if present, else the filename stem (mirrors the
    connect pass's own docstring: "one per note title/topic under review")."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:200]
    return path.stem


def _build_queries(vault_root: Path, *, max_query_notes: int) -> list[str]:
    """Bounded, deterministic query list seeding the connect + contradiction
    retrieval passes. Capped by ``max_query_notes`` -- this is the one place
    this script itself could grow an unbounded loop over a large vault, so it
    is bounded explicitly rather than left open."""

    notes = _iter_vault_notes(vault_root)[:max_query_notes]
    queries = [_note_query(path, vault_root) for path in notes]
    # Deterministic de-dup, order-preserving.
    seen: set[str] = set()
    deduped: list[str] = []
    for query in queries:
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def _resolve_note_path(note_uuid: str, vault_root: Path, *, evidence: tuple[str, ...]) -> Path | None:
    """Resolve a vault-relative note path from a finding's ``note_uuid`` /
    ``evidence``, mirroring
    ``app.curation.proposal_writer._note_path_from_finding``'s identity
    convention (real uuid vs ``path:<rel>`` fallback) without importing that
    private helper directly."""

    if note_uuid.startswith("path:"):
        candidate = vault_root / note_uuid[len("path:") :]
        return candidate if candidate.exists() else None
    if evidence:
        candidate = vault_root / evidence[0]
        if candidate.exists():
            return candidate
    return None


def run_lint_and_propose(
    *,
    vault_root: Path,
    outbox_path: Path,
    write_guard: WriteGuard,
    dry_run: bool,
) -> PassOutcome:
    """E1 (finding pipeline) -> E2 (propose-track materialization)."""

    report = run_vault_lint(vault_root)
    outcome = PassOutcome(name="lint_and_propose", notes_scanned=report.notes_scanned)
    outcome.findings_emitted = len(report.findings)
    if dry_run or not report.findings:
        return outcome

    unresolved = write_curation_proposals(
        report.findings,
        vault_root=vault_root,
        write_guard=write_guard,
        outbox_path=outbox_path,
    )
    outcome.extra = {"unresolved_note_path": len(unresolved)}
    return outcome


def run_connect(
    *,
    vault_root: Path,
    queries: list[str],
    caps: PassCaps,
    declined_ledger,
    outbox_path: Path,
    write_guard: WriteGuard,
    dry_run: bool,
) -> tuple[PassOutcome, tuple]:
    """E3 connect pass. Returns the outcome plus the raw
    ``related_unlinked``-class findings (needed to seed E7 cluster
    emergence -- ``find_cluster_emergence`` reuses this pass's already-
    computed pair graph, never re-queries retrieval)."""

    config = ConnectPassConfig(
        max_findings_per_note=caps.connect_max_findings_per_note,
        max_findings_total=caps.connect_max_findings_total,
        retrieval_k=caps.connect_retrieval_k,
        relatedness_floor=caps.connect_relatedness_floor,
        declined_ledger=declined_ledger,
    )
    report = run_connect_pass(
        vault_root=vault_root,
        queries=queries,
        config=config,
        write_guard=write_guard,
        outbox_path=outbox_path,
        materialize=not dry_run,
    )
    outcome = PassOutcome(
        name="connect",
        notes_scanned=report.notes_scanned,
        findings_emitted=len(report.findings),
        suppressed_by_decline=report.suppressed_by_decline,
        suppressed_by_cap=report.suppressed_by_cap,
        extra={
            "suppressed_by_cross_scope_denial": report.suppressed_by_cross_scope_denial,
            "denials": list(report.denials),
        },
    )
    return outcome, report.findings


def run_cluster_to_create(
    *,
    vault_root: Path,
    connect_findings: tuple,
    caps: PassCaps,
    declined_ledger,
    outbox_path: Path,
    write_guard: WriteGuard,
    dry_run: bool,
) -> tuple[PassOutcome, PassOutcome]:
    """E7: cluster emergence detection (propose-track, materialized exactly
    like every other finding class) -> Create pass over each detected,
    non-declined, non-capped cluster (the ONLY create-engine path this run
    uses -- every request handed to ``run_create_pass`` here is built by
    ``cluster_emergence_to_create_request`` from a real
    ``connect.cluster_emergence`` finding, never a freeform/synthesis
    request)."""

    cluster_config = ClusterEmergenceConfig(
        min_cluster_size=caps.cluster_min_size,
        max_clusters=caps.cluster_max_clusters,
        declined_ledger=declined_ledger,
    )
    cluster_report = find_cluster_emergence(connect_findings, config=cluster_config)

    cluster_outcome = PassOutcome(
        name="cluster_emergence",
        findings_emitted=len(cluster_report.findings),
        suppressed_by_decline=cluster_report.suppressed_by_decline,
        suppressed_by_cap=cluster_report.suppressed_by_cap,
        extra={"clusters_found": cluster_report.clusters_found},
    )

    create_outcome = PassOutcome(name="cluster_to_create")

    if dry_run or not cluster_report.findings:
        return cluster_outcome, create_outcome

    # Materialize the cluster findings themselves as propose-track checkboxes
    # first, same discipline as every other finding class (candidate-only).
    write_curation_proposals(
        cluster_report.findings,
        vault_root=vault_root,
        write_guard=write_guard,
        outbox_path=outbox_path,
    )

    # Group findings by finding_id (one logical cluster per id, one
    # CurationFinding per member note).
    clusters_by_id: dict[str, list] = {}
    for finding in cluster_report.findings:
        clusters_by_id.setdefault(finding.finding_id, []).append(finding)

    drafts_created = 0
    blocked = 0
    citation_unresolved = 0

    for finding_id, members in sorted(clusters_by_id.items()):
        member_uuids = [f.note_uuid for f in members]
        member_sources: dict[str, SourceInput] = {}
        resolvable = True
        for member in members:
            note_path = _resolve_note_path(member.note_uuid, vault_root, evidence=member.evidence)
            if note_path is None:
                resolvable = False
                break
            try:
                text = note_path.read_text(encoding="utf-8")
            except OSError:
                resolvable = False
                break
            member_sources[member.note_uuid] = SourceInput(
                object_id=member.note_uuid,
                note_path=str(note_path.relative_to(vault_root)),
                text=text,
                # No quoted span is asserted here -- the retrieval snippet
                # captured at finding-emission time is not guaranteed to
                # still be a byte-verbatim substring of the note's current
                # text, and citation validation would fail loud rather than
                # silently drop a mismatched quote. An empty quoted_spans
                # tuple is a fully valid, already-tested SourceInput shape
                # (``_validate_citations`` only requires non-empty text).
                quoted_spans=(),
            )
        if not resolvable:
            blocked += 1
            continue

        title = f"Cluster overview: {', '.join(sorted(member_uuids))}"[:200]
        request = cluster_emergence_to_create_request(
            frozenset(member_uuids),
            member_sources=member_sources,
            title=title,
        )
        try:
            create_report = run_create_pass(
                request,
                vault_root=vault_root,
                outbox_path=outbox_path,
                write_guard=write_guard,
                staleness_days=caps.create_staleness_days,
            )
        except UnresolvableCitationError:
            citation_unresolved += 1
            continue

        if create_report.activatable:
            drafts_created += 1
        else:
            blocked += 1

    create_outcome.findings_emitted = drafts_created
    create_outcome.extra = {
        "clusters_considered": len(clusters_by_id),
        "drafts_created": drafts_created,
        "blocked": blocked,
        "citation_unresolved": citation_unresolved,
    }
    return cluster_outcome, create_outcome


def run_contradiction(
    *,
    vault_root: Path,
    queries: list[str],
    caps: PassCaps,
    declined_ledger,
    outbox_path: Path,
    write_guard: WriteGuard,
    dry_run: bool,
) -> PassOutcome:
    """E8 contradiction pass."""

    config = ContradictionPassConfig(
        max_findings_per_note=caps.contradiction_max_findings_per_note,
        max_findings_total=caps.contradiction_max_findings_total,
        retrieval_k=caps.contradiction_retrieval_k,
        declined_ledger=declined_ledger,
    )
    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=queries,
        config=config,
        write_guard=write_guard,
        outbox_path=outbox_path,
        materialize=not dry_run,
    )
    return PassOutcome(
        name="contradiction",
        notes_scanned=report.pairs_considered,
        findings_emitted=len(report.findings),
        suppressed_by_decline=report.suppressed_by_decline,
        suppressed_by_cap=report.suppressed_by_cap,
        extra={
            "suppressed_by_cross_scope_denial": report.suppressed_by_cross_scope_denial,
            "denials": list(report.denials),
        },
    )


def emit_consolidated_receipt(
    outcomes: list[PassOutcome],
    *,
    vault_root: Path,
    outbox_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Aggregate every pass's own receipt/report into ONE consolidated
    run receipt, emitted through the same ``append_jsonl_outbox_event``
    mechanism every per-pass receipt already uses (never a parallel receipt
    system)."""

    totals = {
        "notes_scanned": sum(o.notes_scanned for o in outcomes),
        "findings_emitted": sum(o.findings_emitted for o in outcomes),
        "suppressed_by_decline": sum(o.suppressed_by_decline for o in outcomes),
        "suppressed_by_cap": sum(o.suppressed_by_cap for o in outcomes),
    }
    record = {
        "event": DEEP_PASS_RECEIPT_EVENT,
        "event_id": uuid.uuid4().hex,
        "trace_id": uuid.uuid4().hex,
        "source": DEEP_PASS_EVENT_SOURCE,
        "timestamp": _iso_now(),
        "payload": {
            "vault_root": str(vault_root),
            "dry_run": dry_run,
            "totals": totals,
            "passes": [o.to_dict() for o in outcomes],
        },
    }
    if not dry_run:
        append_jsonl_outbox_event(outbox_path, record, default_source=DEEP_PASS_EVENT_SOURCE)
    return record


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the E1-E8 curation/expansion harness once, end to end, over a real "
            "vault, and emit one consolidated run receipt (issue #3000, E9 run tooling)."
        )
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        required=True,
        help="Path to the vault to run against. Required -- never falls back to the repo's vault/ fixture.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run every pass's read-only detection logic but skip every materializing write "
            "(proposal checkboxes, cluster checkboxes, Create staged drafts) and skip the outbox "
            "receipt write; the consolidated receipt is printed to stdout instead."
        ),
    )
    parser.add_argument("--outbox-path", type=Path, default=None, help="Override the outbox path (defaults to the repo's standard INDEX_OUTBOX_PATH resolution).")
    parser.add_argument("--connect-max-findings-per-note", type=int, default=3)
    parser.add_argument("--connect-max-findings-total", type=int, default=25)
    parser.add_argument("--connect-retrieval-k", type=int, default=8)
    parser.add_argument("--connect-relatedness-floor", type=float, default=0.55)
    parser.add_argument("--cluster-min-size", type=int, default=3)
    parser.add_argument("--cluster-max-clusters", type=int, default=10)
    parser.add_argument("--contradiction-max-findings-per-note", type=int, default=3)
    parser.add_argument("--contradiction-max-findings-total", type=int, default=25)
    parser.add_argument("--contradiction-retrieval-k", type=int, default=8)
    parser.add_argument("--create-staleness-days", type=int, default=DEFAULT_STALENESS_DAYS)
    parser.add_argument(
        "--max-query-notes",
        type=int,
        default=500,
        help="Cap on the number of notes used to seed connect/contradiction retrieval queries (bounded, deterministic).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    vault_root = Path(args.vault_root).expanduser().resolve()
    if not vault_root.exists() or not vault_root.is_dir():
        print(f"error: --vault-root {vault_root} does not exist or is not a directory", file=sys.stderr)
        return 2

    outbox_path = resolve_outbox_path(args.outbox_path)
    write_guard = DEFAULT_WRITE_GUARD
    declined_ledger = default_declined_ledger()

    caps = PassCaps(
        connect_max_findings_per_note=args.connect_max_findings_per_note,
        connect_max_findings_total=args.connect_max_findings_total,
        connect_retrieval_k=args.connect_retrieval_k,
        connect_relatedness_floor=args.connect_relatedness_floor,
        cluster_min_size=args.cluster_min_size,
        cluster_max_clusters=args.cluster_max_clusters,
        contradiction_max_findings_per_note=args.contradiction_max_findings_per_note,
        contradiction_max_findings_total=args.contradiction_max_findings_total,
        contradiction_retrieval_k=args.contradiction_retrieval_k,
        create_staleness_days=args.create_staleness_days,
        max_query_notes=args.max_query_notes,
    )

    queries = _build_queries(vault_root, max_query_notes=caps.max_query_notes)

    outcomes: list[PassOutcome] = []

    outcomes.append(
        run_lint_and_propose(
            vault_root=vault_root,
            outbox_path=outbox_path,
            write_guard=write_guard,
            dry_run=args.dry_run,
        )
    )

    connect_outcome, connect_findings = run_connect(
        vault_root=vault_root,
        queries=queries,
        caps=caps,
        declined_ledger=declined_ledger,
        outbox_path=outbox_path,
        write_guard=write_guard,
        dry_run=args.dry_run,
    )
    outcomes.append(connect_outcome)

    cluster_outcome, create_outcome = run_cluster_to_create(
        vault_root=vault_root,
        connect_findings=connect_findings,
        caps=caps,
        declined_ledger=declined_ledger,
        outbox_path=outbox_path,
        write_guard=write_guard,
        dry_run=args.dry_run,
    )
    outcomes.append(cluster_outcome)
    outcomes.append(create_outcome)

    outcomes.append(
        run_contradiction(
            vault_root=vault_root,
            queries=queries,
            caps=caps,
            declined_ledger=declined_ledger,
            outbox_path=outbox_path,
            write_guard=write_guard,
            dry_run=args.dry_run,
        )
    )

    receipt = emit_consolidated_receipt(
        outcomes,
        vault_root=vault_root,
        outbox_path=outbox_path,
        dry_run=args.dry_run,
    )
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
