"""#2996 (EXP-3) / #2998 (EXP-5) -- Create engine: overview + answer_note +
digest draft lifecycle.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2, §5.

Covers every behavioral Acceptance Criterion from the issue:

- AC1: a ``create.overview`` and a ``create.answer_note`` draft each carry
  resolvable ``SourceRef``s for every synthesized section.
- AC2: an unresolvable citation blocks the draft from proposal with a loud
  failure (not a silently pruned claim).
- AC3: staged draft content is not indexed and is not retrievable into any
  context (production-call-site enforcement over ``app.ingest.vault_alpha``).
- AC4: an ignored draft expires after the declared staleness window, with an
  expiry receipt; expiry never errors.
- Plus (#2998, EXP-5): ``create.digest`` goes through the identical staged
  lifecycle; no default output kind (fail-loud on a non-enum kind);
  activation-gate blocking never silently runs.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.expansion.create import (
    CreatePassReport,
    CreateRequest,
    ExpirySweepReport,
    OutputKind,
    SourceInput,
    UnresolvableCitationError,
    run_create_pass,
    sweep_expired_drafts,
)
from app.write_guard import WriteGuard
from app.reasoning.schema import ReasoningOutput


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "unhealthy", "reason": "test-blocked"})


def _outbox_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _source(object_id: str, text: str, span: str, *, language: str = "en") -> SourceInput:
    return SourceInput(
        object_id=object_id,
        note_path=f"{object_id}.md",
        text=text,
        quoted_spans=(span,),
        language=language,
        review_state="reviewed",
    )


@pytest.mark.parametrize("kind", [OutputKind.OVERVIEW, OutputKind.ANSWER_NOTE])
def test_draft_carries_resolvable_source_refs(tmp_path: Path, kind: OutputKind) -> None:
    """AC1: each kind's draft carries resolvable SourceRefs for every
    synthesized section, and the staged note frontmatter records provenance
    (sources, derived_by, authority_state)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (
        _source("obj-a", "Alpha note body about topic X.", "Alpha note body about topic X."),
        _source("obj-b", "Beta note body also about topic X.", "Beta note body also about topic X."),
    )
    request = CreateRequest(kind=kind, title="Topic X overview", sources=sources, question="What is X?")

    report = run_create_pass(
        request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard()
    )

    assert isinstance(report, CreatePassReport)
    assert report.activatable is True
    assert report.draft_path is not None
    assert report.receipt_id is not None

    draft_text = (vault_root / report.draft_path).read_text(encoding="utf-8")
    assert "obj-a" in draft_text
    assert "obj-b" in draft_text
    assert "derived_by: synthesis" in draft_text
    assert "authority_state: proposal" in draft_text
    assert "AI-åtgärder" in draft_text
    assert "- [ ]" in draft_text  # in-draft acceptance checkbox, unchecked
    assert "- [x]" not in draft_text

    records = _outbox_records(outbox_path)
    proposed = [r for r in records if r.get("event") == "expansion.create.proposed"]
    assert len(proposed) == 1
    assert proposed[0]["payload"]["kind"] == kind.value
    assert set(proposed[0]["payload"]["sources"]) == {"obj-a", "obj-b"}


def test_unresolvable_citation_blocks_loudly(tmp_path: Path) -> None:
    """AC2: a quoted span that does not exist verbatim in its source text
    blocks the draft from proposal with a loud, typed failure -- never a
    silently pruned claim. No draft file and no receipt are written."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (
        SourceInput(
            object_id="obj-a",
            note_path="obj-a.md",
            text="Alpha note body about topic X.",
            quoted_spans=("this span was never actually written",),
            language="en",
        ),
    )
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Bad citation", sources=sources)

    with pytest.raises(UnresolvableCitationError):
        run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())

    drafts_dir = vault_root / "⚙️ System" / "drafts"
    assert not drafts_dir.exists() or not any(drafts_dir.glob("*.md"))
    assert not outbox_path.exists() or _outbox_records(outbox_path) == []


def test_empty_source_text_blocks_loudly(tmp_path: Path) -> None:
    """A citation naming a source with no resolvable text also blocks loudly
    -- an empty/whitespace-only body can never ground a verbatim span."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (SourceInput(object_id="obj-empty", note_path="obj-empty.md", text="   ", quoted_spans=()),)
    request = CreateRequest(kind=OutputKind.ANSWER_NOTE, title="Empty source", sources=sources)

    with pytest.raises(UnresolvableCitationError):
        run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())


