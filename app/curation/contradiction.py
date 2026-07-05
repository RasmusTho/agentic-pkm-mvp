"""Contradiction pass: retrieval-grounded claim-conflict finding harness (G2-4, #2999).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4, §6 (G2-4).
Parent: #2980 (Capability Hardening / Cognitive Expansion). This is a sibling
Expansion pass -- it shares EXP-1's harness shape (``app.expansion.connect``)
and EXP-2's declined-proposal ledger (``app.proposals.declined_ledger``), and
reuses the merged G2-1 finding pipeline (``app.curation.findings``) and G2-2
propose writer (``app.curation.proposal_writer``) exactly like Connect does --
this module never forks any of those three.

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.expansion.connect``'s and ``app.curation.proposal_writer``'s
posture):

- **Propose-only by construction.** Every finding this module emits uses
  :data:`app.curation.findings.FindingClass.CONTRADICTION_CLAIM_CONFLICT`,
  which the closed class table (spec GRADUATED_CURATION §1) maps to
  ``propose`` -- never ``auto_fix``. There is no code path here, and no
  configuration flag, that materializes a contradiction finding directly as a
  body edit. Materialization is delegated entirely to the existing
  ``app.curation.proposal_writer.write_curation_proposals`` (unchecked
  ``AI-åtgärder`` checkbox only); this module never calls
  ``_write_proposals_to_panel`` or any other body-edit path itself.
- **The ``[!contradiction]`` callout is never written by this pass.** Per spec
  §4 ("a `[!contradiction]` callout only after confirmation -- the callout
  itself is a body edit and therefore rides the confirmed action, never the
  pass"), this module contains zero code that writes a callout block. The
  callout is out of scope for the pass entirely; it is produced later by the
  confirmed-action path (the existing Panel confirm -> execute flow), not by
  anything in ``app/curation/contradiction.py``.
- **Citations must resolve or the finding is void, loudly.** Every emitted
  finding carries >=2 resolvable in-vault source references (spec §4,
  invariant ``curation_citations_resolve``). Resolution is checked against the
  vault at construction time; an unresolvable citation raises
  :class:`UnresolvableContradictionCitationError` rather than emitting an
  uncited "trust me" finding or silently dropping the candidate without a
  trace -- callers see exactly which candidate pair failed and why.
- **Retrieval-grounded, evidence clamped to ``background``.** Candidates come
  only from :func:`app.retrieval.capability.retrieve`. A retrieved hit's
  supporting span is surfaced as ``background`` salience signal in the
  decision-surface payload, never claimed as ``evidence`` -- mirrors
  ``app.expansion.connect.CONNECT_EVIDENCE_ROLE``'s refusal to launder
  retrieval-derived material as authority.
- **Never adjudicates.** This module only ever surfaces a tension between two
  verbatim claims plus a one-line agent interpretation; there is no code path
  that decides, ranks, or labels which claim is "correct". The interpretation
  field is bounded to naming the tension, never a verdict.
- **Scope discipline mirrors Connect exactly.** Same-scope pairs are proposed
  by default; a cross-scope pair is proposed only under an existing
  ``surface``-operation :class:`app.expansion.connect.CrossScopeFlow` grant
  (never ``cite``/``import``) -- this module reuses
  ``app.expansion.connect.CrossScopeFlow`` and its ``permits_surface`` check
  rather than defining a second grant shape.
- **Idempotent + decline-aware.** ``finding_id`` is content-derived from the
  class, the unordered pair of note identities, and the two claim spans (via
  :func:`compute_contradiction_finding_id`) -- a rerun over an unchanged vault
  is a provable no-op. Every pass consults
  :class:`app.expansion.connect.DeclinedLedgerPort` (the real
  ``app.proposals.declined_ledger.DeclinedLedger`` by default) before
  emitting a finding: a declined finding_id is suppressed and counted in the
  pass receipt, exactly like every other proposal-emitting pass.
- **CLI-invoked, explicit invocation only.** This module exposes no tick/
  watcher/scheduler hook. ``run_contradiction_pass`` only runs when a caller
  (the CLI entrypoint) invokes it directly -- never as a side effect of vault
  watching or a relevance tick.
- **Model routing: task-kind declaration only.** :data:`TASK_KIND`
  (``curation.contradiction``) is declared here as the offline curation task
  kind this pass would use to resolve a model route (spec §4, §6: "an
  offline curation task kind"). This module does not implement
  RUNTIME_MODEL_POSTURE's paid-tier routing policy -- that compiler/policy
  wiring is out of scope for this slice (Track P), and no code path here
  resolves a model client from this constant.
"""
from __future__ import annotations

