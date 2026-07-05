"""#2994 (EXP-1) -- Connect pass: related-unlinked + thematic finding harness.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §1, §5.

Covers every behavioral Acceptance Criterion from the issue:

- AC1: a known unlinked-but-related pair (SV+EN) produces a
  ``connect.related_unlinked`` finding with both note refs, >=1 verbatim span
  per side, and the retrieval basis as a score CLASS (never a raw float).
- AC2: an already-linked pair (direct or 1-hop) is never proposed.
- AC3: a cross-scope pair without an existing ``surface``-operation
  ``CrossScopeFlow`` grant is silently excluded -- content-free, never
  surfaced or logged with identifying content.
- AC4: per-pass caps (per-note, total) hold on a fixture engineered to
  exceed them.
- AC5: rerunning the pass over an unchanged vault is idempotent (no
  duplicate findings / no duplicate checkbox lines).

Uses ``retrieve_fn`` injection (the seam ``run_connect_pass`` exposes) to
supply deterministic ``RetrievalResponse`` fixtures rather than depending on
live BM25/embedding scoring -- one additional test proves the production
``app.retrieval.capability.retrieve`` wiring is actually used by default.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.findings import CONNECT_FINDING_CLASSES, FindingClass, FindingTrack
from app.expansion.connect import (
    ConnectPassConfig,
    CrossScopeFlow,
    run_connect_pass,
)
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
    score: float = 0.9,
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
# AC1: unlinked-but-related SV+EN pair -> connect.related_unlinked
# ---------------------------------------------------------------------------


@pytest.fixture
def sv_en_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root,
        "sv-note.md",
        _panel_note("uuid-sv", "Det handlar om projektplanering och milstolpar i Q3.\n\n"),
    )
    _write_note(
        vault_root,
        "en-note.md",
        _panel_note("uuid-en", "This covers project planning and milestones for Q3.\n\n"),
    )
    return vault_root


def test_related_unlinked_pair_produces_finding_with_both_refs_and_spans(
    sv_en_vault: Path, tmp_path: Path
) -> None:
    hits = [
        _hit(
            "sv-note",
            uuid="uuid-sv",
            text="Det handlar om projektplanering och milstolpar i Q3.",
            source_ref="sv-note.md",
            score=0.91,
        ),
        _hit(
            "en-note",
            uuid="uuid-en",
            text="This covers project planning and milestones for Q3.",
            source_ref="en-note.md",
            score=0.88,
        ),
    ]
    outbox_path = tmp_path / "outbox.jsonl"

    report = run_connect_pass(
        vault_root=sv_en_vault,
        queries=["project planning milestones"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert len(report.findings) == 2  # one CurationFinding per side of the pair
    finding_ids = {f.finding_id for f in report.findings}
    assert len(finding_ids) == 1  # both sides share one logical finding_id

    for finding in report.findings:
        assert finding.finding_class == FindingClass.CONNECT_RELATED_UNLINKED
        assert finding.track == FindingTrack.PROPOSE
        # >= 1 verbatim supporting span per side: this side's own path is
        # evidence[0], every OTHER side's verbatim span follows.
        assert len(finding.evidence) >= 2
        # Retrieval basis is a score CLASS, never a raw float.
        assert "0.9" not in finding.span and "0.88" not in finding.span and "0.91" not in finding.span
        assert any(band in finding.span for band in ("high", "medium", "low"))

    note_uuids = {f.note_uuid for f in report.findings}
    assert note_uuids == {"uuid-sv", "uuid-en"}

    # Verbatim spans are quoted, never translated (spec §1.2): the Swedish
    # source text appears verbatim somewhere in the evidence, not translated.
    all_evidence = " ".join(e for f in report.findings for e in f.evidence)
    assert "projektplanering" in all_evidence  # SV span kept verbatim
    assert "project planning" in all_evidence  # EN span kept verbatim

    # Materialized as an unchecked propose-track checkbox on BOTH notes.
    sv_text = (sv_en_vault / "sv-note.md").read_text(encoding="utf-8")
    en_text = (sv_en_vault / "en-note.md").read_text(encoding="utf-8")
    assert sv_text.count("- [ ]") == 1
    assert en_text.count("- [ ]") == 1
    assert "- [x]" not in sv_text and "- [x]" not in en_text


def test_connect_finding_class_is_in_closed_connect_set() -> None:
    assert FindingClass.CONNECT_RELATED_UNLINKED in CONNECT_FINDING_CLASSES
    assert FindingClass.CONNECT_THEMATIC_LINK in CONNECT_FINDING_CLASSES
    assert FindingClass.CONNECT_CLUSTER_EMERGENCE in CONNECT_FINDING_CLASSES


# ---------------------------------------------------------------------------
# AC2: already-linked pairs (direct + 1-hop) are never proposed
# ---------------------------------------------------------------------------


def test_directly_linked_pair_is_not_proposed(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root, "a.md", _panel_note("uuid-a", "See [[b]] for the related discussion.\n\n")
    )
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "Referenced from a.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("a", uuid="uuid-a", text="shared related content alpha beta", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="shared related content alpha beta", source_ref="b.md"),
    ]

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared related content"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert report.findings == ()


def test_one_hop_linked_pair_is_not_proposed(tmp_path: Path) -> None:
    """A links to X, B links to X -> A and B share a 1-hop path, so the pair
    is excluded even though A and B do not link to each other directly."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "See [[hub]].\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "See [[hub]].\n\n"))
    _write_note(vault_root, "hub.md", _panel_note("uuid-hub", "The hub note.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit("a", uuid="uuid-a", text="shared related content alpha beta", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="shared related content alpha beta", source_ref="b.md"),
    ]

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared related content"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert report.findings == ()


# ---------------------------------------------------------------------------
# AC3: cross-scope candidate without a grant -> silent, content-free exclusion
# ---------------------------------------------------------------------------


def test_cross_scope_pair_without_grant_is_silently_excluded(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "work.md", _panel_note("uuid-work", "Work project notes.\n\n"))
    _write_note(vault_root, "personal.md", _panel_note("uuid-personal", "Personal journal.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit(
            "work",
            uuid="uuid-work",
            text="shared related content alpha beta",
            source_ref="work.md",
            domain="work",
        ),
        _hit(
            "personal",
            uuid="uuid-personal",
            text="shared related content alpha beta",
            source_ref="personal.md",
            domain="personal",
        ),
    ]

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared related content"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    # Never surfaced.
    assert report.findings == ()
    assert report.suppressed_by_cross_scope_denial == 1
    # Content-free: only a denial CLASS/reason string, never note identity,
    # scope name, path, or excerpt.
    for denial in report.denials:
        assert "work" not in denial
        assert "personal" not in denial
        assert "uuid-work" not in denial
        assert "uuid-personal" not in denial
    # No checkbox written to either note.
    work_text = (vault_root / "work.md").read_text(encoding="utf-8")
    personal_text = (vault_root / "personal.md").read_text(encoding="utf-8")
    assert "- [ ]" not in work_text
    assert "- [ ]" not in personal_text


def test_cross_scope_pair_with_surface_grant_is_proposed(tmp_path: Path) -> None:
    """The mirror case: an explicit surface-operation grant DOES let a
    cross-scope pair through -- proving the denial is a real gate, not a
    permanent block."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "work.md", _panel_note("uuid-work", "Work project notes.\n\n"))
    _write_note(vault_root, "personal.md", _panel_note("uuid-personal", "Personal journal.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit(
            "work",
            uuid="uuid-work",
            text="shared related content alpha beta",
            source_ref="work.md",
            domain="work",
        ),
        _hit(
            "personal",
            uuid="uuid-personal",
            text="shared related content alpha beta",
            source_ref="personal.md",
            domain="personal",
        ),
    ]
    grant = CrossScopeFlow(
        source_scope="work", target_scope="personal", allowed_operations=frozenset({"surface"})
    )

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared related content"],
        config=ConnectPassConfig(cross_scope_grants=(grant,)),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    assert len(report.findings) == 2
    assert report.suppressed_by_cross_scope_denial == 0


# ---------------------------------------------------------------------------
# AC4: per-pass caps hold
# ---------------------------------------------------------------------------


def test_per_note_and_total_caps_hold(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # A hub note plus five leaf notes: the hub would pair with all five,
    # exceeding a max_findings_per_note=2 cap on the hub.
    _write_note(vault_root, "hub.md", _panel_note("uuid-hub", "Hub content.\n\n"))
    for i in range(5):
        _write_note(vault_root, f"leaf{i}.md", _panel_note(f"uuid-leaf{i}", f"Leaf {i} content.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [_hit("hub", uuid="uuid-hub", text="shared alpha beta gamma", source_ref="hub.md")]
    for i in range(5):
        hits.append(
            _hit(
                f"leaf{i}",
                uuid=f"uuid-leaf{i}",
                text="shared alpha beta gamma",
                source_ref=f"leaf{i}.md",
                score=0.9 - i * 0.01,
            )
        )

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared alpha beta gamma"],
        config=ConnectPassConfig(max_findings_per_note=2, max_findings_total=25),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    hub_findings = [f for f in report.findings if f.note_uuid == "uuid-hub"]
    assert len(hub_findings) <= 2
    assert report.suppressed_by_cap > 0


def test_total_cap_holds(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    for i in range(6):
        _write_note(vault_root, f"note{i}.md", _panel_note(f"uuid-note{i}", f"Note {i} content.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    hits = [
        _hit(
            f"note{i}",
            uuid=f"uuid-note{i}",
            text="shared alpha beta gamma delta",
            source_ref=f"note{i}.md",
            score=0.9 - i * 0.01,
        )
        for i in range(6)
    ]  # 6 notes -> 15 unique pairs, all mutually unlinked/same-scope

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared alpha beta gamma delta"],
        config=ConnectPassConfig(max_findings_per_note=10, max_findings_total=3),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )

    # 3 logical findings accepted -> 6 CurationFinding records (2 per pair).
    logical_ids = {f.finding_id for f in report.findings}
    assert len(logical_ids) == 3
    assert report.suppressed_by_cap > 0


# ---------------------------------------------------------------------------
# AC5: idempotent rerun over an unchanged vault
# ---------------------------------------------------------------------------


def test_rerun_over_unchanged_vault_is_idempotent(sv_en_vault: Path, tmp_path: Path) -> None:
    hits = [
        _hit(
            "sv-note",
            uuid="uuid-sv",
            text="Det handlar om projektplanering och milstolpar i Q3.",
            source_ref="sv-note.md",
            score=0.91,
        ),
        _hit(
            "en-note",
            uuid="uuid-en",
            text="This covers project planning and milestones for Q3.",
            source_ref="en-note.md",
            score=0.88,
        ),
    ]
    outbox_path = tmp_path / "outbox.jsonl"

    first = run_connect_pass(
        vault_root=sv_en_vault,
        queries=["project planning milestones"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    sv_text_after_first = (sv_en_vault / "sv-note.md").read_text(encoding="utf-8")
    en_text_after_first = (sv_en_vault / "en-note.md").read_text(encoding="utf-8")

    second = run_connect_pass(
        vault_root=sv_en_vault,
        queries=["project planning milestones"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve(hits),
    )
    sv_text_after_second = (sv_en_vault / "sv-note.md").read_text(encoding="utf-8")
    en_text_after_second = (sv_en_vault / "en-note.md").read_text(encoding="utf-8")

    first_ids = {f.finding_id for f in first.findings}
    second_ids = {f.finding_id for f in second.findings}
    assert first_ids == second_ids  # byte-identical ids across reruns

    # No duplicate checkbox lines were appended on the second pass.
    assert sv_text_after_first == sv_text_after_second
    assert en_text_after_first == en_text_after_second
    assert sv_text_after_second.count("- [ ]") == 1
    assert en_text_after_second.count("- [ ]") == 1


# ---------------------------------------------------------------------------
# Production wiring: default retrieve_fn is app.retrieval.capability.retrieve
# ---------------------------------------------------------------------------


def test_default_retrieve_fn_is_the_production_capability() -> None:
    """`run_connect_pass`'s default ``retrieve_fn`` argument is bound to the
    real production retrieval seam (``app.retrieval.capability.retrieve``),
    not a private reimplementation -- the only way this pass may see the
    vault, per the issue constraint ("read candidates through
    app/retrieval/capability.py::retrieve")."""
    import inspect

    from app.retrieval.capability import retrieve as production_retrieve

    sig = inspect.signature(run_connect_pass)
    assert sig.parameters["retrieve_fn"].default is production_retrieve


def test_default_retrieve_fn_resolves_through_live_capability(tmp_path: Path, monkeypatch) -> None:
    """End-to-end (no retrieve_fn override): a note seeded into the live
    hybrid store is reachable via the real retrieve() -> run_connect_pass
    call chain, proving the production wiring path actually works, not just
    that the default argument happens to point at the right function."""
    from app.retrieval.hybrid import get_store

    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1]
    )
    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_docs", lambda texts: ([[0.1, 0.1, 0.1] for _ in texts], {})
    )
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "solo.md", _panel_note("uuid-solo", "Solo note.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    store = get_store()
    store.set_documents([])
    try:
        store.add_document(
            doc_id="solo",
            text="a completely solitary note with no pair candidates",
            source_ref="solo.md",
            payload={"uuid": "uuid-solo"},
        )
        report = run_connect_pass(
            vault_root=vault_root,
            queries=["a completely solitary note"],
            write_guard=_allow_all_guard(),
            outbox_path=outbox_path,
        )
        # A single-note store has no pair to find, but the call must complete
        # through the real retrieve() without error -- proving the wiring.
        assert report.findings == ()
        assert report.notes_scanned == 1
    finally:
        store.set_documents([])