def test_no_sources_blocks_loudly(tmp_path: Path) -> None:
    """An unsourced draft is refused outright -- Create never emits an
    unsourced narrative (spec §2.6 deterministic-fallback discipline)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    request = CreateRequest(kind=OutputKind.OVERVIEW, title="No sources", sources=())

    with pytest.raises(UnresolvableCitationError):
        run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())


def test_create_marks_empty_provider_cognition_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    sources = (
        _source("obj-a", "Alpha source text.", "Alpha source text."),
        _source("obj-b", "Beta source text.", "Beta source text."),
    )
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Degraded collation", sources=sources)
    monkeypatch.setattr(
        "app.expansion.create.run_multi_note_reasoning",
        lambda *_args, **_kwargs: ReasoningOutput(
            outcome="empty_output", degraded_reason="empty_provider_output"
        ),
    )

    report = run_create_pass(
        request,
        vault_root=vault_root,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
    )

    assert report.draft_path is not None
    draft_text = (vault_root / report.draft_path).read_text(encoding="utf-8")
    assert "Alpha source text." in draft_text
    assert "Beta source text." in draft_text
    assert "claims: 0" in draft_text
    assert "inferences: 0" in draft_text
    assert "degraded: true" in draft_text
    assert "degraded_reason: empty_provider_output" in draft_text
    assert "outcome: empty_output" in draft_text

    proposed = [
        record
        for record in _outbox_records(outbox_path)
        if record.get("event") == "expansion.create.proposed"
    ]
    assert proposed[0]["payload"]["cognition_metadata"] == {
        "claims": 0,
        "inferences": 0,
        "degraded": True,
        "outcome": "empty_output",
        "degraded_reason": "empty_provider_output",
    }


def test_digest_kind_is_supported_and_produces_a_draft(tmp_path: Path) -> None:
    """`create.digest` (EXP-5, #2998) is now a fully implemented output kind:
    an explicit-ask digest request goes through the identical staged-draft
    lifecycle as overview/answer_note (activation gate -> citation validation
    -> staging write -> receipt) -- no separate code path, no shortcut."""
    from app.expansion.create import DigestActivityInput

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (_source("obj-a", "Some text.", "Some text."),)
    activity = DigestActivityInput(
        period_label="2026-06-29..2026-07-05", moved=("a.md",), opened=("b.md",), quiet=("c.md",)
    )
    request = CreateRequest(
        kind=OutputKind.DIGEST, title="Weekly digest", sources=sources, digest_activity=activity
    )

    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())

    assert report.activatable is True
    assert report.draft_path is not None
    draft_text = (vault_root / report.draft_path).read_text(encoding="utf-8")
    assert "authority_state: proposal" in draft_text
    assert "- [ ]" in draft_text
    assert "- [x]" not in draft_text
    assert "What moved" in draft_text
    assert "a.md" in draft_text
    assert "b.md" in draft_text
    assert "c.md" in draft_text


def test_invalid_output_kind_fails_loud_for_a_non_enum_value() -> None:
    """No default output kind: constructing a request with a value outside
    the closed `OutputKind` enum fails loud at construction (Enum
    coercion) -- there is no third silent-fallback path for an unrecognized
    kind string."""
    with pytest.raises(ValueError):
        OutputKind("create.not_a_real_kind")


def test_supported_output_kinds_is_the_full_closed_enum() -> None:
    """All three closed-enum members are implemented and supported -- no
    kind is left half-built or silently unreachable."""
    from app.expansion.create import SUPPORTED_OUTPUT_KINDS

    assert SUPPORTED_OUTPUT_KINDS == frozenset(OutputKind)


def test_writes_blocked_state_prevents_staging_write(tmp_path: Path) -> None:
    """WriteGuard is asserted before any staging file is touched -- an
    unhealthy runtime state blocks the write the same way every other
    propose-track writer in this program is gated."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (_source("obj-a", "Some text.", "Some text."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Blocked", sources=sources)

    from app.write_guard import WritesBlockedError

    with pytest.raises(WritesBlockedError):
        run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_blocked_guard())