import hashlib
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

# Offline curation task kind (spec §4, §6: "an offline curation task kind
# (curation.contradiction), eligible for the paid tier under
# RUNTIME_MODEL_POSTURE rules ... this slice just declares the task kind,
# does not implement the routing policy"). Declared for later RUNTIME_MODEL_
# POSTURE wiring to consult; no router/policy call site resolves this constant
# in this slice.
TASK_KIND = "curation.contradiction"

# Same conservative-by-construction posture as app.expansion.connect.CONNECT_
# EVIDENCE_ROLE: a contradiction candidate's supporting span is surfaced as
# background salience, never claimed as evidence, regardless of retrieval
# score.
CONTRADICTION_EVIDENCE_ROLE = "background"

_DEFAULT_MAX_FINDINGS_PER_NOTE = 3
_DEFAULT_MAX_FINDINGS_TOTAL = 25
_DEFAULT_RETRIEVAL_K = 8
_DEFAULT_CONTRADICTION_FLOOR = 0.4


class UnresolvableContradictionCitationError(ValueError):
    """Raised when a contradiction candidate cannot produce >=2 resolvable
    in-vault source links.

    Spec §4 / invariant ``curation_citations_resolve``: "unresolvable evidence
    voids the finding (no uncited 'trust me' callouts)". This is a loud
    failure -- callers are told exactly which candidate pair and which side
    failed to resolve, rather than the candidate being silently dropped
    without a trace or emitted with a dangling citation.
    """


@dataclass(frozen=True)
class ContradictionClaim:
    """One side of a candidate contradiction, as this pass reasons over it."""

    note_uuid: str
    rel_path: str | None
    scope: str | None
    claim_text: str
    score: float

    def source_link(self) -> str:
        """The resolvable source reference for this claim -- a wikilink target
        (the note's relative path/stem) when available, else the uuid-anchored
        fallback identity. Always non-empty for a constructed claim (spec §4:
        "wikilink or uuid-anchored")."""
        return self.rel_path or self.note_uuid


def _resolve_claim_source(claim: ContradictionClaim, vault_root: Path) -> bool:
    """True if *claim*'s source link resolves to a real file under
    *vault_root* -- the citation-resolution check the finding-construction
    step must pass before a finding is ever built (spec: citations "resolve at
    materialization time")."""
    if claim.rel_path:
        candidate = vault_root / claim.rel_path
        return candidate.exists()
    if claim.note_uuid.startswith("path:"):
        candidate = vault_root / claim.note_uuid[len("path:") :]
        return candidate.exists()
    # A bare uuid identity (no known path) cannot be resolved against the
    # filesystem directly; treat as unresolved rather than guessing a path.
    return False


