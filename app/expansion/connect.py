"""Connect pass: related-unlinked + thematic-link finding harness (EXP-1, #2994).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §1
(EXP-1). Parent: #2980 (Capability Hardening / Cognitive Expansion). Builds on
the merged G2-1 finding pipeline (``app.curation.findings``) and G2-2 propose
writer (``app.curation.proposal_writer``) -- this module never forks either;
it only emits ``CurationFinding`` records and hands them to the existing
writer.

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.curation.lint``'s and ``app.curation.proposal_writer``'s
posture):

- **Candidate-only by construction.** Every finding this module emits uses a
  class from :data:`app.curation.findings.CONNECT_FINDING_CLASSES`, which is
  asserted disjoint from ``MECHANICAL_ALLOWLIST`` at import time
  (``app/curation/findings.py``). There is no code path here, and no
  configuration flag, that can materialize a connect finding on the
  ``auto_fix`` track -- ``track_for_class`` derives the track from class
  membership alone, and this module never bypasses it.
- **Retrieval-grounded, evidence clamped to ``background``.** Candidates come
  only from :func:`app.retrieval.capability.retrieve`. This module never
  claims an ``evidence`` role for connect-derived material; every finding's
  supporting spans are surfaced as ``background`` salience signal, per
  ``app.knowledge_compilation.proposal_builders._MACHINE_DERIVATIONS`` (which
  already marks ``retrieval``-derived material machine-derived and refuses to
  launder it as authority -- this module reuses that refusal by construction
  rather than restating it: it never emits an ``evidence_role`` claim above
  ``background`` regardless of retrieval score).
- **Scope is hard.** A candidate pair is proposed only when both notes carry
  the same scope tag (``payload["domain"]`` -- the same field the retrieval
  scope prefilter already keys on, ``app/retrieval/hybrid.py::_extract_domain``).
  A cross-scope pair is proposed only under an existing, explicitly-supplied
  :class:`CrossScopeFlow` grant naming the ``surface`` operation; with no
  grant the pair is silently excluded -- never surfaced, never logged with any
  content identifying the pair (content-free denial, KERNEL-10). This module
  never bypasses ``retrieve()``'s own scope prefilter -- it reads the
  *pairwise* scope tag from each hit's payload on top of whatever ``retrieve``
  already admitted.
- **Idempotent + decline-aware.** ``finding_id`` is content-derived from the
  class, the *unordered* set of note identities, and a theme/span basis (spec
  §1.2) via :func:`compute_connect_finding_id` -- a symmetric pair produces one
  finding_id regardless of iteration order, so reruns over an unchanged vault
  are no-ops. Every pass consults :class:`DeclinedLedgerPort` before emitting
  a finding, backed by the real declined-proposal ledger
  (``app.proposals.declined_ledger.DeclinedLedger``, EXP-2 #2995): a declined
  finding_id is suppressed and counted in the pass receipt
  (``suppressed_by_decline``) until its content basis changes (a changed
  span/basis mints a different finding_id automatically -- the ledger needs
  no reset logic of its own). The ledger is derived/rebuildable suppression
  state only; it is never indexed, retrieved, or admitted as context.
- **Bounded surfacing.** :class:`ConnectPassConfig` caps findings per note and
  in total; a pass that would exceed a cap truncates deterministically
  (lowest finding_id first) rather than flooding panels.
- **Already-linked pairs are never proposed.** A pair with an existing direct
  wikilink, or a 1-hop path through a shared linked note, is excluded before
  scope/cap logic runs.

Cluster emergence (EXP-5, #2998, spec §1.1/§1.3 `connect.cluster_emergence`)
extends this module with one additional finding class and its Create
handoff:

- **Cluster emergence is candidate-only, exactly like every other
  ``connect.*`` class.** :func:`find_cluster_emergence` groups the SAME
  same-scope, unlinked, related-pair candidates this pass already computes
  into connected components (union-find over the accepted pair graph); a
  component reaching ``min_cluster_size`` (default 3, spec §1.1: "cluster
  member refs (>=3)") proposes a hub/overview note, never writes one. The
  class is a member of :data:`app.curation.findings.CONNECT_FINDING_CLASSES`
  and therefore inherits the same import-time disjointness-from-auto_fix
  assertion -- this module adds no separate track override.
- **The handoff is accept-then-create, never emergence-then-create.**
  :func:`cluster_emergence_to_create_request` only ever converts an
  ALREADY-ACCEPTED cluster finding (the caller supplies the finding plus
  resolvable source text for each member) into a
  :class:`app.expansion.create.CreateRequest` of kind
  :data:`app.expansion.create.OutputKind.OVERVIEW` -- it never calls
  ``run_create_pass`` itself and never runs on an unaccepted (still-proposed)
  finding. Wiring the handoff trigger to the real acceptance path
  (``app.expansion.accept``) is the caller's responsibility; this function is
  the pure, testable conversion step.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from app.curation.findings import CurationFinding, FindingClass, LanguageVerdict, track_for_class
from app.curation.proposal_writer import write_curation_proposals
from app.retrieval.capability import RetrievalRequest, RetrievalResponse, retrieve
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

if TYPE_CHECKING:
    from app.expansion.create import CreateRequest, SourceInput

# Reuses the same wikilink shape as app.curation.lint (`_WIKILINK_RE`) rather
# than importing a private symbol across modules -- both patterns must stay
# in lockstep with vault wikilink syntax; kept identical intentionally.
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

# ``connect.*` never claims an evidence role above this -- see module
# docstring. Never read as a configurable value: it is a literal constant so
# no config path can accidentally upgrade it.
CONNECT_EVIDENCE_ROLE = "background"

_DEFAULT_MAX_FINDINGS_PER_NOTE = 3
_DEFAULT_MAX_FINDINGS_TOTAL = 25
_DEFAULT_RETRIEVAL_K = 8
_DEFAULT_RELATEDNESS_FLOOR = 0.55


class DeclinedLedgerPort(Protocol):
    """Consultation point for "has the human already said no to this finding?"

    Backed by the real declined-proposal ledger
    (``app.proposals.declined_ledger.DeclinedLedger``, EXP-2 #2995) via
    :func:`default_declined_ledger`. Kept as a narrow structural Protocol
    (rather than importing the concrete class into every call site) so this
    pass, the G2 curation passes, and later E8's contradiction pass all
    consult the identical one-method contract without coupling to
    ``app.proposals``'s storage details.
    """

    def is_declined(self, finding_id: str) -> bool: ...


def default_declined_ledger() -> DeclinedLedgerPort:
    """Construct the default :class:`DeclinedLedgerPort` -- the real,
    file-backed ledger (``app.proposals.declined_ledger``), not a stub.
    Import is deferred into the function body so a module that only wants
    the Protocol shape (e.g. for typing or a test double) never pays for
    importing ``app.proposals``."""
    from app.proposals.declined_ledger import default_declined_ledger as _real_default

    return _real_default()


@dataclass(frozen=True)
class CrossScopeFlow:
    """A typed, directional, operation-specific grant (spec: cross-scope-flow.md).

    Minimal app-level shape carrying only what this pass consults:
    ``allowed_operations`` must include ``"surface"`` for a cross-scope
    candidate pair to be proposed at all (Connect never receives
    ``cite``/``import``/``export`` -- spec §1.2). No grant naming a
    ``source_scope``/``target_scope`` pair means that pair is denied by
    default; this module never invents a permissive default.
    """

    source_scope: str
    target_scope: str
    allowed_operations: frozenset[str] = field(default_factory=frozenset)

    def permits_surface(self, source_scope: str, target_scope: str) -> bool:
        return (
            "surface" in self.allowed_operations
            and {self.source_scope, self.target_scope} == {source_scope, target_scope}
        )


def _grants_permit_surface(
    grants: tuple[CrossScopeFlow, ...], scope_a: str, scope_b: str
) -> bool:
    return any(grant.permits_surface(scope_a, scope_b) for grant in grants)


@dataclass(frozen=True)
class ConnectPassConfig:
    """Bounds + policy knobs for one Connect pass (spec §1.2 "bounded surfacing")."""

    max_findings_per_note: int = _DEFAULT_MAX_FINDINGS_PER_NOTE
    max_findings_total: int = _DEFAULT_MAX_FINDINGS_TOTAL
    retrieval_k: int = _DEFAULT_RETRIEVAL_K
    relatedness_floor: float = _DEFAULT_RELATEDNESS_FLOOR
    cross_scope_grants: tuple[CrossScopeFlow, ...] = ()
    declined_ledger: DeclinedLedgerPort = field(default_factory=default_declined_ledger)


@dataclass(frozen=True)
class ConnectPassReport:
    """Pass receipt (spec §1.3 "Observability": notes scanned, findings emitted
    / suppressed-by-decline / suppressed-by-cap)."""

    findings: tuple[CurationFinding, ...]
    notes_scanned: int
    suppressed_by_decline: int
    suppressed_by_cap: int
    suppressed_by_cross_scope_denial: int
    denials: tuple[str, ...] = ()  # content-free denial reasons only (KERNEL-10)


@dataclass(frozen=True)
class _NoteCandidate:
    """A retrieval hit projected into the shape this pass reasons over."""

    note_uuid: str
    rel_path: str | None
    scope: str | None
    language: str | None
    span: str
    score: float


def _score_class(score: float) -> str:
    """Coarse, human-legible score band -- never the raw float (spec AC1:
    "the retrieval basis (score class, not raw floats)")."""
    if score >= 0.85:
        return "high"
    if score >= _DEFAULT_RELATEDNESS_FLOOR:
        return "medium"
    return "low"


def _candidate_from_hit(hit: Any, *, anchor_scope: str | None) -> _NoteCandidate:
    payload = hit.payload or {}
    rel_path = hit.source_ref or payload.get("path")
    rel_path = str(rel_path) if rel_path else None
    raw_uuid = payload.get("uuid")
    # Identity convention mirrors app.curation.lint._note_identity exactly:
    # a real frontmatter uuid when present, else the `path:<rel>` fallback --
    # this is what makes proposal_writer._note_path_from_finding resolve
    # either shape without this module inventing a third identity scheme.
    if isinstance(raw_uuid, str) and raw_uuid.strip():
        note_uuid = raw_uuid.strip()
    elif rel_path:
        note_uuid = f"path:{rel_path}"
    else:
        note_uuid = f"path:{hit.doc_id}"
    scope = payload.get("domain")
    scope = str(scope) if isinstance(scope, str) and scope.strip() else anchor_scope
    language = payload.get("language")
    snippet = hit.snippet or hit.text[:240]
    return _NoteCandidate(
        note_uuid=note_uuid,
        rel_path=rel_path,
        scope=scope,
        language=str(language) if language else None,
        span=snippet.strip(),
        score=hit.score,
    )


def compute_connect_finding_id(
    *,
    finding_class: FindingClass,
    note_uuids: frozenset[str],
    basis: str,
) -> str:
    """Content-derived, order-independent finding id for a connect finding.

    ``hash(class, unordered note-uuid set, theme|span basis)`` per spec §1.2.
    Sorting the uuid set before hashing is what makes a symmetric pair collapse
    to one id regardless of which note is visited first -- reruns and
    A/B-vs-B/A traversal order both produce the identical id.
    """
    sorted_uuids = "\x1e".join(sorted(note_uuids))
    digest_input = "\x1f".join([finding_class.value, sorted_uuids, basis])
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _make_connect_findings(
    *,
    finding_class: FindingClass,
    candidates: tuple[_NoteCandidate, ...],
    observed: str,
    proposed: str,
    basis: str,
) -> tuple[CurationFinding, ...]:
    """Build one :class:`CurationFinding` PER SIDE of the candidate set, all
    sharing the identical order-independent ``finding_id``.

    A connect proposal is about a *relationship*, so both/all sides must see
    it in their own note's panel (spec AC1: "both note refs"). Emitting one
    record per note (rather than a single anchor-note record) lets the
    existing per-note ``write_curation_proposals`` materialize the checkbox
    on every participant's note while the shared ``finding_id`` keeps the
    pass's own idempotency/dedup/decline-ledger keying to ONE logical finding,
    not N.
    """
    note_uuids = frozenset(c.note_uuid for c in candidates)
    finding_id = compute_connect_finding_id(
        finding_class=finding_class, note_uuids=note_uuids, basis=basis
    )
    # track is derived once, the same way CurationFinding.create derives it --
    # from the closed class->track wall alone (never overridable by this call
    # site, never by confidence/LLM output).
    track = track_for_class(finding_class)

    findings: list[CurationFinding] = []
    for c in candidates:
        # This side's own path first (what proposal_writer resolves against,
        # evidence[0]); then every OTHER side's verbatim supporting span, so
        # each note's proposal still carries "≥1 verbatim span per side"
        # (spec AC1) even though the checkbox materializes on one note.
        evidence_entries = [c.rel_path or c.note_uuid]
        for other in candidates:
            if other is c:
                continue
            evidence_entries.append(f"{other.rel_path or other.note_uuid}: {other.span}")
        findings.append(
            CurationFinding(
                finding_id=finding_id,
                note_uuid=c.note_uuid,
                finding_class=finding_class,
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


def _existing_link_paths(vault_root: Path) -> dict[str, set[str]]:
    """Map each note identity (title/stem, and uuid if present) to the set of
    note identities it links to directly, for the "already linked, direct or
    1-hop" exclusion (spec AC2). Read-only; never mutates the vault."""
    from scripts.yaml_roundtrip import load_frontmatter

    links: dict[str, set[str]] = {}
    stems_by_identity: dict[str, str] = {}
    for path in sorted(vault_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = load_frontmatter(text)
        uuid = frontmatter.get("uuid")
        identity = str(uuid).strip() if uuid else f"path:{path.relative_to(vault_root).as_posix()}"
        stem = path.stem
        stems_by_identity[stem] = identity
        targets = {m.group(1).strip() for m in _WIKILINK_RE.finditer(body)}
        links.setdefault(identity, set()).update(targets)

    # Resolve wikilink targets (titles/stems) to identities where possible.
    resolved: dict[str, set[str]] = {}
    for identity, targets in links.items():
        resolved_targets: set[str] = set()
        for target in targets:
            resolved_targets.add(stems_by_identity.get(target, target))
        resolved[identity] = resolved_targets
    return resolved


def _already_linked(identity_a: str, identity_b: str, link_map: dict[str, set[str]]) -> bool:
    """True if A links to B (or vice versa) directly, or shares a 1-hop path
    (A links to X and B links to X, or A links to X which links to B)."""
    a_links = link_map.get(identity_a, set())
    b_links = link_map.get(identity_b, set())
    if identity_b in a_links or identity_a in b_links:
        return True
    # 1-hop: shared linked neighbor, or A -> X -> B.
    if a_links & b_links:
        return True
    for x in a_links:
        if identity_b in link_map.get(x, set()):
            return True
    for x in b_links:
        if identity_a in link_map.get(x, set()):
            return True
    return False


def run_connect_pass(
    *,
    vault_root: Path,
    queries: list[str],
    config: ConnectPassConfig | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path,
    materialize: bool = True,
    retrieve_fn: Callable[[RetrievalRequest], RetrievalResponse] = retrieve,
) -> ConnectPassReport:
    """Run one Connect pass: retrieval-grounded related-unlinked + thematic
    finding harness, materialized as propose-track panel checkboxes.

    ``queries`` seeds the retrieval seam (one call to
    :func:`app.retrieval.capability.retrieve` per query, e.g. one per note
    title/topic under review) -- this pass never re-implements ranking; it
    only consumes ``RetrievalResponse`` and applies Connect-specific
    discipline (already-linked exclusion, scope pairing, caps, idempotency)
    on top of what retrieval already returned.
    """
    config = config or ConnectPassConfig()
    vault_root = Path(vault_root).expanduser().resolve()
    link_map = _existing_link_paths(vault_root)

    seen_finding_ids: set[str] = set()
    # One entry per LOGICAL finding (a pair), holding every per-side
    # CurationFinding record that finding materializes as.
    candidate_groups: list[tuple[CurationFinding, ...]] = []
    suppressed_by_decline = 0
    suppressed_by_cross_scope_denial = 0
    denial_reasons: list[str] = []
    notes_scanned = len({identity for identity in link_map})

    for query in queries:
        response = retrieve_fn(RetrievalRequest(query=query, k=config.retrieval_k))
        hits = [hit for hit in response.hits if hit.score >= config.relatedness_floor]
        candidates = [_candidate_from_hit(hit, anchor_scope=None) for hit in hits]

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                a, b = candidates[i], candidates[j]
                if a.note_uuid == b.note_uuid:
                    continue
                if _already_linked(a.note_uuid, b.note_uuid, link_map):
                    continue

                scope_a = a.scope or "unscoped"
                scope_b = b.scope or "unscoped"
                if scope_a != scope_b:
                    if not _grants_permit_surface(config.cross_scope_grants, scope_a, scope_b):
                        # Content-free denial (KERNEL-10): record that a
                        # cross-scope candidate was excluded, never which
                        # notes/scopes/content. No object identity, no count
                        # of pairs, no per-pair reason.
                        suppressed_by_cross_scope_denial += 1
                        reason = "cross_scope_no_flow"
                        if reason not in denial_reasons:
                            denial_reasons.append(reason)
                        continue

                basis = f"{_score_class(a.score)}|{a.span[:80]}|{b.span[:80]}"
                observed = f"'{a.rel_path or a.note_uuid}' and '{b.rel_path or b.note_uuid}' share unlinked related content"
                proposed = f"consider linking '{a.rel_path or a.note_uuid}' <-> '{b.rel_path or b.note_uuid}'"
                group = _make_connect_findings(
                    finding_class=FindingClass.CONNECT_RELATED_UNLINKED,
                    candidates=(a, b),
                    observed=observed,
                    proposed=proposed,
                    basis=basis,
                )
                finding_id = group[0].finding_id

                if finding_id in seen_finding_ids:
                    continue  # idempotent within this pass too (symmetric pair, either order)
                if config.declined_ledger.is_declined(finding_id):
                    suppressed_by_decline += 1
                    continue

                seen_finding_ids.add(finding_id)
                candidate_groups.append(group)

    # Deterministic ordering before cap enforcement so truncation is
    # reproducible across reruns (lowest finding_id first) -- one logical
    # finding (pair) is the unit of ordering/capping, not the per-side record.
    candidate_groups.sort(key=lambda group: group[0].finding_id)

    accepted_groups: list[tuple[CurationFinding, ...]] = []
    findings_by_note: dict[str, int] = {}
    suppressed_by_cap = 0
    for group in candidate_groups:
        if len(accepted_groups) >= config.max_findings_total:
            suppressed_by_cap += len(candidate_groups) - len(accepted_groups)
            break
        # A pair is capped per-note if EITHER participant is already at cap --
        # a note must never accumulate more than max_findings_per_note
        # connect proposals regardless of which side of the pair it's on.
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

    return ConnectPassReport(
        findings=tuple(accepted),
        notes_scanned=notes_scanned,
        suppressed_by_decline=suppressed_by_decline,
        suppressed_by_cap=suppressed_by_cap,
        suppressed_by_cross_scope_denial=suppressed_by_cross_scope_denial,
        denials=tuple(denial_reasons),
    )


# --- cluster emergence (EXP-5, #2998) ----------------------------------------

_DEFAULT_MIN_CLUSTER_SIZE = 3


@dataclass(frozen=True)
class ClusterEmergenceConfig:
    """Bounds + policy knobs for cluster-emergence detection (spec §1.1)."""

    min_cluster_size: int = _DEFAULT_MIN_CLUSTER_SIZE
    max_clusters: int = 10
    declined_ledger: DeclinedLedgerPort = field(default_factory=default_declined_ledger)


def _union_find_clusters(pairs: list[tuple[str, str]]) -> list[frozenset[str]]:
    """Group note identities into connected components over *pairs* (an
    undirected relatedness graph) via a small, deterministic union-find.

    Deterministic regardless of pair iteration order -- the resulting
    components are order-independent sets, matching the same "unordered set"
    discipline :func:`compute_connect_finding_id` already applies to a single
    pair.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Deterministic tie-break: lexicographically smaller root wins,
            # so component identity never depends on pair traversal order.
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for a, b in pairs:
        union(a, b)

    members_by_root: dict[str, set[str]] = {}
    for node in parent:
        members_by_root.setdefault(find(node), set()).add(node)
    return [frozenset(members) for members in members_by_root.values()]


def compute_cluster_finding_id(*, member_uuids: frozenset[str]) -> str:
    """Content-derived, order-independent finding id for a cluster-emergence
    finding -- ``hash(class, unordered member-uuid set)`` (spec §1.2's
    identity discipline, extended to an N-member set rather than a pair)."""
    sorted_uuids = "\x1e".join(sorted(member_uuids))
    digest_input = "\x1f".join([FindingClass.CONNECT_CLUSTER_EMERGENCE.value, sorted_uuids])
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClusterEmergenceReport:
    """Pass receipt for one cluster-emergence detection run."""

    findings: tuple[CurationFinding, ...]
    clusters_found: int
    suppressed_by_decline: int
    suppressed_by_cap: int


def find_cluster_emergence(
    related_unlinked_findings: tuple[CurationFinding, ...],
    *,
    config: ClusterEmergenceConfig | None = None,
) -> ClusterEmergenceReport:
    """Detect unnamed clusters reaching hub-worthiness from a Connect pass's
    already-computed ``connect.related_unlinked`` findings (spec §1.1
    ``connect.cluster_emergence``: "an unnamed cluster that has reached
    hub-worthiness; proposes creating an overview/hub note").

    Reuses the SAME accepted pair graph :func:`run_connect_pass` already
    proposed (never re-queries retrieval, never re-derives relatedness) --
    a cluster is a connected component of >= ``min_cluster_size`` distinct
    note identities across those pairs. Candidate-only by construction: this
    function returns :class:`CurationFinding` records (class
    :data:`app.curation.findings.FindingClass.CONNECT_CLUSTER_EMERGENCE`,
    which resolves to :data:`app.curation.findings.FindingTrack.PROPOSE`
    unconditionally via ``track_for_class`` -- there is no branch here, or
    anywhere, that materializes a cluster as an overview directly). Declined
    clusters (by content-derived cluster finding_id) are suppressed exactly
    like every other propose-track class.
    """
    config = config or ClusterEmergenceConfig()

    pair_findings_by_id: dict[str, list[CurationFinding]] = {}
    for finding in related_unlinked_findings:
        if finding.finding_class != FindingClass.CONNECT_RELATED_UNLINKED:
            continue
        pair_findings_by_id.setdefault(finding.finding_id, []).append(finding)

    pairs: list[tuple[str, str]] = []
    span_by_uuid: dict[str, str] = {}
    for group in pair_findings_by_id.values():
        uuids = sorted({f.note_uuid for f in group})
        if len(uuids) == 2:
            pairs.append((uuids[0], uuids[1]))
        for f in group:
            span_by_uuid.setdefault(f.note_uuid, f.evidence[0] if f.evidence else f.note_uuid)

    components = [c for c in _union_find_clusters(pairs) if len(c) >= config.min_cluster_size]
    # Deterministic ordering: smallest sorted-member signature first, so
    # truncation at max_clusters is reproducible across reruns.
    components.sort(key=lambda members: tuple(sorted(members)))

    findings: list[CurationFinding] = []
    suppressed_by_decline = 0
    suppressed_by_cap = 0
    track = track_for_class(FindingClass.CONNECT_CLUSTER_EMERGENCE)

    for members in components:
        if len(findings) // max(config.min_cluster_size, 1) >= config.max_clusters and findings:
            suppressed_by_cap += 1
            continue
        finding_id = compute_cluster_finding_id(member_uuids=members)
        if config.declined_ledger.is_declined(finding_id):
            suppressed_by_decline += 1
            continue
        member_list = sorted(members)
        observed = f"{len(member_list)} notes ({', '.join(member_list)}) form an unnamed, densely related cluster"
        proposed = "consider creating an overview/hub note over this cluster (uncertain theme label)"
        for member in member_list:
            evidence_entries = [span_by_uuid.get(member, member)]
            evidence_entries.extend(
                span_by_uuid.get(other, other) for other in member_list if other != member
            )
            findings.append(
                CurationFinding(
                    finding_id=finding_id,
                    note_uuid=member,
                    finding_class=FindingClass.CONNECT_CLUSTER_EMERGENCE,
                    track=track,
                    span="draft theme label: uncertain",
                    observed=observed,
                    proposed=proposed,
                    evidence=tuple(evidence_entries),
                    language_verdict=LanguageVerdict.UNKNOWN,
                    reversal=None,
                )
            )

    return ClusterEmergenceReport(
        findings=tuple(findings),
        clusters_found=len(components),
        suppressed_by_decline=suppressed_by_decline,
        suppressed_by_cap=suppressed_by_cap,
    )


def cluster_emergence_to_create_request(
    cluster_finding_ids: frozenset[str] | list[str],
    *,
    member_sources: dict[str, "SourceInput"],
    title: str,
    language_policy: str | None = None,
) -> "CreateRequest":
    """Convert an ALREADY-ACCEPTED ``connect.cluster_emergence`` finding into
    a :class:`app.expansion.create.CreateRequest` of kind
    :data:`app.expansion.create.OutputKind.OVERVIEW` (spec §1.1 handoff: "an
    unnamed cluster ... proposes creating an overview/hub note").

    This function performs NO acceptance-state check of its own -- the caller
    (the real acceptance path, ``app.expansion.accept``, or a CLI/panel
    handler wired to it) is responsible for calling this ONLY after a human
    has accepted the cluster finding's checkbox. It never calls
    ``run_create_pass`` itself; it only builds the request, so the normal
    Create draft lifecycle (activation gate -> citation validation -> staging
    write -> human acceptance, EXP-3/EXP-4) governs the resulting overview
    exactly like any other Create request -- the cluster handoff grants no
    shortcut through that lifecycle.

    ``member_sources`` must supply a :class:`app.expansion.create.SourceInput`
    for every member uuid in *cluster_finding_ids* (the member set); a missing
    member raises ``ValueError`` -- fail loud rather than silently synthesizing
    an overview over a subset of the cluster.
    """
    from app.expansion.create import CreateRequest, OutputKind

    member_uuids = frozenset(cluster_finding_ids)
    if not member_uuids:
        raise ValueError("cluster_emergence_to_create_request requires at least one member uuid")
    missing = member_uuids - set(member_sources)
    if missing:
        raise ValueError(
            f"member_sources is missing source input for cluster member(s) {sorted(missing)!r}; "
            "refusing to synthesize an overview over an incomplete cluster"
        )
    sources = tuple(member_sources[uuid] for uuid in sorted(member_uuids))
    return CreateRequest(
        kind=OutputKind.OVERVIEW,
        title=title,
        sources=sources,
        language_policy=language_policy,
    )


__all__ = [
    "CONNECT_EVIDENCE_ROLE",
    "ClusterEmergenceConfig",
    "ClusterEmergenceReport",
    "ConnectPassConfig",
    "ConnectPassReport",
    "CrossScopeFlow",
    "DeclinedLedgerPort",
    "cluster_emergence_to_create_request",
    "compute_cluster_finding_id",
    "compute_connect_finding_id",
    "default_declined_ledger",
    "find_cluster_emergence",
    "run_connect_pass",
]
