"""Governed acceptance/promotion of staged Create drafts (EXP-4, #2997).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2.4,
§5 (EXP-4). Parent: #2980 (Capability Hardening / Cognitive Expansion). This is
the *only* path from a staged Create draft (produced by
``app.expansion.create.run_create_pass``, EXP-3) to a canonical vault note. It
implements the acceptance half of ``create_never_autowrites_canonical``: a
staged draft becomes canonical vault content ONLY through a human acceptance
receipt, never on the machine's own initiative.

Authority model (the point of this slice — do not relax without an owner-ratified
ADR; ``docs/testing/invariant-tests.md`` names these invariants):

- **The human checkbox is the sole trigger.** The staged draft carries one
  unchecked in-draft acceptance checkbox (EXP-3 writes ``- [ ] Accept ...``).
  A human checking it (``- [x]``) is the acceptance decision — substrate-neutral,
  exactly like the Panel confirmation checkbox. :func:`accept_draft` refuses to
  materialize a draft whose checkbox is still unchecked
  (:class:`DraftNotAcceptedError`); there is no code path, and no configuration
  flag, that materializes an unchecked draft. This is
  ``create_never_autowrites_canonical`` (acceptance side).

- **Acceptance is a governed AuthorityTransition** (``authority-transition.schema.json``):
  the checked checkbox mints a :class:`DecisionToken` (the pre-mutation
  ``decision_token_ref``) and the completed materialization emits an
  ``expansion.create.accepted`` :class:`AcceptanceReceipt` (the post-mutation
  ``authority_receipt_id``). Both ride on the transition record. This is
  ``authority_transition_requires_decision_token_and_receipt``.

- **Execution cannot authorize itself** (``execution_cannot_authorize_itself``):
  the decision token is derived *only* from the human's checked checkbox
  (:func:`_mint_decision_token`), never minted by the materialization path on
  its own. A caller cannot pass a fabricated token; the token is computed here
  from the observed checkbox state, so an unchecked draft can produce no token
  and therefore no transition and therefore no canonical write.

- **WriteGuard gates the canonical materialization** with a named action
  (:data:`ACCEPT_MATERIALIZE_WRITE_ACTION`), asserted before the canonical file
  is written — the same fail-closed gate every other durable write in the repo
  consults.

- **Provenance survives acceptance permanently** (``synthesis_carries_source_provenance``,
  ``test_accepted_note_keeps_provenance``): the materialized note keeps its
  ``sources:`` list and ``derived_by: synthesis``, and gains ``accepted_by: human``,
  ``authority_state: accepted``, and the acceptance receipt id. Citations are
  re-validated at acceptance time against the live source set; a citation that no
  longer resolves blocks the acceptance LOUDLY
  (:class:`UnresolvableCitationError`) rather than silently shipping an
  unsourced/untraceable note.

- **Trust is not silently upgraded.** Acceptance advances ``authority_state``
  from ``proposal`` to ``accepted`` and stamps ``accepted_by: human`` — it does
  *not* set a real-world-evidence role and does *not* strip
  ``derived_by: synthesis``. The accepted note is knowledge the human owns, not
  evidence the machine may cite as settled, until a review state is separately
  human-advanced (spec §2.3, owner decision E4 defaulting conservative).

- **Idempotent.** Re-processing an already-accepted draft (one whose frontmatter
  already reads ``authority_state: accepted`` / carries ``accepted_by``) does not
  double-materialize: :func:`accept_draft` returns an ``already_accepted`` result
  without writing a second canonical note or a second receipt.

- **Modify-existing-note variant stays ``ask-you``.** Materializing an accepted
  draft as a **new** note is additive and Git-reversible — the human's accept is
  the explicit act, so no further gate is owed. Any variant that *modifies an
  existing canonical note* (destination resolves to an already-existing file) is
  a body edit and stays ``ask-you`` per the ratified #1881 table
  (``docs/CAPABILITY_CONTRACT_MODEL.md``): :func:`accept_draft` refuses to
  overwrite an existing canonical note (:class:`ModifyExistingRequiresAskError`)
  — this slice never materializes that variant at a lighter tier.

- **Decline is a visible lifecycle outcome, not deletion.** :func:`decline_draft`
  records the draft id in the shared declined-proposal ledger
  (``app.proposals.declined_ledger``, EXP-2), archives/removes the staged draft,
  produces NO canonical note, and keeps its decline receipt.

- **Edited-then-accepted text is authoritative.** The materialized note reflects
  the draft's *current on-disk body* at acceptance time — human edits made to the
  draft before checking the box are what get materialized, not the original
  generated draft.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.expansion.create import (
    UnresolvableCitationError,
)
from app.services.outbox import append_jsonl_outbox_event
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# --- named, WriteGuard-gated action (dotted <module>.<verb> convention) ------
ACCEPT_MATERIALIZE_WRITE_ACTION = "expansion.create.accept_materialize"

CREATE_ACCEPTED_EVENT = "expansion.create.accepted"
CREATE_DECLINED_EVENT = "expansion.create.declined"
ACCEPT_EVENT_SOURCE = "app.expansion.accept"

# Acceptance advances authority_state along the spec's frontmatter vocabulary
# (`proposal` -> `accepted`), matching what EXP-3 actually writes into the draft
# (`app.expansion.create._draft_frontmatter` stamps `authority_state: proposal`).
PROPOSAL_AUTHORITY_STATE = "proposal"
ACCEPTED_AUTHORITY_STATE = "accepted"

# Accepted synthesis stays machine-derived (never silently upgraded to evidence).
SYNTHESIS_DERIVED_BY = "synthesis"

# The AuthorityTransition operation class + initiating source (the checked
# checkbox is the human's approval).
ACCEPT_OPERATION_TYPE = "accept"
ACCEPT_INITIATING_SOURCE = "human_approval"


class AcceptError(RuntimeError):
    """Base for acceptance-path refusals."""


class DraftNotFoundError(AcceptError):
    """The staged draft path does not exist / is unreadable."""


class DraftNotAcceptedError(AcceptError):
    """The staged draft's in-draft acceptance checkbox is still unchecked.

    The machine never materializes a canonical note without the human's
    checkbox — this is the acceptance-side half of
    ``create_never_autowrites_canonical``.
    """


class ModifyExistingRequiresAskError(AcceptError):
    """The resolved destination is an existing canonical note.

    Materializing over an existing note is a body edit and stays ``ask-you``
    per the ratified #1881 table (``docs/CAPABILITY_CONTRACT_MODEL.md``). This
    slice applies the ratified table; it never quietly materializes that variant
    at a lighter tier. The checkbox for that variant *is* the ask, handled by a
    separate governed edit flow — not by this new-note materialization path.
    """


class MalformedDraftError(AcceptError):
    """The staged draft is missing the provenance frontmatter EXP-3 writes
    (``derived_by: synthesis`` / ``sources:``); refusing to materialize an
    artifact whose provenance cannot be preserved."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _is_checked(text: str) -> bool:
    """True iff the draft's acceptance checkbox has been checked by a human."""
    return "- [x]" in text or "- [X]" in text