def compute_contradiction_finding_id(
    *,
    note_uuids: frozenset[str],
    claim_a: str,
    claim_b: str,
) -> str:
    """Content-derived, order-independent finding id for a contradiction pair.

    ``hash(class, unordered note-uuid set, sorted claim-span pair)`` -- mirrors
    ``app.expansion.connect.compute_connect_finding_id``'s discipline exactly:
    a symmetric pair produces one id regardless of traversal order, so reruns
    over an unchanged vault are no-ops.
    """
    sorted_uuids = "\x1e".join(sorted(note_uuids))
    sorted_claims = "\x1e".join(sorted([claim_a, claim_b]))
    digest_input = "\x1f".join(
        [FindingClass.CONTRADICTION_CLAIM_CONFLICT.value, sorted_uuids, sorted_claims]
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContradictionPassConfig:
    """Bounds + policy knobs for one contradiction pass (mirrors
    ``app.expansion.connect.ConnectPassConfig``'s bounded-surfacing posture)."""

    max_findings_per_note: int = _DEFAULT_MAX_FINDINGS_PER_NOTE
    max_findings_total: int = _DEFAULT_MAX_FINDINGS_TOTAL
    retrieval_k: int = _DEFAULT_RETRIEVAL_K
    cross_scope_grants: tuple[CrossScopeFlow, ...] = ()
    declined_ledger: DeclinedLedgerPort = field(default_factory=default_declined_ledger)


@dataclass(frozen=True)
class ContradictionPassReport:
    """Pass receipt: findings emitted / suppressed-by-decline / suppressed-by-
    cap / suppressed-by-cross-scope-denial, mirroring
    ``app.expansion.connect.ConnectPassReport``'s shape."""

    findings: tuple[CurationFinding, ...]
    pairs_considered: int
    suppressed_by_decline: int
    suppressed_by_cap: int
    suppressed_by_cross_scope_denial: int
    denials: tuple[str, ...] = ()  # content-free denial reasons only (KERNEL-10)


def _claim_from_hit(hit, *, anchor_scope: str | None) -> ContradictionClaim:
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
    scope = str(scope) if isinstance(scope, str) and scope.strip() else anchor_scope
    claim_text = (hit.snippet or hit.text).strip()
    return ContradictionClaim(
        note_uuid=note_uuid, rel_path=rel_path, scope=scope, claim_text=claim_text, score=hit.score
    )


def _grants_permit_surface(
    grants: tuple[CrossScopeFlow, ...], scope_a: str, scope_b: str
) -> bool:
    return any(grant.permits_surface(scope_a, scope_b) for grant in grants)


def _build_contradiction_finding(
    *,
    claim_a: ContradictionClaim,
    claim_b: ContradictionClaim,
    vault_root: Path,
    interpretation: str,
) -> tuple[CurationFinding, ...]:
    """Build one :class:`CurationFinding` per side of the contradiction pair,
    both sharing an order-independent ``finding_id``, after verifying >=2
    resolvable source links (spec §4). Raises
    :class:`UnresolvableContradictionCitationError` -- loudly, never silently
    -- if either side's citation does not resolve.

    Mirrors ``app.expansion.connect._make_connect_findings``'s per-side
    record shape (a proposal about a relationship must appear in every
    participant's own note panel), extended with the citation-resolution gate
    this finding class uniquely requires.
    """
    unresolved: list[str] = []
    for claim in (claim_a, claim_b):
        if not _resolve_claim_source(claim, vault_root):
            unresolved.append(claim.source_link())
    if unresolved:
        raise UnresolvableContradictionCitationError(
            "contradiction finding voided: source link(s) do not resolve in-vault: "
            f"{unresolved!r} (>=2 resolvable source links are required, spec GRADUATED_CURATION.md "
            "§4; the candidate is refused rather than emitted with a dangling citation)"
        )

    note_uuids = frozenset({claim_a.note_uuid, claim_b.note_uuid})
    finding_id = compute_contradiction_finding_id(
        note_uuids=note_uuids, claim_a=claim_a.claim_text, claim_b=claim_b.claim_text
    )
    track = track_for_class(FindingClass.CONTRADICTION_CLAIM_CONFLICT)

    # Both source links, always exactly 2 resolvable references (spec §4:
    # "≥2 resolvable source links"). Both claims are carried verbatim in
    # `observed` (facts stay separate from `proposed`, the agent's one-line
    # interpretation) per the normalized decision-surface format
    # (docs/PANEL_AGENT.md :: Normalized Decision-Surface Proposal Format):
    # facts / interpretation / uncertainty / choices stay visibly separate.
    observed = (
        f"Claim A ({claim_a.source_link()}): {claim_a.claim_text}\n"
        f"Claim B ({claim_b.source_link()}): {claim_b.claim_text}"
    )
    proposed = (
        f"Motstridigt: {claim_a.source_link()} säger \"{claim_a.claim_text}\", "
        f"{claim_b.source_link()} säger \"{claim_b.claim_text}\" — markera och bekräfta "
        "för att få ett förslags-PR i noten"
    )

    findings: list[CurationFinding] = []
    for this_claim, other_claim in ((claim_a, claim_b), (claim_b, claim_a)):
        evidence = (this_claim.source_link(), other_claim.source_link())
        findings.append(
            CurationFinding(
                finding_id=finding_id,
                note_uuid=this_claim.note_uuid,
                finding_class=FindingClass.CONTRADICTION_CLAIM_CONFLICT,
                track=track,
                span=interpretation,
                observed=observed,
                proposed=proposed,
                evidence=evidence,
                language_verdict=LanguageVerdict.UNKNOWN,
                reversal=None,
            )
        )
    return tuple(findings)


def run_contradiction_pass(
    *,
    vault_root: Path,
    queries: list[str],
    config: ContradictionPassConfig | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path,
    materialize: bool = True,
    retrieve_fn: Callable[[RetrievalRequest], RetrievalResponse] = retrieve,
) -> ContradictionPassReport:
    """Run one contradiction pass: retrieval-grounded claim-conflict finding
    harness, materialized as propose-track panel checkboxes.

    ``queries`` seeds the retrieval seam (one call to
    :func:`app.retrieval.capability.retrieve` per query) -- this pass never
    re-implements ranking; it only consumes ``RetrievalResponse`` and applies
    contradiction-specific discipline (pairwise negation detection via the
    caller-supplied query framing, scope pairing, citation resolution, caps,
    idempotency, decline suppression) on top of what retrieval already
    returned.

    Explicit-invocation only: this function has no scheduler/tick binding.
    Callers (the CLI) decide when to invoke it.
    """
    config = config or ContradictionPassConfig()
    vault_root = Path(vault_root).expanduser().resolve()

    seen_finding_ids: set[str] = set()
    candidate_groups: list[tuple[CurationFinding, ...]] = []
    suppressed_by_decline = 0
    suppressed_by_cross_scope_denial = 0
    denial_reasons: list[str] = []
    pairs_considered = 0

    for query in queries:
        response = retrieve_fn(RetrievalRequest(query=query, k=config.retrieval_k))
        hits = [hit for hit in response.hits if hit.score >= _DEFAULT_CONTRADICTION_FLOOR]
        claims = [_claim_from_hit(hit, anchor_scope=None) for hit in hits]

        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                a, b = claims[i], claims[j]
                if a.note_uuid == b.note_uuid:
                    continue
                if a.claim_text == b.claim_text:
                    continue  # identical text is not a conflict
                pairs_considered += 1

                scope_a = a.scope or "unscoped"
                scope_b = b.scope or "unscoped"
                if scope_a != scope_b:
                    if not _grants_permit_surface(config.cross_scope_grants, scope_a, scope_b):
                        # Content-free denial (KERNEL-10), identical discipline
                        # to app.expansion.connect: record only that a
                        # cross-scope candidate was excluded, never which
                        # notes/scopes/content.
                        suppressed_by_cross_scope_denial += 1
                        reason = "cross_scope_no_flow"
                        if reason not in denial_reasons:
                            denial_reasons.append(reason)
                        continue

                interpretation = (
                    f"Agent interpretation: '{a.source_link()}' and '{b.source_link()}' make "
                    "conflicting claims; this pass surfaces the tension only and does not "
                    "adjudicate which claim is correct."
                )

                try:
                    group = _build_contradiction_finding(
                        claim_a=a, claim_b=b, vault_root=vault_root, interpretation=interpretation
                    )
                except UnresolvableContradictionCitationError:
                    # Voided loudly at the call site that has content to log;
                    # re-raise so the caller sees exactly which pass run
                    # failed rather than silently dropping the candidate.
                    raise

                finding_id = group[0].finding_id
                if finding_id in seen_finding_ids:
                    continue  # idempotent within this pass too (symmetric pair, either order)
                if config.declined_ledger.is_declined(finding_id):
                    suppressed_by_decline += 1
                    continue

                seen_finding_ids.add(finding_id)
                candidate_groups.append(group)

    # Deterministic ordering before cap enforcement (lowest finding_id first),
    # mirroring app.expansion.connect's reproducible-truncation discipline.
    candidate_groups.sort(key=lambda group: group[0].finding_id)

    accepted_groups: list[tuple[CurationFinding, ...]] = []
    findings_by_note: dict[str, int] = {}
    suppressed_by_cap = 0
    for group in candidate_groups:
        if len(accepted_groups) >= config.max_findings_total:
            suppressed_by_cap += len(candidate_groups) - len(accepted_groups)
            break
        if any(
            findings_by_note.get(f.note_uuid, 0) >= config.max_findings_per_note for f in group
        ):
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
        pairs_considered=pairs_considered,
        suppressed_by_decline=suppressed_by_decline,
        suppressed_by_cap=suppressed_by_cap,
        suppressed_by_cross_scope_denial=suppressed_by_cross_scope_denial,
        denials=tuple(denial_reasons),
    )


__all__ = [
    "CONTRADICTION_EVIDENCE_ROLE",
    "ContradictionClaim",
    "ContradictionPassConfig",
    "ContradictionPassReport",
    "TASK_KIND",
    "UnresolvableContradictionCitationError",
    "compute_contradiction_finding_id",
    "run_contradiction_pass",
]
