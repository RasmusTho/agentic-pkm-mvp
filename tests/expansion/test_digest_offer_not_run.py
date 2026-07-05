"""#2998 (EXP-5) -- digest moment-offer wiring point (offer-only, never a run).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2.1,
§5 (EXP-5 second AC); ``docs/MIMER_CAPABILITY_HARDENING/PROACTIVITY_TIERS_AND_QUIET_MODE.md``
(G4).

Covers the issue's second Acceptance Criterion:

- A moment-offer wiring point exists for `create.digest` that can only
  materialize an offer checkbox, never a draft, from tick-style context.

This is a hard invariant, not a default (issue Constraints): "A moment must
never generate a draft directly -- only an offer checkbox." The tests below
prove this at both the unit level (what `build_digest_offer` returns) and the
construction level (the function's own source never reaches
`run_create_pass`), matching the same "prove it at the real call site"
discipline the other Expansion invariants use.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.expansion.create import (
    DIGEST_OFFER_EVENT,
    DigestOffer,
    OutputKind,
    build_digest_offer,
    emit_digest_offer_receipt,
    run_create_pass,
)


def _outbox_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_build_digest_offer_returns_an_inert_offer_not_a_draft() -> None:
    offer = build_digest_offer(period_label="2026-06-29..2026-07-05", moment_id="moment-1")

    assert isinstance(offer, DigestOffer)
    assert offer.period_label == "2026-06-29..2026-07-05"
    assert offer.moment_id == "moment-1"
    assert "Offer" in offer.offer_label
    # No draft-shaped fields exist on the offer at all -- there is nothing to
    # mistake for a generated artifact.
    assert not hasattr(offer, "draft_path")
    assert not hasattr(offer, "sources")


def test_build_digest_offer_requires_a_period_label() -> None:
    with pytest.raises(ValueError):
        build_digest_offer(period_label="")


def test_build_digest_offer_never_calls_run_create_pass() -> None:
    """Construction-level proof: the offer builder's own CODE (not its
    docstring, which explains the invariant in prose) contains no call to
    `run_create_pass` and never constructs a `CreateRequest` -- there is no
    code path inside it that could generate a draft, not just a runtime
    coincidence that it doesn't today."""
    source = inspect.getsource(build_digest_offer)
    _, _, code_only = source.partition('"""')
    _, _, code_only = code_only.partition('"""')  # drop the docstring body
    assert "run_create_pass(" not in code_only
    assert "CreateRequest(" not in code_only


def test_build_digest_offer_signature_accepts_no_sources_or_vault_write_params() -> None:
    """The offer builder's signature has no `sources`, `vault_root`, or
    `write_guard` parameter -- there is no way for a caller to hand it enough
    to materialize a draft even by misuse; the shape itself refuses it."""
    sig = inspect.signature(build_digest_offer)
    forbidden = {"sources", "vault_root", "write_guard", "outbox_path"}
    assert forbidden.isdisjoint(sig.parameters)


def test_offer_receipt_is_distinct_from_the_create_proposed_event(tmp_path: Path) -> None:
    """The offer's receipt event is `expansion.create.digest_offered` --
    never `expansion.create.proposed` (the event only a real `run_create_pass`
    call emits). A test that greps the outbox for the wrong event would give
    a false pass; this asserts the exact, distinct event name."""
    from app.expansion.create import CREATE_PROPOSED_EVENT

    offer = build_digest_offer(period_label="2026-06-29..2026-07-05")
    outbox_path = tmp_path / "outbox.jsonl"
    receipt_id = emit_digest_offer_receipt(offer, outbox_path=outbox_path)

    assert receipt_id
    records = _outbox_records(outbox_path)
    assert len(records) == 1
    assert records[0]["event"] == DIGEST_OFFER_EVENT
    assert records[0]["event"] != CREATE_PROPOSED_EVENT
    assert records[0]["payload"]["period_label"] == "2026-06-29..2026-07-05"


def test_offering_a_digest_writes_no_draft_file(tmp_path: Path) -> None:
    """End-to-end production-call-site proof: offering (and receipting) a
    digest, with no subsequent explicit `run_create_pass` call, leaves the
    vault with zero new files anywhere -- offering truly performs no vault
    write of any kind."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    before = set(vault_root.rglob("*"))
    offer = build_digest_offer(period_label="2026-06-29..2026-07-05", moment_id="moment-42")
    emit_digest_offer_receipt(offer, outbox_path=outbox_path)
    after = set(vault_root.rglob("*"))

    assert before == after  # no vault file was created by offering alone


def test_explicit_ask_digest_still_reaches_run_create_pass_unaffected(tmp_path: Path) -> None:
    """The offer-only constraint governs the MOMENT path only -- an explicit
    human ask for a digest (the same `run_create_pass` call every other kind
    uses) is unaffected and still produces a real staged draft. This is the
    sibling proof that offer-only does not regress the explicit-ask path."""
    from app.expansion.create import CreateRequest, DigestActivityInput, SourceInput
    from app.write_guard import WriteGuard

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})

    sources = (
        SourceInput(object_id="obj-a", note_path="a.md", text="Some text.", quoted_spans=("Some text.",)),
    )
    request = CreateRequest(
        kind=OutputKind.DIGEST,
        title="Weekly digest",
        sources=sources,
        digest_activity=DigestActivityInput(period_label="week-1", moved=("a.md",)),
    )
    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=guard)

    assert report.activatable is True
    assert report.draft_path is not None