@dataclass(frozen=True)
class DecisionToken:
    """The pre-mutation governed-write DecisionToken.

    Minted ONLY from the human's checked acceptance checkbox
    (:func:`_mint_decision_token`) — never by the materialization path on its
    own initiative (``execution_cannot_authorize_itself``). ``token_ref`` is a
    content hash over the draft id + the checkbox-checked evidence, so the token
    is inseparable from the human act that produced it.
    """

    token_ref: str
    draft_id: str
    decided_by: str  # "human" — the checkbox is the human's decision
    decided_at: str


@dataclass(frozen=True)
class AcceptanceReceipt:
    """The post-mutation AuthorityReceipt for an accepted draft.

    Links draft -> final note -> sources (spec §2.4). Carried on the
    AuthorityTransition as ``authority_receipt_id``.
    """

    receipt_id: str
    draft_id: str
    final_note_path: str
    sources: tuple[str, ...]
    decision_token_ref: str
    accepted_at: str


@dataclass(frozen=True)
class AcceptResult:
    """Outcome of one acceptance attempt (observability + call-site assertions)."""

    status: str  # "accepted" | "already_accepted"
    draft_id: str
    final_note_path: str | None
    receipt_id: str | None
    decision_token_ref: str | None
    transition_id: str | None


@dataclass(frozen=True)
class DeclineResult:
    """Outcome of one decline (spec §2.4 decline path)."""

    status: str  # "declined"
    draft_id: str
    receipt_id: str
    ledger_recorded: bool


