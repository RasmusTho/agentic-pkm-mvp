"""Contradiction pass: sourced claim-conflict harness (G2-4, EXP sibling, #2999).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4, §6 (G2-4).
Parent: #2980 (Capability Hardening / Cognitive Expansion). This is a sibling
Expansion pass: it reuses the EXP-1 Connect pass's harness shape
(``app.expansion.connect``) and EXP-2's declined-proposal ledger
(``app.proposals.declined_ledger``) rather than forking either. It emits
``contradiction.claim_conflict`` findings (class already enumerated in E1's
closed table, ``app.curation.findings.FindingClass``) through the existing
G2-2 propose writer (``app.curation.proposal_writer``) -- it never invents a
new note surface.

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.expansion.connect``'s and
``app.curation.proposal_writer``'s posture):

- **Candidate-only by construction.** ``contradiction.claim_conflict`` is a
  ``propose``-track class in the closed enum
  (``app.curation.findings.MECHANICAL_ALLOWLIST`` never contains it -- see
  the table in ``GRADUATED_CURATION.md`` §1). This module has no code path,
  and no configuration flag, that materializes a contradiction finding as a
  body edit: the only write this module performs is handing findings to
  ``write_curation_proposals``, which only ever inserts unchecked
  ``AI-åtgärder`` checkboxes (never a checked box, never a
  ``[!contradiction]`` callout). The callout itself is explicitly **out of
  this module's write surface** -- per spec §4, it "rides the confirmed
  action, never the pass" -- so this module contains zero callout-writing
  code.
- **``curation_citations_resolve``: every emitted finding carries >=2
  resolvable in-vault sources.** :func:`_resolvable_citations` re-derives,
  from the *current* vault state, which of a finding's candidate citations
  (wikilink targets or ``uuid:``-anchored references) actually resolve to a
  note file that exists right now. A candidate finding whose resolvable-count
  drops below 2 is **voided** -- never emitted, never materialized with a
  dangling cite (spec: "an unresolvable citation voids the finding rather
  than materializing an uncited callout"). This is re-checked at
  materialization time, not only at detection time, so a citation that
  resolved during retrieval but was deleted before the pass writes checkboxes
  still voids the finding.
- **Retrieval-grounded, evidence clamped to ``background``.** Candidates come
  only from :func:`app.retrieval.capability.retrieve`, exactly like Connect.
  This module never claims an ``evidence`` role for retrieval-derived
  material -- every finding's supporting spans are ``background`` salience
  signal (mirrors ``app.expansion.connect.CONNECT_EVIDENCE_ROLE``).
- **Scope is hard.** A cross-scope candidate pair is proposed only under an
  existing ``surface``-operation ``CrossScopeFlow`` grant (the identical
  mechanism ``app.expansion.connect`` uses); absent a grant the pair is
  silently, content-freely excluded (KERNEL-10) -- never surfaced, never
  logged with any identifying content. This pass never receives
  ``cite``/``import`` authority on cross-scope material, only ``surface``.
- **Idempotent + decline-aware.** ``finding_id`` is content-derived
  (``app.curation.findings.compute_finding_id``, keyed on the unordered claim
  pair + span) so a rerun over an unchanged vault is a provable no-op. Every
  pass consults the shared :class:`app.expansion.connect.DeclinedLedgerPort`
  (backed by the real ``app.proposals.declined_ledger.DeclinedLedger``)
  before emitting a finding: a declined contradiction is suppressed exactly
  like any other proposal-emitting pass, until its content basis changes.
- **Never adjudicates.** This module records both claims verbatim and a
  one-line agent interpretation; it never decides, ranks, or implies which
  claim is correct (spec: "surfaces the tension, does not resolve it").
- **CLI-invoked, explicit only.** This module never wires itself into a tick
  or watcher loop; it is only ever invoked directly (by a CLI entry point or
  a test), matching spec §4's "explicit invocation, never tick-driven".
- **Offline curation task kind.** :data:`CURATION_CONTRADICTION_TASK_KIND`
  declares the ``curation.contradiction`` task-kind label this pass' model
  calls should carry once RUNTIME_MODEL_POSTURE's paid-tier routing exists
  (Track P, not filed) -- this module only declares the label; it implements
  no routing policy and makes no paid-tier call itself.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.curation.findings import CurationFinding, FindingClass, LanguageVerdict, track_for_class
from app.curation.proposal_writer import write_curation_proposals
from app.expansion.connect import (
    CrossScopeFlow,
    DeclinedLedgerPort,
    default_declined_ledger,
)
from app.retrieval.capability import RetrievalRequest, RetrievalResponse, retrieve
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Reuses the identical wikilink shape as app.curation.lint / app.expansion.connect
# (`_WIKILINK_RE`) -- kept as its own module-local copy rather than importing a
# private symbol across modules; both patterns must stay in lockstep with
# vault wikilink syntax.
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

# `contradiction.*` never claims an evidence role above this -- see module
# docstring. A literal constant (not configurable) so no config path can
# accidentally upgrade retrieval-derived material to `evidence`.
CONTRADICTION_EVIDENCE_ROLE = "background"

# Minimum resolvable in-vault sources a contradiction finding must carry to
# materialize at all -- `curation_citations_resolve` (GRADUATED_CURATION.md
# §7). Not configurable: this is the invariant floor, not a policy knob.
MIN_RESOLVABLE_CITATIONS = 2

# Declared offline curation task kind for RUNTIME_MODEL_POSTURE's (not yet
# built) paid-tier routing -- Track P, not filed. This module only declares
# the label; see module docstring.
CURATION_CONTRADICTION_TASK_KIND = "curation.contradiction"

_DEFAULT_MAX_FINDINGS_PER_NOTE = 3
_DEFAULT_MAX_FINDINGS_TOTAL = 25
_DEFAULT_RETRIEVAL_K = 8
_DEFAULT_CONTRADICTION_FLOOR = 0.4


@dataclass(frozen=True)
class ContradictionPassConfig:
    """Bounds + policy knobs for one Contradiction pass (mirrors
    ``app.expansion.connect.ConnectPassConfig``)."""

    max_findings_per_note: int = _DEFAULT_MAX_FINDINGS_PER_NOTE
    max_findings_total: int = _DEFAULT_MAX_FINDINGS_TOTAL
    retrieval_k: int = _DEFAULT_RETRIEVAL_K
    cross_scope_grants: tuple[CrossScopeFlow, ...] = ()
    declined_ledger: DeclinedLedgerPort = field(default_factory=default_declined_ledger)


@dataclass(frozen=True)
class ContradictionPassReport:
    """Pass receipt: notes scanned, findings emitted / suppressed-by-decline /
    suppressed-by-cap / suppressed-by-cross-scope-denial /
    voided-by-unresolvable-citation (spec §4, mirrors ConnectPassReport)."""

    findings: tuple[CurationFinding, ...]
    notes_scanned: int
    suppressed_by_decline: int
    suppressed_by_cap: int
    suppressed_by_cross_scope_denial: int
    voided_by_unresolvable_citation: int
    denials: tuple[str, ...] = ()  # content-free denial reasons only (KERNEL-10)


@dataclass(frozen=True)
class ClaimCandidate:
    """One side's claim, as supplied by the caller (harness input shape).

    The harness itself does not do NLI/claim-extraction cognition -- per the
    issue ("the pass itself is a model run, not code, per the README TCD
    note"), a model run (or, in tests, a fixture) supplies the two candidate
    claims; this dataclass is the typed shape the harness consumes.
    """

    note_uuid: str
    rel_path: str | None
    scope: str | None
    claim_text: str  # the verbatim claim text from this note
    interpretation: str  # one-line agent interpretation of the conflict


def _candidate_from_hit(hit, *, claim_text: str, interpretation: str) -> ClaimCandidate:
    payload = hit.payload or {}
    rel_path = hit.source_ref or payload.get("path")
    rel_path = str(rel_path) if rel_path else None
    raw_uuid = payload.get("uuid")
    if isinstance(raw_uuid, str) and raw_uuid.strip():
        note_uuid = raw_uuid.strip()
    elif rel_path:
        note_uuid = f"path:{rel_path}"
    else:
        note_uuid = f"path:{hit.doc_id}"
    scope = payload.get("domain")
    scope = str(scope) if isinstance(scope, str) and scope.strip() else None
    return ClaimCandidate(
        note_uuid=note_uuid,
        rel_path=rel_path,
        scope=scope,
        claim_text=claim_text.strip(),
        interpretation=interpretation.strip(),
    )


def compute_contradiction_finding_id(
    *,
    note_uuids: frozenset[str],
    basis: str,
) -> str:
    """Content-derived, order-independent finding id for a contradiction.

    ``hash(class, unordered note-uuid set, claim-pair basis)`` -- mirrors
    ``app.expansion.connect.compute_connect_finding_id`` exactly, so a
    symmetric claim pair collapses to one id regardless of which note is
    visited first, and a rerun over an unchanged vault is a provable no-op.
    """
    sorted_uuids = "\x1e".join(sorted(note_uuids))
    digest_input = "\x1f".join(
        [FindingClass.CONTRADICTION_CLAIM_CONFLICT.value, sorted_uuids, basis]
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _candidate_citations(candidate: ClaimCandidate) -> tuple[str, ...]:
    """Every citation this candidate side could contribute: its own
    identity (wikilink target / uuid) plus any wikilink targets its claim
    text itself references -- kept broad so a claim quoting "see [[Other]]"
    also offers that as a resolvable source."""
    citations: list[str] = []
    if candidate.rel_path:
        citations.append(candidate.rel_path)
    else:
        citations.append(candidate.note_uuid)
    citations.extend(match.group(1).strip() for match in _WIKILINK_RE.finditer(candidate.claim_text))
    return tuple(dict.fromkeys(citations))  # de-dup, preserve order


def _resolvable_citations(
    citations: tuple[str, ...],
    *,
    vault_root: Path,
    identity_index: dict[str, str],
) -> tuple[str, ...]:
    """Re-derive, from the CURRENT vault state, which of *citations* actually
    resolve to a note that exists right now.

    A citation resolves if it is a ``uuid:``-prefixed or bare identity found
    in ``identity_index`` (built from live frontmatter uuids + stems), or a
    vault-relative path that exists on disk. This is deliberately
    re-evaluated at materialization time (not cached from detection time) so
    a source deleted between detection and write voids the finding rather
    than materializing a dangling cite (``curation_citations_resolve``).
    """
    resolved: list[str] = []
    for citation in citations:
        raw = citation[len("uuid:") :] if citation.startswith("uuid:") else citation
        if raw in identity_index:
            resolved.append(citation)
            continue
        candidate_path = vault_root / raw
        if candidate_path.exists() and candidate_path.is_file():
            resolved.append(citation)
    return tuple(dict.fromkeys(resolved))


def _build_identity_index(vault_root: Path) -> dict[str, str]:
    """Map every live note's stem and frontmatter uuid to its vault-relative
    path, for citation resolution. Read-only; never mutates the vault."""
    from scripts.yaml_roundtrip import load_frontmatter

    index: dict[str, str] = {}
    for path in sorted(vault_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, _body = load_frontmatter(text)
        rel_path = path.relative_to(vault_root).as_posix()
        index[path.stem] = rel_path
        index[rel_path] = rel_path
        uuid = frontmatter.get("uuid")
        if uuid:
            index[str(uuid).strip()] = rel_path
    return index


def _grants_permit_surface(
    grants: tuple[CrossScopeFlow, ...], scope_a: str, scope_b: str
) -> bool:
    return any(grant.permits_surface(scope_a, scope_b) for grant in grants)


def _proposed_label(a: ClaimCandidate, b: ClaimCandidate) -> str:
    """Self-contained Swedish-language checkbox label per spec §4's example
    format ("Motstridigt: X säger A (länk), Y säger B (länk) -- markera och
    bekräfta för att få ett förslags-PR i noten"). Understandable when read
    aloud without relying on DOM position or surrounding prose (TTS-safe,
    ``docs/PANEL_AGENT.md :: Normalized Decision-Surface Proposal Format``)."""
    a_ref = a.rel_path or a.note_uuid
    b_ref = b.rel_path or b.note_uuid
    return (
        f"Motstridigt: {a_ref} säger \"{a.claim_text}\" ({a_ref}), "
        f"{b_ref} säger \"{b.claim_text}\" ({b_ref}) -- markera och bekräfta "
        f"för att få ett förslags-granskning i noten"
    )


def _make_contradiction_findings(
    *,
    candidates: tuple[ClaimCandidate, ClaimCandidate],
    citations: tuple[str, ...],
    basis: str,
) -> tuple[CurationFinding, ...]:
    """Build one :class:`CurationFinding` per side, sharing the identical
    order-independent ``finding_id`` -- mirrors
    ``app.expansion.connect._make_connect_findings`` exactly."""
    a, b = candidates
    note_uuids = frozenset({a.note_uuid, b.note_uuid})
    finding_id = compute_contradiction_finding_id(note_uuids=note_uuids, basis=basis)
    track = track_for_class(FindingClass.CONTRADICTION_CLAIM_CONFLICT)

    observed = f'"{a.claim_text}" vs "{b.claim_text}"'
    proposed = _proposed_label(a, b)
    interpretation = a.interpretation or b.interpretation

    findings: list[CurationFinding] = []
    for this_side, other_side in ((a, b), (b, a)):
        evidence_entries = [this_side.rel_path or this_side.note_uuid]
        evidence_entries.append(f"{other_side.rel_path or other_side.note_uuid}: {other_side.claim_text}")
        evidence_entries.extend(c for c in citations if c not in evidence_entries)
        evidence_entries.append(f"interpretation: {interpretation}")
        findings.append(
            CurationFinding(
                finding_id=finding_id,
                note_uuid=this_side.note_uuid,
                finding_class=FindingClass.CONTRADICTION_CLAIM_CONFLICT,
                track=track,
                span=basis,
                observed=observed,
                proposed=proposed,
                evidence=tuple(evidence_entries),
                language_verdict=LanguageVerdict.UNKNOWN,
                reversal=None,
            )
        )
    return tuple(findings)


def run_contradiction_pass(
    *,
    vault_root: Path,
    claim_pairs: list[tuple[ClaimCandidate, ClaimCandidate]] | None = None,
    queries: list[str] | None = None,
    claim_extractor: Callable[[RetrievalResponse], list[tuple[ClaimCandidate, ClaimCandidate]]]
    | None = None,
    config: ContradictionPassConfig | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path,
    materialize: bool = True,
    retrieve_fn: Callable[[RetrievalRequest], RetrievalResponse] = retrieve,
) -> ContradictionPassReport:
    """Run one Contradiction pass: retrieval-grounded claim-conflict harness,
    materialized as propose-track panel checkboxes.

    Candidate claim pairs may be supplied directly via *claim_pairs* (the
    harness call shape a claim-extraction model run would use in production,
    and the shape tests use for deterministic fixtures), or derived from
    *queries* + *claim_extractor* against the retrieval seam -- mirroring
    ``app.expansion.connect.run_connect_pass``'s ``queries`` seam, but keeping
    claim-conflict detection itself (an LLM cognition task, per the issue) out
    of this harness: :func:`retrieve` supplies candidates, an injected
    extractor decides which pairs conflict, this harness only enforces the
    structural invariants (citations, scope, caps, idempotency, decline).

    Every emitted finding is re-checked against the CURRENT vault for
    resolvable citations (``curation_citations_resolve``); a finding with
    fewer than :data:`MIN_RESOLVABLE_CITATIONS` resolvable sources is voided,
    never materialized.
    """
    config = config or ContradictionPassConfig()
    vault_root = Path(vault_root).expanduser().resolve()
    identity_index = _build_identity_index(vault_root)
    notes_scanned = len({v for v in identity_index.values()})

    pairs: list[tuple[ClaimCandidate, ClaimCandidate]] = list(claim_pairs or [])
    if queries and claim_extractor is not None:
        for query in queries:
            response = retrieve_fn(RetrievalRequest(query=query, k=config.retrieval_k))
            pairs.extend(claim_extractor(response))

    seen_finding_ids: set[str] = set()
    candidate_groups: list[tuple[CurationFinding, ...]] = []
    suppressed_by_decline = 0
    suppressed_by_cross_scope_denial = 0
    voided_by_unresolvable_citation = 0
    denial_reasons: list[str] = []

    for a, b in pairs:
        if a.note_uuid == b.note_uuid:
            continue

        scope_a = a.scope or "unscoped"
        scope_b = b.scope or "unscoped"
        if scope_a != scope_b:
            if not _grants_permit_surface(config.cross_scope_grants, scope_a, scope_b):
                # Content-free denial (KERNEL-10): record only that a
                # cross-scope candidate was excluded, never which
                # notes/scopes/claims. Mirrors app.expansion.connect exactly.
                suppressed_by_cross_scope_denial += 1
                reason = "cross_scope_no_flow"
                if reason not in denial_reasons:
                    denial_reasons.append(reason)
                continue

        basis = f"{a.claim_text[:80]}|{b.claim_text[:80]}"
        citations = _candidate_citations(a) + _candidate_citations(b)
        resolvable = _resolvable_citations(
            citations, vault_root=vault_root, identity_index=identity_index
        )

        group = _make_contradiction_findings(candidates=(a, b), citations=resolvable, basis=basis)
        finding_id = group[0].finding_id

        if finding_id in seen_finding_ids:
            continue  # idempotent within this pass too (symmetric pair, either order)

        if len(resolvable) < MIN_RESOLVABLE_CITATIONS:
            # curation_citations_resolve: void the finding rather than
            # materialize it with a dangling/unresolvable cite. Never emitted.
            voided_by_unresolvable_citation += 1
            continue

        if config.declined_ledger.is_declined(finding_id):
            suppressed_by_decline += 1
            continue

        seen_finding_ids.add(finding_id)
        candidate_groups.append(group)

    # Deterministic ordering before cap enforcement (lowest finding_id first),
    # mirroring app.expansion.connect's reproducible-truncation posture.
    candidate_groups.sort(key=lambda group: group[0].finding_id)

    accepted_groups: list[tuple[CurationFinding, ...]] = []
    findings_by_note: dict[str, int] = {}
    suppressed_by_cap = 0
    for group in candidate_groups:
        if len(accepted_groups) >= config.max_findings_total:
            suppressed_by_cap += len(candidate_groups) - len(accepted_groups)
            break
        if any(findings_by_note.get(f.note_uuid, 0) >= config.max_findings_per_note for f in group):
            suppressed_by_cap += 1
            continue
        for f in group:
            findings_by_note[f.note_uuid] = findings_by_note.get(f.note_uuid, 0) + 1
        accepted_groups.append(group)

    accepted: list[CurationFinding] = [f for group in accepted_groups for f in group]

    if materialize and accepted:
        write_curation_proposals(
            accepted,
            vault_root=vault_root,
            write_guard=write_guard,
            outbox_path=outbox_path,
        )

    return ContradictionPassReport(
        findings=tuple(accepted),
        notes_scanned=notes_scanned,
        suppressed_by_decline=suppressed_by_decline,
        suppressed_by_cap=suppressed_by_cap,
        suppressed_by_cross_scope_denial=suppressed_by_cross_scope_denial,
        voided_by_unresolvable_citation=voided_by_unresolvable_citation,
        denials=tuple(denial_reasons),
    )


__all__ = [
    "CONTRADICTION_EVIDENCE_ROLE",
    "CURATION_CONTRADICTION_TASK_KIND",
    "MIN_RESOLVABLE_CITATIONS",
    "ClaimCandidate",
    "ContradictionPassConfig",
    "ContradictionPassReport",
    "compute_contradiction_finding_id",
    "run_contradiction_pass",
]