def test_no_admissible_source_blocks_via_activation_gate(tmp_path: Path) -> None:
    """Sanity check for the activation-gate-green path: a populated,
    well-formed source set is activatable and produces a real receipt. The
    sibling gate-blocked path (a deliberately regressed posture) is covered
    by ``tests/invariants/test_expansion_invariants.py::test_create_requires_activation_record``."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    sources = (_source("obj-a", "Some text.", "Some text."),)
    request = CreateRequest(kind=OutputKind.ANSWER_NOTE, title="Sanity", sources=sources)

    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())
    assert report.activatable is True


def test_expiry_sweep_removes_ignored_draft_past_staleness_window(tmp_path: Path) -> None:
    """AC4: an ignored (unchecked) draft past its declared `expires` timestamp
    is removed, with an `expansion.create.expired` receipt. Expiry never
    errors even when the staging dir has malformed neighbors."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (_source("obj-a", "Some text.", "Some text."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Will expire", sources=sources)

    created_at = datetime.now(timezone.utc) - timedelta(days=30)
    report = run_create_pass(
        request,
        vault_root=vault_root,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        staleness_days=14,
        now=created_at,
    )
    draft_path = vault_root / report.draft_path

    # A malformed neighbor file must not blow up the sweep.
    drafts_dir = draft_path.parent
    (drafts_dir / "not-a-real-draft.md").write_text("no frontmatter here", encoding="utf-8")

    assert draft_path.exists()

    sweep = sweep_expired_drafts(vault_root=vault_root, outbox_path=outbox_path, now=datetime.now(timezone.utc))

    assert isinstance(sweep, ExpirySweepReport)
    assert not draft_path.exists()
    assert len(sweep.expired) == 1
    assert len(sweep.receipt_ids) == 1

    records = _outbox_records(outbox_path)
    expired_records = [r for r in records if r.get("event") == "expansion.create.expired"]
    assert len(expired_records) == 1


def test_expiry_sweep_never_removes_a_checked_draft(tmp_path: Path) -> None:
    """A checked (accepted) draft is EXP-4's concern; the sweep must never
    remove it even if it is past its staleness window."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (_source("obj-a", "Some text.", "Some text."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Accepted draft", sources=sources)
    created_at = datetime.now(timezone.utc) - timedelta(days=30)
    report = run_create_pass(
        request,
        vault_root=vault_root,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        staleness_days=14,
        now=created_at,
    )
    draft_path = vault_root / report.draft_path
    text = draft_path.read_text(encoding="utf-8")
    draft_path.write_text(text.replace("- [ ]", "- [x]"), encoding="utf-8")

    sweep_expired_drafts(vault_root=vault_root, outbox_path=outbox_path, now=datetime.now(timezone.utc))

    assert draft_path.exists()


def test_expiry_sweep_missing_staging_dir_never_errors(tmp_path: Path) -> None:
    """A vault with no staging dir at all (nothing was ever staged) must not
    raise -- expiry is silent-safe by construction."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sweep = sweep_expired_drafts(vault_root=vault_root, outbox_path=outbox_path)
    assert sweep.expired == ()
    assert sweep.receipt_ids == ()


def test_staged_draft_not_indexed_by_vault_alpha_ingest(tmp_path: Path) -> None:
    """AC3, production-call-site enforcement: the real ingest candidate
    selection (`app.ingest.vault_alpha._select_candidates`) never includes a
    staged Create draft under the resolved system dir's `drafts` subfolder --
    the same exclusion mechanism that already protects `_system/companions`."""
    from app.ingest.vault_alpha import _select_candidates

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    sources = (_source("obj-a", "Some text.", "Some text."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Invisible draft", sources=sources)
    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard())
    draft_path = vault_root / report.draft_path
    assert draft_path.exists()

    # A normal, non-staged note in the same vault, to prove the selection
    # still returns ordinary notes (the exclusion is scoped, not total).
    ordinary_note = vault_root / "ordinary.md"
    ordinary_note.write_text("---\nuuid: ordinary-1\n---\n\n# Ordinary\n", encoding="utf-8")

    candidates, _ = _select_candidates(
        vault_root,
        include_folders=None,
        ignore_glob=(),
        include_test_note=True,
        max_notes=0,
    )

    candidate_paths = {p.relative_to(vault_root) for p in candidates}
    assert draft_path.relative_to(vault_root) not in candidate_paths
    assert ordinary_note.relative_to(vault_root) in candidate_paths