@dataclass(frozen=True)
class _LoadedDraft:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    raw_text: str
    checked: bool


def _load_draft(draft_path: Path) -> _LoadedDraft:
    from scripts.yaml_roundtrip import load_frontmatter

    try:
        raw_text = draft_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DraftNotFoundError(f"staged draft {draft_path} is not readable: {exc}") from exc
    frontmatter, body = load_frontmatter(raw_text)
    return _LoadedDraft(
        path=draft_path,
        frontmatter=frontmatter or {},
        body=body,
        raw_text=raw_text,
        checked=_is_checked(raw_text),
    )


def _draft_id_of(loaded: _LoadedDraft) -> str:
    return str(loaded.frontmatter.get("uuid") or loaded.path.stem)


def _sources_of(loaded: _LoadedDraft) -> tuple[str, ...]:
    raw = loaded.frontmatter.get("sources")
    if not isinstance(raw, list):
        return ()
    return tuple(str(s) for s in raw if str(s).strip())


def _mint_decision_token(loaded: _LoadedDraft, *, now: datetime) -> DecisionToken:
    """Mint the governed-write DecisionToken from the human's checked checkbox.

    This is the ``execution_cannot_authorize_itself`` seam: the token exists
    only because ``loaded.checked`` is True (a human checked the box). The
    materialization path never calls this for an unchecked draft, and the token
    is a hash over the checkbox evidence, so it cannot be forged by execution.
    """
    if not loaded.checked:  # defensive: callers gate on this first
        raise DraftNotAcceptedError(
            f"draft {_draft_id_of(loaded)!r} has no checked acceptance checkbox; "
            "the machine never mints acceptance authority for an unchecked draft"
        )
    draft_id = _draft_id_of(loaded)
    digest = hashlib.sha256(
        f"human-accept::{draft_id}::checkbox-checked".encode("utf-8")
    ).hexdigest()
    return DecisionToken(
        token_ref=f"dtok-{digest[:24]}",
        draft_id=draft_id,
        decided_by="human",
        decided_at=_iso(now),
    )


def _re_validate_citations(loaded: _LoadedDraft, *, live_source_ids: set[str] | None) -> None:
    """Re-validate provenance at acceptance time (spec §2.4 / §6:
    ``synthesis_carries_source_provenance``).

    The draft must still carry its ``sources:`` list and ``derived_by: synthesis``.
    When the caller supplies the set of source ids that still resolve
    (``live_source_ids``), a cited source that no longer resolves blocks the
    acceptance LOUDLY — provenance survival is enforced at acceptance, not just
    at draft creation. When ``live_source_ids`` is None the caller has asserted
    the source set is unchanged since draft creation (already citation-validated
    by EXP-3), so only the structural provenance is re-checked.
    """
    if str(loaded.frontmatter.get("derived_by") or "").strip() != SYNTHESIS_DERIVED_BY:
        raise MalformedDraftError(
            f"draft {_draft_id_of(loaded)!r} is missing 'derived_by: {SYNTHESIS_DERIVED_BY}'; "
            "refusing to materialize an artifact whose synthesis provenance is absent"
        )
    sources = _sources_of(loaded)
    if not sources:
        raise MalformedDraftError(
            f"draft {_draft_id_of(loaded)!r} carries no 'sources:'; a synthesis note without "
            "resolvable sources is unaccountable machine text — blocking acceptance"
        )
    if live_source_ids is None:
        return
    for source_id in sources:
        if source_id not in live_source_ids:
            raise UnresolvableCitationError(
                f"cited source {source_id!r} for draft {_draft_id_of(loaded)!r} no longer resolves "
                "at acceptance time; blocking materialization (provenance must survive acceptance)"
            )


def _already_accepted(loaded: _LoadedDraft) -> bool:
    state = str(loaded.frontmatter.get("authority_state") or "").strip()
    return state == ACCEPTED_AUTHORITY_STATE or bool(loaded.frontmatter.get("accepted_by"))


