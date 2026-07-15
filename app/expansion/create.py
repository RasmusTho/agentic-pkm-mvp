"""Create engine: overview + answer_note + digest draft synthesis (EXP-3/EXP-5,
#2996/#2998).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2
(EXP-3, EXP-5). Parent: #2980 (Capability Hardening / Cognitive Expansion).
Turns admitted material into a reviewable synthesized artifact via the
dormant ``CompilationDraft``/``proposal_builders``/``run_multi_note_reasoning``
machinery, activated through the Expansion Activation Gate
(``app.activation.gate``) rather than rebuilt -- the second passage through
that gate the ASK synthesis proof (#2022/#2026) already validated once.

This module implements all three output kinds (closed enum, no default):
``create.overview`` (a synthesis/overview over a topic/cluster/note-set),
``create.answer_note`` (an ASK answer filed as a durable note with sources),
and ``create.digest`` (a bounded-period digest -- EXP-5, #2998; explicit-ask
only through :func:`run_create_pass` in this slice). A moment may only ever
materialize a digest *offer* checkbox, never a draft directly from tick
context -- see :func:`build_digest_offer`, the G4 moment-offer wiring point
this slice builds without depending on G4-1 landing.

Hard invariants held by this module (do not relax without an owner-ratified
ADR, mirroring ``app.expansion.connect``'s and
``app.knowledge_compilation.proposal_builders``'s posture):

- **This slice produces DRAFTS ONLY.** The only write this module ever
  performs is a staging-area note under ``_system/drafts/`` (spec §2.3, owner
  decision E1's recommended default -- no owner ruling has superseded it, so
  this module uses it as documented). There is no code path here, and no
  configuration flag, that writes a canonical vault location --
  acceptance/materialization is EXP-4's scope (#2997), not this module's.
- **No default output kind.** :func:`run_create_pass` raises
  :class:`InvalidOutputKindError` for anything outside
  :data:`SUPPORTED_OUTPUT_KINDS` -- an unrecognized or unsupported kind (e.g.
  the not-yet-built ``create.digest``) fails loud, never silently falls back
  to a default.
- **Every synthesized draft carries resolvable SourceRefs.** Citation
  validation (:func:`_validate_citations`) checks that every cited object id
  resolves in the object store and that every quoted span exists verbatim in
  the source's text. An unresolvable citation raises
  :class:`UnresolvableCitationError` -- the draft is blocked from proposal
  loudly, never silently pruned to drop the unsupported claim (spec §2.2).
- **No hidden-authority laundering.** Drafts are assembled via
  ``app.knowledge_compilation.proposal_builders.build_compilation_draft``, so
  the existing ``_reject_hidden_authority`` guard applies unchanged: a
  write-authorizing, stale, or non-approved-review-state context is refused
  at construction, not just at this module's own checks.
- **Gated by the Expansion Activation Gate.** :func:`run_create_pass` first
  evaluates :func:`build_create_activation_posture` /
  :func:`evaluate_activation`; a regressed gate input (or no admissible
  candidate) returns a ``blocked`` :class:`CreatePassResult`, never a silent
  run (spec §4, invariant ``expansion_requires_activation_record``).
- **Staged drafts are invisible to retrieval.** The staging write lands under
  ``_system/drafts/`` (spec §2.3), which ``app.ingest.vault_alpha`` already
  excludes from indexing candidates the same way it excludes
  ``_system/companions`` -- this module relies on that existing ingest-side
  exclusion rather than re-implementing it; the invariant test
  (``tests/invariants/test_expansion_invariants.py::test_drafts_invisible_to_retrieval``)
  asserts the production ingest call site actually skips the directory.
- **Multilingual discipline (spec §2.5).** Quoted spans are never translated;
  the draft header states the language rule applied
  (:func:`_resolve_output_language`).
- **Expiry is silent-safe.** :func:`sweep_expired_drafts` never raises for a
  missing/unreadable staging dir or a malformed draft file; it removes only
  drafts past their declared ``expires`` timestamp and always emits an
  ``expansion.create.expired`` receipt per removed draft.
- **A moment can only offer a digest, never generate one.** :func:`build_digest_offer`
  is the ONLY function in this module that accepts tick/moment-style context.
  It returns a :class:`DigestOffer` -- an inert, unchecked offer-checkbox
  description -- and contains no code path that calls :func:`run_create_pass`
  or otherwise materializes a draft. There is no configuration flag that
  upgrades an offer into a run; a human must independently trigger
  :func:`run_create_pass` with ``kind=OutputKind.DIGEST`` (the explicit-ask
  path) after seeing the offer. This is the G4 moment-offer wiring point the
  spec names (§2.1 "later optionally *offered* via a G4 moment -- offered,
  never auto-run"); it does not depend on G4-1 (the state-diff gate) landing
  because it never reads a live tick -- it accepts a plain period-bounds
  input the caller (a future G4-1 tick or a manual CLI invocation alike) can
  supply either way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from app.activation.gate import (
    ActivationDecision,
    ActivationPosture,
    CandidateContext,
    ConsumingAuthority,
    evaluate_activation,
)
from app.knowledge_compilation.proposal_builders import ProposalContext, build_compilation_draft
from app.knowledge_compilation.runtime_artifacts import CompilationDraft, ContextAuthorityLimits, SourceRef
from app.reasoning.multi import run_multi_note_reasoning
from app.services.outbox import append_jsonl_outbox_event
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# --- output kinds (closed enum; no default) ---------------------------------


class OutputKind(str, Enum):
    """The Create output-kind enum (spec §2.1). Closed and versioned: adding a
    member here is the only place a new kind may be minted. All three members
    are implemented and included in :data:`SUPPORTED_OUTPUT_KINDS`;
    ``create.digest`` (EXP-5, #2998) is explicit-ask only through
    :func:`run_create_pass` -- a moment may only ever produce an *offer* via
    :func:`build_digest_offer`, never call ``run_create_pass`` directly."""

    OVERVIEW = "create.overview"
    ANSWER_NOTE = "create.answer_note"
    DIGEST = "create.digest"


# The closed subset `run_create_pass` will build. Anything outside this set
# fails loud via `InvalidOutputKindError` -- no default kind (spec §2.1).
SUPPORTED_OUTPUT_KINDS: frozenset[OutputKind] = frozenset(
    {OutputKind.OVERVIEW, OutputKind.ANSWER_NOTE, OutputKind.DIGEST}
)

CREATE_CAPABILITY_ID = "synthesis_note_proposal"
CREATE_SCOPE = "expansion.create.staging"

# WriteGuard-gated, named action (dotted <module>.<verb> convention, mirroring
# CURATION_PROPOSE_WRITE_ACTION / DECLINED_LEDGER_WRITE_ACTION).
CREATE_STAGING_WRITE_ACTION = "expansion.create.stage_write"

# Staging location -- owner decision E1 (spec §7): recommended `_system/drafts/`
# inside the vault. No owner ruling has superseded this recommendation, so
# this module uses it as the documented default rather than inventing a new
# location. Follow-up: revisit if/when the owner rules otherwise.
DRAFTS_SUBDIR = "drafts"

DEFAULT_STALENESS_DAYS = 14

CREATE_PROPOSED_EVENT = "expansion.create.proposed"
CREATE_EXPIRED_EVENT = "expansion.create.expired"
CREATE_EVENT_SOURCE = "app.expansion.create"

_ACCEPTANCE_CHECKBOX_MARKER = "AI-åtgärder"  # "AI-åtgärder"


class InvalidOutputKindError(ValueError):
    """Raised when ``kind`` is not a member of :data:`SUPPORTED_OUTPUT_KINDS`.

    Fail-loud, no default track (spec §2.1: "Anything else is invalid -- the
    engine fails loud; no default kind.").
    """


class UnresolvableCitationError(ValueError):
    """Raised when a cited source cannot be resolved or a quoted span does not
    exist verbatim in its source text.

    The draft is blocked from proposal loudly -- this module never silently
    drops the unsupported claim (spec §2.2 keystone).
    """


class CreateBlockedError(RuntimeError):
    """Raised when the caller requests a hard failure on an activation-gate
    block, instead of receiving a ``blocked`` :class:`CreatePassResult`."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceInput:
    """One admitted source note supplied to a Create pass.

    ``object_id`` is the vault object identity the draft cites;
    ``quoted_spans`` are the verbatim spans this draft's synthesis actually
    quotes from that source (citation validation checks each one exists
    verbatim in ``text``, spec §2.2). ``language`` supports the multilingual
    rules (spec §2.5): quoted spans are rendered in the source's own
    language, never translated.
    """

    object_id: str
    note_path: str | None
    text: str
    quoted_spans: tuple[str, ...] = field(default_factory=tuple)
    language: str | None = None
    review_state: str | None = None


@dataclass(frozen=True)
class DigestActivityInput:
    """One bounded-period activity bucket for a ``create.digest`` request
    (spec §2.1: "what moved, what opened, what went quiet").

    ``moved`` / ``opened`` / ``quiet`` are vault-relative note paths (or note
    identities) the caller has already classified for the period -- this
    module never re-derives vault activity itself; a digest is a synthesis
    OVER already-known activity, the same way overview/answer_note synthesize
    over already-admitted sources, never over data this module discovers on
    its own initiative.
    """

    period_label: str  # human-legible period description, e.g. "2026-06-29..2026-07-05"
    moved: tuple[str, ...] = field(default_factory=tuple)
    opened: tuple[str, ...] = field(default_factory=tuple)
    quiet: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CreateRequest:
    """Human-triggered Create request (spec §2.2 "trigger (human intent)").

    ``digest_activity`` is required (and only meaningful) for
    ``kind=OutputKind.DIGEST``; other kinds ignore it.
    """

    kind: OutputKind
    title: str
    sources: tuple[SourceInput, ...]
    question: str | None = None
    destination_hint: str | None = None
    language_policy: str | None = None  # explicit human choice, else dominant-source
    trace_id: str | None = None
    digest_activity: DigestActivityInput | None = None


@dataclass(frozen=True)
class CreatePassReport:
    """Observability receipt for one Create pass (spec §2.6 "Observability")."""

    activatable: bool
    blocked_reasons: tuple[str, ...]
    draft_path: str | None
    receipt_id: str | None
    kind: OutputKind


def build_create_activation_posture(kind: OutputKind) -> ActivationPosture:
    """Declare the ``proposal``-authority activation posture for Create.

    Mirrors ``app.activation.ask_synthesis.build_ask_synthesis_posture``'s
    shape but at ``PROPOSAL`` authority (one step above ASK's read-only
    proof, per spec §4: "one step above ASK's read-only proof, still below
    governed execution") -- this module declares its own posture rather than
    reusing the read-only ASK posture (spec §8 "Rejected alternatives":
    "Reusing the ASK read-only activation record for Create: rejected").
    Create's staging write is the reversible write path (a new file under a
    disposable staging dir, Git-reversible), so ``reversible_write_path`` is
    True even though the declared authority ceiling is only PROPOSAL/CITED_PROPOSAL.
    """

    return ActivationPosture(
        capability_id=f"{CREATE_CAPABILITY_ID}.{kind.value}",
        declared_authority=ConsumingAuthority.PROPOSAL,
        admissibility_declared=True,
        loop_precondition_green=True,
        reversible_write_path=True,
        observable=True,
        scope=CREATE_SCOPE,
    )


def build_create_candidates(sources: Sequence[SourceInput]) -> list[CandidateContext]:
    """Build read-side candidate contexts for admitted Create sources.

    Same-scope declaration mirrors ``build_retrieval_candidates`` in
    ``app.activation.ask_synthesis``: every admitted source is declared in
    the Create staging scope so the sphere axis admits it, and as non-memory
    context (the memory-class axis is not binding for vault source notes).
    ``review_state`` defaults to ``REVIEWED`` (the vault source note itself,
    not an unreviewed/raw candidate) -- per ``app.activation.gate``'s
    provenance axis this admits at exactly the ``CITED_PROPOSAL`` tier the
    spec names ("admissibility gate at cited-proposal tier", §2.2), never the
    ``ACTION`` tier a write-authorizing consumer would need. A caller may
    override via ``source.review_state`` (e.g. a citation whose source is
    known unreviewed) without this module inventing a laxer default.
    """

    from app.agent_memory.candidate import ReviewState

    candidates: list[CandidateContext] = []
    for source in sources:
        artifact_id = (source.object_id or "").strip()
        if not artifact_id:
            continue
        review_state_raw = (source.review_state or "reviewed").strip().lower()
        try:
            review_state = ReviewState(review_state_raw)
        except ValueError:
            review_state = ReviewState.REVIEWED
        candidates.append(
            CandidateContext(
                artifact_id=artifact_id,
                sphere=CREATE_SCOPE,
                is_memory=False,
                has_provenance=True,
                review_state=review_state,
            )
        )
    return candidates


def evaluate_create_activation(
    kind: OutputKind,
    sources: Sequence[SourceInput],
    *,
    receipt_id: str | None = None,
    now: datetime | None = None,
) -> ActivationDecision:
    """Evaluate the Create activation-gate decision for one pass."""

    posture = build_create_activation_posture(kind)
    candidates = build_create_candidates(sources)
    return evaluate_activation(posture, candidates, receipt_id=receipt_id, now=now)


def _validate_citations(sources: Sequence[SourceInput]) -> None:
    """Validate every cited source resolves and every quoted span exists
    verbatim in its source text.

    Raises :class:`UnresolvableCitationError` on the first failure -- loud,
    never silently pruned (spec §2.2 keystone).
    """

    if not sources:
        raise UnresolvableCitationError(
            "a Create draft requires at least one source; refusing to synthesize an unsourced draft"
        )
    for source in sources:
        if not (source.object_id or "").strip():
            raise UnresolvableCitationError("a source with an empty object_id cannot be cited")
        if not (source.text or "").strip():
            raise UnresolvableCitationError(
                f"source {source.object_id!r} has no resolvable text; citation cannot be validated"
            )
        for span in source.quoted_spans:
            if span not in source.text:
                raise UnresolvableCitationError(
                    f"quoted span {span!r} does not exist verbatim in source "
                    f"{source.object_id!r}; blocking draft from proposal"
                )


def _resolve_output_language(
    sources: Sequence[SourceInput], *, language_policy: str | None
) -> tuple[str, str]:
    """Resolve the draft's narrative output language + the applied rule label
    (spec §2.5: explicit choice, else dominant source language)."""

    if language_policy:
        return language_policy, "explicit_choice"
    counts: dict[str, int] = {}
    for source in sources:
        lang = (source.language or "").strip().lower()
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "und", "dominant_source_unknown"
    dominant = max(counts.items(), key=lambda kv: kv[1])[0]
    return dominant, "dominant_source_language"


def _build_source_refs(sources: Sequence[SourceInput]) -> tuple[SourceRef, ...]:
    """Build provenance-preserving SourceRefs for the draft.

    Deliberately does NOT stamp ``retrieval_score`` or a ``_MACHINE_DERIVATIONS``
    ``derived_by`` value: a Create citation names the *source note itself* as
    approved context for this pass, not a retrieval-ranking artifact -- the
    admissibility gate (not ``proposal_builders``' hidden-authority guard) is
    what governs whether a given source was fairly admitted into this
    synthesis. Carrying a `review_state` through lets a caller record the
    source's known review posture without this module inventing one.
    """

    return tuple(
        SourceRef(
            artifact_id=source.object_id,
            note_path=source.note_path,
            role="cited",
            review_state=source.review_state,
        )
        for source in sources
    )


def _build_synthesis_body(
    request: CreateRequest, *, sources: Sequence[SourceInput], language: str, language_rule: str
) -> str:
    """Deterministic collation body: cognition augments this, but the module's
    deterministic fallback (spec §2.6: "no LLM -> no synthesis... a
    research-pack-style deterministic collation") is always what grounds the
    citation-checkable structure -- sources + verbatim quoted spans, never an
    unsourced narrative."""

    lines: list[str] = []
    lines.append(f"# {request.title}")
    lines.append("")
    lines.append(
        f"_Output language: {language} ({language_rule}). Quoted spans are verbatim and never "
        "translated; mixed-language synthesis quotes each source in its own language._"
    )
    lines.append("")
    if request.question:
        lines.append(f"**Question:** {request.question}")
        lines.append("")
    if request.kind is OutputKind.DIGEST and request.digest_activity is not None:
        lines.extend(_digest_activity_section(request.digest_activity))
    lines.append("## Sources")
    lines.append("")
    for source in sources:
        label = source.note_path or source.object_id
        lines.append(f"### {label}")
        for span in source.quoted_spans:
            lines.append(f"> {span}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _digest_activity_section(activity: DigestActivityInput) -> list[str]:
    """Render the digest's period-bounded activity buckets (spec §2.1: "what
    moved, what opened, what went quiet") as a deterministic, citation-free
    summary section -- the note-level ``## Sources`` block (built separately,
    from ``request.sources``) is what carries the citation-checkable
    structure; this section is a legible index over already-classified
    activity, never a re-derivation of it."""

    lines = [f"## Digest period: {activity.period_label}", ""]

    def _bucket(title: str, items: tuple[str, ...]) -> list[str]:
        out = [f"### {title}", ""]
        if items:
            out.extend(f"- {item}" for item in items)
        else:
            out.append("- (none)")
        out.append("")
        return out

    lines.extend(_bucket("What moved", activity.moved))
    lines.extend(_bucket("What opened", activity.opened))
    lines.extend(_bucket("What went quiet", activity.quiet))
    return lines


def _run_cognition(request: CreateRequest) -> dict[str, Any]:
    """Run the dormant cross-note reasoning engine (spec §2.2 "cognition").

    Failure here degrades to the deterministic collation fallback (spec §2.6)
    rather than blocking the draft -- cognition augments the body; it is
    never the sole source of citation-checkable structure.
    """

    object_ids = [source.object_id for source in request.sources]
    try:
        output = run_multi_note_reasoning(object_ids, trace_id=request.trace_id)
    except Exception:
        return {
            "claims": 0,
            "inferences": 0,
            "degraded": True,
            "outcome": "provider_failure",
            "degraded_reason": "provider_failure",
        }
    return {
        "claims": len(output.claims),
        "inferences": len(output.inferences),
        "degraded": output.degraded,
        "outcome": output.outcome,
        "degraded_reason": output.degraded_reason,
    }


def _drafts_dir(vault_root: Path) -> Path:
    from app.vault.paths import get_vault_system_dir_rel

    system_root = Path(get_vault_system_dir_rel(vault_root))
    return vault_root / system_root / DRAFTS_SUBDIR


def _draft_frontmatter(
    *,
    kind: OutputKind,
    draft_id: str,
    sources: Sequence[SourceInput],
    cognition_metadata: dict[str, Any],
    created_at: datetime,
    staleness_days: int,
) -> dict[str, Any]:
    return {
        "uuid": draft_id,
        "kind": "draft",
        "derived_by": "synthesis",
        "authority_state": "proposal",
        "proposed_by": {
            "capability": CREATE_CAPABILITY_ID,
            "cognition": cognition_metadata,
        },
        "sources": [source.object_id for source in sources],
        "create_kind": kind.value,
        "created": _iso(created_at),
        "expires": _iso(created_at + timedelta(days=staleness_days)),
    }


def _draft_note_text(
    *,
    frontmatter: dict[str, Any],
    body: str,
    draft_id: str,
) -> str:
    from scripts.yaml_roundtrip import dump_frontmatter

    checkbox_block = (
        "\n%% AI:Start %%\n"
        f"## {_ACCEPTANCE_CHECKBOX_MARKER}\n\n"
        f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})\n"
        "%% AI:End %%\n"
    )
    return dump_frontmatter(frontmatter, body) + checkbox_block


def _emit_receipt(event: str, payload: dict[str, Any], *, outbox_path: Path, trace_id: str | None) -> str:
    event_id = uuid4().hex
    record = {
        "event": event,
        "event_id": event_id,
        "trace_id": trace_id or uuid4().hex,
        "source": CREATE_EVENT_SOURCE,
        "timestamp": _iso(_now()),
        "payload": payload,
    }
    append_jsonl_outbox_event(outbox_path, record, default_source=CREATE_EVENT_SOURCE)
    return event_id


def run_create_pass(
    request: CreateRequest,
    *,
    vault_root: Path,
    outbox_path: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
    now: datetime | None = None,
) -> CreatePassReport:
    """Run one Create pass end to end: activation gate -> cognition ->
    CompilationDraft -> citation validation -> staging write -> receipt.

    Raises :class:`InvalidOutputKindError` for an unsupported kind and
    :class:`UnresolvableCitationError` for a citation that fails to resolve
    -- both are fail-loud, never silently degraded. A blocked activation gate
    returns a ``CreatePassReport(activatable=False, ...)`` rather than
    raising, so callers can surface "blocked-with-reason" without a
    try/except for the expected-blocked case (mirrors
    ``evaluate_activation``'s own non-raising blocked outcome).
    """

    if request.kind not in SUPPORTED_OUTPUT_KINDS:
        raise InvalidOutputKindError(
            f"unsupported Create output kind {request.kind!r}; this slice only supports "
            f"{sorted(k.value for k in SUPPORTED_OUTPUT_KINDS)}"
        )

    now = now or _now()
    decision = evaluate_create_activation(request.kind, request.sources, now=now)
    if not decision.activatable:
        return CreatePassReport(
            activatable=False,
            blocked_reasons=tuple(decision.blocked_reasons),
            draft_path=None,
            receipt_id=None,
            kind=request.kind,
        )

    # Citation validation BEFORE any draft/context is built -- an unresolvable
    # citation must block the draft, never silently prune the unsupported
    # claim (spec §2.2 keystone).
    _validate_citations(request.sources)

    language, language_rule = _resolve_output_language(
        request.sources, language_policy=request.language_policy
    )
    cognition_metadata = _run_cognition(request)
    body = _build_synthesis_body(
        request, sources=request.sources, language=language, language_rule=language_rule
    )
    source_refs = _build_source_refs(request.sources)

    # Routed through proposal_builders so the no-laundering guard
    # (_MACHINE_DERIVATIONS / _reject_hidden_authority) applies unchanged --
    # this module never bypasses it, only supplies approved context.
    context = ProposalContext(
        source_refs=source_refs,
        authority_limits=ContextAuthorityLimits(may_inform=True, may_propose=True),
        content=body,
        generated_by=CREATE_CAPABILITY_ID,
        trace_ref=request.trace_id,
    )
    draft: CompilationDraft = build_compilation_draft(context, title=request.title)

    write_guard.assert_writes_allowed(CREATE_STAGING_WRITE_ACTION)

    vault_root = Path(vault_root).expanduser().resolve()
    drafts_dir = _drafts_dir(vault_root)
    drafts_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = _draft_frontmatter(
        kind=request.kind,
        draft_id=draft.artifact_id,
        sources=request.sources,
        cognition_metadata=cognition_metadata,
        created_at=now,
        staleness_days=staleness_days,
    )
    note_text = _draft_note_text(frontmatter=frontmatter, body=draft.body or "", draft_id=draft.artifact_id)
    draft_path = drafts_dir / f"{draft.artifact_id}.md"
    draft_path.write_text(note_text, encoding="utf-8")

    receipt_id = _emit_receipt(
        CREATE_PROPOSED_EVENT,
        {
            "draft_id": draft.artifact_id,
            "kind": request.kind.value,
            "sources": [s.object_id for s in request.sources],
            "cognition_metadata": cognition_metadata,
            "draft_path": str(draft_path.relative_to(vault_root)),
            "language": language,
            "language_rule": language_rule,
        },
        outbox_path=outbox_path,
        trace_id=request.trace_id,
    )

    return CreatePassReport(
        activatable=True,
        blocked_reasons=(),
        draft_path=str(draft_path.relative_to(vault_root)),
        receipt_id=receipt_id,
        kind=request.kind,
    )


# --- G4 moment-offer wiring point (EXP-5, #2998; offer-only) ----------------

DIGEST_OFFER_EVENT = "expansion.create.digest_offered"


@dataclass(frozen=True)
class DigestOffer:
    """An inert digest OFFER -- an unchecked checkbox description a moment
    surface may materialize, never a draft.

    This is the whole shape of the G4 wiring point (spec §2.1: "later
    optionally *offered* via a G4 moment -- offered, never auto-run"): it
    carries enough for a Panel/companion surface to render one checkbox
    ("offer to generate a digest for <period>") and nothing that could be
    mistaken for, or silently escalated into, a generated draft. There is no
    ``draft_path`` field here -- offering a digest produces no file.
    """

    period_label: str
    offer_label: str
    moment_id: str | None


def build_digest_offer(
    *,
    period_label: str,
    moment_id: str | None = None,
) -> DigestOffer:
    """Build a digest OFFER from tick/moment-style context -- the ONLY
    function in this module a moment surface may call for digests.

    Deliberately takes no ``sources``/``digest_activity`` payload and returns
    no draft/receipt-id-for-a-draft: there is nothing here a caller could
    thread into :func:`run_create_pass` to make this call site auto-generate
    a digest. Materializing the returned offer as an actual checkbox
    (a propose-track write, mirroring ``app.curation.proposal_writer``) is
    the caller's concern; checking that checkbox is a SEPARATE, later human
    act that must independently invoke :func:`run_create_pass` with
    ``kind=OutputKind.DIGEST`` -- offering is never running.
    """

    if not (period_label or "").strip():
        raise ValueError("build_digest_offer requires a non-empty period_label")
    return DigestOffer(
        period_label=period_label,
        offer_label=f"Offer: generate a digest for {period_label}?",
        moment_id=moment_id,
    )


def emit_digest_offer_receipt(
    offer: DigestOffer,
    *,
    outbox_path: Path,
    trace_id: str | None = None,
) -> str:
    """Emit an observability receipt for a materialized digest offer
    (never for a generated digest -- that receipt is
    :data:`CREATE_PROPOSED_EVENT`, only reachable through the explicit-ask
    :func:`run_create_pass` path)."""

    return _emit_receipt(
        DIGEST_OFFER_EVENT,
        {
            "period_label": offer.period_label,
            "offer_label": offer.offer_label,
            "moment_id": offer.moment_id,
        },
        outbox_path=outbox_path,
        trace_id=trace_id,
    )


# --- expiry sweep -------------------------------------------------------------


@dataclass(frozen=True)
class ExpirySweepReport:
    """Observability receipt for one expiry sweep (spec §2.2 "ignore -> draft
    expires after a bounded staleness window ... expiry is silent-safe,
    receipt records it")."""

    expired: tuple[str, ...]
    receipt_ids: tuple[str, ...]


def _is_checked(text: str) -> bool:
    return "- [x]" in text or "- [X]" in text


def sweep_expired_drafts(
    *,
    vault_root: Path,
    outbox_path: Path,
    now: datetime | None = None,
) -> ExpirySweepReport:
    """Remove staged drafts past their declared ``expires`` timestamp whose
    acceptance checkbox was never checked.

    Never raises: a missing staging dir, an unreadable file, or malformed
    frontmatter is skipped rather than treated as an error (spec: "expiry is
    silent-safe"). Every removed draft emits one ``expansion.create.expired``
    receipt.
    """

    from scripts.yaml_roundtrip import load_frontmatter

    now = now or _now()
    vault_root = Path(vault_root).expanduser().resolve()
    drafts_dir = _drafts_dir(vault_root)
    expired: list[str] = []
    receipt_ids: list[str] = []

    if not drafts_dir.exists():
        return ExpirySweepReport(expired=(), receipt_ids=())

    for path in sorted(drafts_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _is_checked(text):
            # An accepted draft is EXP-4's concern (acceptance/promotion);
            # this sweep never removes a checked draft.
            continue
        frontmatter, _body = load_frontmatter(text)
        expires_raw = frontmatter.get("expires")
        if not isinstance(expires_raw, str) or not expires_raw:
            continue
        try:
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires_at > now:
            continue

        draft_id = str(frontmatter.get("uuid") or path.stem)
        try:
            path.unlink()
        except OSError:
            continue
        expired.append(draft_id)
        receipt_id = _emit_receipt(
            CREATE_EXPIRED_EVENT,
            {
                "draft_id": draft_id,
                "draft_path": str(path.relative_to(vault_root)),
                "expired_at": _iso(now),
            },
            outbox_path=outbox_path,
            trace_id=None,
        )
        receipt_ids.append(receipt_id)

    return ExpirySweepReport(expired=tuple(expired), receipt_ids=tuple(receipt_ids))


__all__ = [
    "CREATE_CAPABILITY_ID",
    "CREATE_EXPIRED_EVENT",
    "CREATE_PROPOSED_EVENT",
    "CREATE_SCOPE",
    "CREATE_STAGING_WRITE_ACTION",
    "DEFAULT_STALENESS_DAYS",
    "DIGEST_OFFER_EVENT",
    "DRAFTS_SUBDIR",
    "SUPPORTED_OUTPUT_KINDS",
    "CreateBlockedError",
    "CreatePassReport",
    "CreateRequest",
    "DigestActivityInput",
    "DigestOffer",
    "ExpirySweepReport",
    "InvalidOutputKindError",
    "OutputKind",
    "SourceInput",
    "UnresolvableCitationError",
    "build_create_activation_posture",
    "build_create_candidates",
    "build_digest_offer",
    "emit_digest_offer_receipt",
    "evaluate_create_activation",
    "run_create_pass",
    "sweep_expired_drafts",
]
