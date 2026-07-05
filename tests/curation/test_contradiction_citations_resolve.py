"""#2999 (G2-4) -- Contradiction pass: retrieval-grounded claim-conflict harness.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4, §6.

Covers every behavioral Acceptance Criterion from the issue:

- AC1: a fixture vault with two notes making conflicting claims produces a
  ``contradiction.claim_conflict`` finding with both claims verbatim and >=2
  resolvable source links.
- AC2: an unresolvable citation voids the finding rather than materializing an
  uncited callout -- blocked loudly (raises), never silently emitted or
  silently dropped without trace.
- AC4: a declined contradiction finding is suppressed on rerun via the
  declined-proposal ledger (``test_declined_contradiction_suppressed``).

The ``[!contradiction]``-callout-never-during-the-pass AC (AC3) is covered
separately in ``tests/curation/test_semantic_never_autowrites.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.contradiction import (
    ContradictionPassConfig,
    UnresolvableContradictionCitationError,
    run_contradiction_pass,
)
from app.curation.findings import FindingClass, FindingTrack
from app.expansion.connect import CrossScopeFlow
from app.proposals.declined_ledger import DeclinedLedger
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse
from app.write_guard import WriteGuard


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _panel_note(uuid: str, extra_body: str = "") -> str:
    return (
        f"---\nuuid: {uuid}\nkind: note\n---\n\n"
        f"# {uuid}\n\n{extra_body}"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "\n"
        "## AI-åtgärder\n"
        "%% AI:End %%\n"
    )


def _write_note(vault_root: Path, rel_path: str, content: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _hit(
    doc_id: str,
    *,
    uuid: str,
    text: str,
    source_ref: str,
    domain: str | None = None,
    score: float = 0.8,
) -> RetrievalHit:
    payload: dict = {"uuid": uuid}
    if domain is not None:
        payload["domain"] = domain
    return RetrievalHit(
        object_id=doc_id,
        doc_id=doc_id,
        text=text,
        score=score,
        snippet=text,
        source_ref=source_ref,
        payload=payload,
    )


def _fake_retrieve(hits: list[RetrievalHit]):
    def _inner(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(query=request.query, hits=list(hits), trace_id=request.trace_id)

    return _inner


# ---------------------------------------------------------------------------
# AC1: conflicting claims -> contradiction.claim_conflict finding, both claims
# verbatim, >=2 resolvable source links
# ---------------------------------------------------------------------------


@pytest.fixture
def conflicting_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root,
        "meeting-a.md",
        _panel_note("uuid-a", "Mötet är på tisdagar kl 10.\n\n"),
    )
    _write_note(
        vault_root,
        "meeting-b.md",
        _panel_note("uuid-b", "The meeting is on Wednesdays at 10am.\n\n"),
    )
    return vault_root


def test_conflicting_claims_produce_finding_with_verbatim_claims_and_two_sources(
    conflicting_vault: Path, tmp_path: Path
) -> None:
    hits = [
        _hit(
            "meeting-a",
            uuid="uuid-a",
            text="Mötet är på tisdagar kl 10.",
            source_ref="meeting-a.md",
            score=0.8,
        ),
        _hit(
            "meeting-b",
            uuid="uuid-b",
            text="The meeting is on Wednesdays at 10am.",
            source_ref="meeting-b.md",
            score=0.75,
        ),
    ]
    outbox_path = tmp_path / "outbox.jsonl"

    report = run_contradiction_pass(
        vault_root=conflicting_vault,
        queries=["when is the meeting"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert len(report.findings) == 2  # one CurationFinding per side
    finding_ids = {f.finding_id for f in report.findings}
    assert len(finding_ids) == 1  # both sides share one logical finding_id

    for finding in report.findings:
        assert finding.finding_class == FindingClass.CONTRADICTION_CLAIM_CONFLICT
        assert finding.track == FindingTrack.PROPOSE
        # >= 2 resolvable source links per finding.
        assert len(finding.evidence) >= 2
        # Both claims verbatim in `observed`.
        assert "Mötet är på tisdagar kl 10." in finding.observed
        assert "The meeting is on Wednesdays at 10am." in finding.observed
        # One-line agent interpretation present, never a verdict on which is right.
        assert "interpretation" in finding.span.lower()
        assert "correct" not in finding.span.lower() or "does not adjudicate" in finding.span.lower()

    note_uuids = {f.note_uuid for f in report.findings}
    assert note_uuids == {"uuid-a", "uuid-b"}

    # Materialized as an unchecked propose-track checkbox on BOTH notes with a
    # self-contained Swedish-language label (spec §4 example format).
    a_text = (conflicting_vault / "meeting-a.md").read_text(encoding="utf-8")
    b_text = (conflicting_vault / "meeting-b.md").read_text(encoding="utf-8")
    assert a_text.count("- [ ]") == 1
    assert b_text.count("- [ ]") == 1
    assert "- [x]" not in a_text and "- [x]" not in b_text
    assert "Motstridigt" in a_text  # Swedish label per spec example
    assert "[!contradiction]" not in a_text  # callout never written by the pass
    assert "[!contradiction]" not in b_text


def test_contradiction_finding_class_already_in_closed_enum() -> None:
    """The class must already exist in E1's closed enum (issue constraint: do
    not add a new enum value if it already exists)."""
    assert FindingClass.CONTRADICTION_CLAIM_CONFLICT.value == "contradiction.claim_conflict"


def test_identical_claims_are_not_a_contradiction(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "Samma påstående.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "Samma påstående.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("a", uuid="uuid-a", text="Samma påstående.", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="Samma påstående.", source_ref="b.md"),
    ]

    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=["samma påstående"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert report.findings == ()


# ---------------------------------------------------------------------------
# AC2: unresolvable citation voids the finding, loudly -- never silently
# emitted, never silently dropped without a trace
# ---------------------------------------------------------------------------


def test_unresolvable_citation_raises_and_never_materializes(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # Only note A actually exists on disk; note B's referenced file is absent,
    # so its citation cannot resolve.
    _write_note(vault_root, "meeting-a.md", _panel_note("uuid-a", "Mötet är på tisdagar.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("meeting-a", uuid="uuid-a", text="Mötet är på tisdagar.", source_ref="meeting-a.md"),
        _hit(
            "meeting-b",
            uuid="uuid-b",
            text="The meeting is on Wednesdays.",
            source_ref="meeting-b-missing.md",  # never written to vault_root
        ),
    ]

    with pytest.raises(UnresolvableContradictionCitationError):
        run_contradiction_pass(
            vault_root=vault_root,
            queries=["when is the meeting"],
            write_guard=_allow_all_guard(),
            outbox_path=outbox_path,
            retrieve_fn=_fake_retrieve(hits),
        )

    # No checkbox was written anywhere -- the finding never materialized.
    a_text = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    assert "- [ ]" not in a_text


# ---------------------------------------------------------------------------
# Scope discipline: cross-scope candidates only surface under an existing
# `surface` CrossScopeFlow grant (mirrors app.expansion.connect exactly)
# ---------------------------------------------------------------------------


def test_cross_scope_pair_without_grant_is_silently_excluded(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "work.md", _panel_note("uuid-work", "Deadline is Friday.\n\n"))
    _write_note(vault_root, "personal.md", _panel_note("uuid-personal", "Deadline is Monday.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit(
            "work", uuid="uuid-work", text="Deadline is Friday.", source_ref="work.md", domain="work"
        ),
        _hit(
            "personal",
            uuid="uuid-personal",
            text="Deadline is Monday.",
            source_ref="personal.md",
            domain="personal",
        ),
    ]

    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=["deadline"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert report.findings == ()
    assert report.suppressed_by_cross_scope_denial == 1
    for denial in report.denials:
        assert "work" not in denial
        assert "personal" not in denial
    work_text = (vault_root / "work.md").read_text(encoding="utf-8")
    personal_text = (vault_root / "personal.md").read_text(encoding="utf-8")
    assert "- [ ]" not in work_text
    assert "- [ ]" not in personal_text


def test_cross_scope_pair_with_surface_grant_is_proposed(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "work.md", _panel_note("uuid-work", "Deadline is Friday.\n\n"))
    _write_note(vault_root, "personal.md", _panel_note("uuid-personal", "Deadline is Monday.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit(
            "work", uuid="uuid-work", text="Deadline is Friday.", source_ref="work.md", domain="work"
        ),
        _hit(
            "personal",
            uuid="uuid-personal",
            text="Deadline is Monday.",
            source_ref="personal.md",
            domain="personal",
        ),
    ]
    grant = CrossScopeFlow(
        source_scope="work", target_scope="personal", allowed_operations=frozenset({"surface"})
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=["deadline"],
        config=ContradictionPassConfig(cross_scope_grants=(grant,)),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert len(report.findings) == 2
    assert report.suppressed_by_cross_scope_denial == 0


# ---------------------------------------------------------------------------
# AC4: a declined contradiction finding is suppressed on rerun via the ledger
# ---------------------------------------------------------------------------


def test_declined_contradiction_suppressed(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "meeting-a.md", _panel_note("uuid-a", "Mötet är på tisdagar.\n\n"))
    _write_note(vault_root, "meeting-b.md", _panel_note("uuid-b", "The meeting is on Wednesdays.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"
    guard = _allow_all_guard()
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    config = ContradictionPassConfig(declined_ledger=ledger)

    hits = [
        _hit("meeting-a", uuid="uuid-a", text="Mötet är på tisdagar.", source_ref="meeting-a.md"),
        _hit(
            "meeting-b",
            uuid="uuid-b",
            text="The meeting is on Wednesdays.",
            source_ref="meeting-b.md",
        ),
    ]

    first = run_contradiction_pass(
        vault_root=vault_root,
        queries=["when is the meeting"],
        config=config,
        write_guard=guard,
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    assert first.findings
    finding_id = first.findings[0].finding_id
    ledger.record_decline(
        finding_id, finding_class="contradiction.claim_conflict", write_guard=guard
    )

    second = run_contradiction_pass(
        vault_root=vault_root,
        queries=["when is the meeting"],
        config=config,
        write_guard=guard,
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    assert second.findings == ()
    assert second.suppressed_by_decline == 1

    # No new checkbox was appended for the declined finding on rerun.
    a_text = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    assert a_text.count("- [ ]") == 1  # only the first pass's checkbox


# ---------------------------------------------------------------------------
# Idempotency: rerunning over an unchanged vault is a no-op
# ---------------------------------------------------------------------------


def test_rerun_over_unchanged_vault_is_idempotent(conflicting_vault: Path, tmp_path: Path) -> None:
    hits = [
        _hit(
            "meeting-a",
            uuid="uuid-a",
            text="Mötet är på tisdagar kl 10.",
            source_ref="meeting-a.md",
            score=0.8,
        ),
        _hit(
            "meeting-b",
            uuid="uuid-b",
            text="The meeting is on Wednesdays at 10am.",
            source_ref="meeting-b.md",
            score=0.75,
        ),
    ]
    outbox_path = tmp_path / "outbox.jsonl"

    first = run_contradiction_pass(
        vault_root=conflicting_vault,
        queries=["when is the meeting"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    a_after_first = (conflicting_vault / "meeting-a.md").read_text(encoding="utf-8")

    second = run_contradiction_pass(
        vault_root=conflicting_vault,
        queries=["when is the meeting"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    a_after_second = (conflicting_vault / "meeting-a.md").read_text(encoding="utf-8")

    first_ids = {f.finding_id for f in first.findings}
    second_ids = {f.finding_id for f in second.findings}
    assert first_ids == second_ids
    assert a_after_first == a_after_second
    assert a_after_second.count("- [ ]") == 1


# ---------------------------------------------------------------------------
# Production wiring: default retrieve_fn is app.retrieval.capability.retrieve
# ---------------------------------------------------------------------------


def test_default_retrieve_fn_is_the_production_capability() -> None:
    import inspect

    from app.retrieval.capability import retrieve as production_retrieve

    sig = inspect.signature(run_contradiction_pass)
    assert sig.parameters["retrieve_fn"].default is production_retrieve