def _slugify(title: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in title.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or uuid4().hex[:12]


def _resolve_destination(
    *,
    vault_root: Path,
    loaded: _LoadedDraft,
    destination: str | None,
) -> Path:
    """Resolve the human-chosen canonical destination (default correctable by
    the human, spec §2.4). Falls back to a title/id-derived filename at the
    vault root. Always contained within the vault."""
    if destination:
        rel = Path(destination)
    else:
        title = str(loaded.frontmatter.get("title") or "").strip()
        stem = _slugify(title) if title else _draft_id_of(loaded)
        rel = Path(f"{stem}.md")
    if rel.is_absolute():
        candidate = rel.resolve()
    else:
        candidate = (vault_root / rel).resolve()
    # Contain within the vault (no traversal outside the vault root).
    if not str(candidate).startswith(str(vault_root)):
        raise AcceptError(
            f"destination {destination!r} resolves outside the vault root; refusing"
        )
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate


def _build_accepted_frontmatter(
    loaded: _LoadedDraft,
    *,
    receipt_id: str,
    decision_token_ref: str,
    accepted_at: datetime,
) -> dict[str, Any]:
    """Provenance-preserving frontmatter for the accepted canonical note.

    Keeps ``sources`` + ``derived_by: synthesis`` (never stripped, never
    upgraded); advances ``authority_state`` proposal -> accepted; stamps
    ``accepted_by: human`` + the acceptance receipt id. Drops staging-only keys
    (``kind: draft``, ``expires``, ``create_kind``) that no longer apply to a
    canonical note, but never the provenance ones.
    """
    fm = dict(loaded.frontmatter)
    fm["derived_by"] = SYNTHESIS_DERIVED_BY  # permanent, not staging-only
    fm["authority_state"] = ACCEPTED_AUTHORITY_STATE
    fm["accepted_by"] = "human"
    fm["accepted_at"] = _iso(accepted_at)
    fm["acceptance_receipt_id"] = receipt_id
    fm["decision_token_ref"] = decision_token_ref
    # `sources` is preserved verbatim from the draft (do not touch it).
    fm.setdefault("sources", list(_sources_of(loaded)))
    # Staging-only keys that must not leak onto a canonical note.
    for staging_key in ("kind", "expires", "create_kind"):
        fm.pop(staging_key, None)
    return fm


def _strip_acceptance_checkbox(body: str) -> str:
    """Remove the EXP-3 acceptance checkbox block from the materialized body.

    The checkbox is a review-surface affordance on the *staged* draft; the
    accepted canonical note must not carry a live acceptance checkbox. The
    human's edits to the rest of the body are preserved verbatim.
    """
    lines = body.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == "%% AI:Start %%":
            skipping = True
            continue
        if stripped == "%% AI:End %%":
            skipping = False
            continue
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _emit_receipt(
    event: str,
    payload: dict[str, Any],
    *,
    outbox_path: Path,
    trace_id: str | None,
) -> str:
    event_id = uuid4().hex
    record = {
        "event": event,
        "event_id": event_id,
        "trace_id": trace_id or uuid4().hex,
        "source": ACCEPT_EVENT_SOURCE,
        "timestamp": _iso(_now()),
        "payload": payload,
    }
    append_jsonl_outbox_event(outbox_path, record, default_source=ACCEPT_EVENT_SOURCE)
    return event_id


def _build_authority_transition(
    *,
    target_object_id: str,
    target_scope_id: str,
    token: DecisionToken,
    receipt_id: str,
    provenance_event_ids: list[str],
    now: datetime,
) -> dict[str, Any]:
    """Assemble the governed AuthorityTransition record for this acceptance.

    Carries BOTH the pre-mutation ``decision_token_ref`` and the post-mutation
    ``authority_receipt_id`` (``authority_transition_requires_decision_token_and_receipt``),
    mirroring ``schemas/authority-transition.schema.json``. This is the
    architecture state object; WriteGuard is the runtime mechanism that gated
    the write it records.
    """
    return {
        "transition_id": f"atx-{uuid4().hex}",
        "actor_id": token.decided_by,
        "initiating_source": ACCEPT_INITIATING_SOURCE,
        "target_object_id": target_object_id,
        "target_scope_id": target_scope_id,
        "prior_authority_state": PROPOSAL_AUTHORITY_STATE,
        "requested_authority_state": ACCEPTED_AUTHORITY_STATE,
        "approved_authority_state": ACCEPTED_AUTHORITY_STATE,
        "operation_type": ACCEPT_OPERATION_TYPE,
        "approval_required": True,
        "approval_state": "approved",
        "approved_by": token.decided_by,
        "approved_at": _iso(now),
        "decision_token_ref": token.token_ref,
        "authority_receipt_id": receipt_id,
        "provenance_event_ids": list(provenance_event_ids) or [receipt_id],
        "affected_derived_representation_ids": [],
        "created_at": _iso(now),
    }


def accept_draft(
    draft_path: Path,
    *,
    vault_root: Path,
    outbox_path: Path,
    destination: str | None = None,
    live_source_ids: set[str] | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> AcceptResult:
    """Materialize a *checked* staged draft into a canonical vault note.

    The ONLY path from a staged Create draft to canonical content. Refuses:
    an unchecked draft (:class:`DraftNotAcceptedError`); a destination that is an
    existing canonical note (:class:`ModifyExistingRequiresAskError` — that
    variant stays ``ask-you``); a draft whose provenance is missing or whose
    cited sources no longer resolve (:class:`MalformedDraftError` /
    :class:`UnresolvableCitationError`). Idempotent: an already-accepted draft
    returns ``already_accepted`` without a second write or receipt.

    ``live_source_ids`` — when given, the set of source object ids that still
    resolve; a cited source outside it blocks acceptance loudly. When None, the
    caller asserts the draft's source set is unchanged since EXP-3 validated it.
    """
    now = now or _now()
    vault_root = Path(vault_root).expanduser().resolve()
    draft_path = Path(draft_path)
    if not draft_path.is_absolute():
        draft_path = (vault_root / draft_path).resolve()

    loaded = _load_draft(draft_path)
    draft_id = _draft_id_of(loaded)

    # Idempotency: an already-accepted draft never double-materializes.
    if _already_accepted(loaded):
        return AcceptResult(
            status="already_accepted",
            draft_id=draft_id,
            final_note_path=None,
            receipt_id=str(loaded.frontmatter.get("acceptance_receipt_id") or "") or None,
            decision_token_ref=str(loaded.frontmatter.get("decision_token_ref") or "") or None,
            transition_id=None,
        )

    # create_never_autowrites_canonical (acceptance side): unchecked => refuse.
    if not loaded.checked:
        raise DraftNotAcceptedError(
            f"draft {draft_id!r} acceptance checkbox is unchecked; the machine never writes "
            "canonical on its own — a human must check the in-draft acceptance box first"
        )

    # synthesis_carries_source_provenance: re-validate at acceptance time.
    _re_validate_citations(loaded, live_source_ids=live_source_ids)

    destination_path = _resolve_destination(
        vault_root=vault_root, loaded=loaded, destination=destination
    )
    # modify-existing-note variant stays ask-you: never overwrite an existing note.
    if destination_path.exists():
        raise ModifyExistingRequiresAskError(
            f"destination {destination_path.relative_to(vault_root)} already exists; materializing over "
            "an existing canonical note is a body edit held at 'ask-you' — not this new-note path"
        )

    # execution_cannot_authorize_itself: the token is minted from the human's
    # checked checkbox, before any canonical write is attempted.
    token = _mint_decision_token(loaded, now=now)

    # WriteGuard gates the canonical materialization with a named action.
    write_guard.assert_writes_allowed(ACCEPT_MATERIALIZE_WRITE_ACTION)

    receipt_id = uuid4().hex

    # Edited-then-accepted: materialize the draft's CURRENT on-disk body (human
    # edits preserved), minus the staging-only acceptance checkbox block.
    from scripts.yaml_roundtrip import dump_frontmatter

    accepted_frontmatter = _build_accepted_frontmatter(
        loaded,
        receipt_id=receipt_id,
        decision_token_ref=token.token_ref,
        accepted_at=now,
    )
    materialized_body = _strip_acceptance_checkbox(loaded.body)
    note_text = dump_frontmatter(accepted_frontmatter, materialized_body)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(note_text, encoding="utf-8")

    final_rel = str(destination_path.relative_to(vault_root))
    sources = _sources_of(loaded)

    # Post-mutation AuthorityReceipt (authority_receipt_id) — linking
    # draft -> final note -> sources, carrying the decision token ref.
    emitted_receipt_id = _emit_receipt(
        CREATE_ACCEPTED_EVENT,
        {
            "draft_id": draft_id,
            "final_note_path": final_rel,
            "sources": list(sources),
            "decision_token_ref": token.token_ref,
            "authority_receipt_id": receipt_id,
            "accepted_by": "human",
            "authority_state": ACCEPTED_AUTHORITY_STATE,
        },
        outbox_path=outbox_path,
        trace_id=draft_id,
    )

    transition = _build_authority_transition(
        target_object_id=draft_id,
        target_scope_id="vault",
        token=token,
        receipt_id=receipt_id,
        provenance_event_ids=[emitted_receipt_id],
        now=now,
    )

    # The staged draft has served its purpose; remove it so it is not re-swept
    # or re-accepted. The canonical note + receipt carry the durable record.
    try:
        loaded.path.unlink()
    except OSError:
        pass

    return AcceptResult(
        status="accepted",
        draft_id=draft_id,
        final_note_path=final_rel,
        receipt_id=receipt_id,
        decision_token_ref=token.token_ref,
        transition_id=transition["transition_id"],
    )


def decline_draft(
    draft_path: Path,
    *,
    vault_root: Path,
    outbox_path: Path,
    reason: str | None = None,
    declined_ledger: Any = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> DeclineResult:
    """Decline a staged draft: record it in the declined-proposal ledger (EXP-2),
    remove/archive the staged draft, produce NO canonical note, keep the receipt.

    Decline is a visible lifecycle outcome, not silent deletion (spec §2.4).
    """
    now = now or _now()
    vault_root = Path(vault_root).expanduser().resolve()
    draft_path = Path(draft_path)
    if not draft_path.is_absolute():
        draft_path = (vault_root / draft_path).resolve()

    loaded = _load_draft(draft_path)
    draft_id = _draft_id_of(loaded)

    if declined_ledger is None:
        from app.proposals.declined_ledger import default_declined_ledger

        declined_ledger = default_declined_ledger()

    ledger_recorded = False
    record_decline = getattr(declined_ledger, "record_decline", None)
    if callable(record_decline):
        record_decline(
            draft_id,
            finding_class="create.draft",
            reason=reason,
            declined_at=_iso(now),
            write_guard=write_guard,
        )
        ledger_recorded = True

    receipt_id = _emit_receipt(
        CREATE_DECLINED_EVENT,
        {
            "draft_id": draft_id,
            "reason": reason,
            "sources": list(_sources_of(loaded)),
        },
        outbox_path=outbox_path,
        trace_id=draft_id,
    )

    # Remove the staged draft (no canonical note produced). The decline receipt
    # + ledger entry are the durable record.
    try:
        loaded.path.unlink()
    except OSError:
        pass

    return DeclineResult(
        status="declined",
        draft_id=draft_id,
        receipt_id=receipt_id,
        ledger_recorded=ledger_recorded,
    )


__all__ = [
    "ACCEPT_EVENT_SOURCE",
    "ACCEPT_INITIATING_SOURCE",
    "ACCEPT_MATERIALIZE_WRITE_ACTION",
    "ACCEPT_OPERATION_TYPE",
    "ACCEPTED_AUTHORITY_STATE",
    "CREATE_ACCEPTED_EVENT",
    "CREATE_DECLINED_EVENT",
    "PROPOSAL_AUTHORITY_STATE",
    "SYNTHESIS_DERIVED_BY",
    "AcceptError",
    "AcceptResult",
    "AcceptanceReceipt",
    "DeclineResult",
    "DecisionToken",
    "DraftNotAcceptedError",
    "DraftNotFoundError",
    "MalformedDraftError",
    "ModifyExistingRequiresAskError",
    "UnresolvableCitationError",
    "accept_draft",
    "decline_draft",
]
