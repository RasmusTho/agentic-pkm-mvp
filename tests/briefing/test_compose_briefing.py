from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.briefing import (
    BriefingReadError,
    compose_briefing,
    load_briefing,
)
from app.domain.commitments import CommitmentRecord
from app.relevance.schema import (
    Moment,
    MomentNeed,
    MomentProvenance,
    MomentTrigger,
    MomentUrgency,
    SurfacedRef,
)
from app.services.commitment_persistence import persist_commitment
from app.vault.manager import VaultContext
from app.vault.markdown_settings import render_markdown_settings
from app.write_guard import WriteGuard, WritesBlockedError


BRIEFING_DATE = date(2026, 7, 10)


def _context(vault_root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="test-vault",
        active_vault_name="Test Vault",
        active_vault_path=str(vault_root),
    )


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, VaultContext]:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")
    return root, _context(root)


def _seed_commitment(
    context: VaultContext,
    commitment_id: str,
    *,
    kind: str,
    state: str,
    target_ref: str | None = None,
) -> None:
    persist_commitment(
        CommitmentRecord(
            commitment_id=commitment_id,
            commitment_kind=kind,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            target_ref=target_ref,
            summary=f"Summary {commitment_id}",
        ),
        vault_context=context,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )


def _seed_moment(
    root: Path,
    moment_id: str,
    *,
    refs: list[SurfacedRef] | None = None,
) -> Path:
    moment = Moment(
        uuid=moment_id,
        created="2026-07-09T17:00:00Z",
        trigger=MomentTrigger(kind="test"),
        need=MomentNeed(basis="reorientation", summary=f"Moment {moment_id}"),
        surfaced_refs=refs or [],
        urgency=MomentUrgency(band="timely", basis="test", evaluator="test"),
        provenance=MomentProvenance(produced_by="test", inputs_digest="abc"),
    )
    path = root / "_system" / "moments" / f"{moment_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_markdown_settings(moment.to_frontmatter(), moment.to_markdown_body()),
        encoding="utf-8",
    )
    return path


def _seed_receipts(root: Path, records: list[dict[str, object]]) -> Path:
    path = root / "_system" / "receipts" / "decisions" / "decisions-202607.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _receipt(
    object_id: str,
    created_at: str,
    *,
    key: str = "review",
    vault_uuid: str | None = "vault-uuid",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "object_id": object_id,
        "vault_uuid": vault_uuid,
        "key": key,
        "value": {"secret_body": "must not render"},
        "created_at": created_at,
    }


def _target(root: Path) -> Path:
    return root / "_system" / "briefings" / "2026-07-10.md"


def test_composes_full_briefing_with_provenance(
    vault: tuple[Path, VaultContext],
) -> None:
    root, context = vault
    _seed_commitment(context, "next-1", kind="next_action", state="next", target_ref="Projects/A.md")
    _seed_commitment(context, "review-1", kind="review_return", state="open")
    _seed_moment(root, "moment-1", refs=[SurfacedRef(ref="Notes/B.md", why="relevant")])
    _seed_receipts(root, [_receipt("object-1", "2026-07-09T11:30:00+00:00")])
    source_paths = [path for path in root.rglob("*") if path.is_file()]
    before = {path: path.read_bytes() for path in source_paths}

    receipt = compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)

    assert receipt.operation == "write_note"
    assert receipt.locator.path == "_system/briefings/2026-07-10.md"
    assert note is not None
    assert note.degraded_sections == ()
    assert [item.commitment_id for item in note.sections["commitments"].items] == [
        "next-1",
        "review-1",
    ]
    assert note.sections["commitments"].items[0].artifact_path.endswith("commitments/next-1.md")
    assert note.sections["moments"].items[0].artifact_path == "_system/moments/moment-1.md"
    assert note.sections["decision_receipts"].items[0].receipt_path.endswith(
        "receipts/decisions/decisions-202607.jsonl"
    )
    assert {path: path.read_bytes() for path in source_paths} == before


def test_briefing_write_asserts_guard_at_seam(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    guard = WriteGuard(lambda: {"state": "safe_mode", "reason": "test"})

    with pytest.raises(WritesBlockedError) as exc_info:
        compose_briefing(vault_context=context, for_date=BRIEFING_DATE, write_guard=guard)

    assert exc_info.value.action == "briefing.write_note"
    assert not _target(root).exists()
    assert not (root / "_system" / "briefings").exists()


@pytest.mark.parametrize(
    ("reader_name", "section_name"),
    [
        ("load_commitments", "commitments"),
        ("collect_now_moments", "moments"),
        ("iter_decision_receipts", "decision_receipts"),
    ],
)
def test_partial_source_failure_names_missing_section(
    vault: tuple[Path, VaultContext],
    monkeypatch: pytest.MonkeyPatch,
    reader_name: str,
    section_name: str,
) -> None:
    from app.briefing import compose as compose_module

    root, context = vault
    _seed_commitment(context, "next-1", kind="next_action", state="next")
    _seed_moment(root, "moment-1")
    _seed_receipts(root, [_receipt("object-1", "2026-07-09T12:00:00Z")])

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("sensitive exception text")

    monkeypatch.setattr(compose_module, reader_name, fail)
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)

    assert note is not None
    assert note.degraded_sections == (section_name,)
    assert note.sections[section_name].status == "degraded"
    assert note.sections[section_name].items == ()
    assert all(
        note.sections[name].items
        for name in ("commitments", "moments", "decision_receipts")
        if name != section_name
    )
    text = _target(root).read_text(encoding="utf-8")
    assert "This section could not be generated (source_read_failed)." in text
    assert "sensitive exception text" not in text


def test_every_item_carries_provenance_ref(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    _seed_commitment(context, "without-target", kind="next_action", state="next")
    _seed_moment(root, "without-refs")
    _seed_receipts(
        root,
        [_receipt("without-uuid", "2026-07-09T04:30:00Z", vault_uuid=None)],
    )

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None

    commitment = note.sections["commitments"].items[0]
    assert commitment.artifact_path == "_system/commitments/without-target.md"
    assert commitment.target_ref is None
    moment = note.sections["moments"].items[0]
    assert moment.artifact_path == "_system/moments/without-refs.md"
    assert moment.surfaced_refs == ()
    decision = note.sections["decision_receipts"].items[0]
    assert decision.object_id == "without-uuid"
    assert decision.vault_uuid is None
    assert decision.receipt_path == "_system/receipts/decisions/decisions-202607.jsonl"


def test_compose_is_deterministic_for_same_inputs_same_day(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.briefing import compose as compose_module

    root, context = vault
    commitments = [
        CommitmentRecord("b", "waiting", "waiting", summary="line\n two"),
        CommitmentRecord("a", "next_action", "next", summary="A"),
    ]
    moments = [
        {
            "moment_id": "z",
            "title": "Z",
            "need_basis": "reorientation",
            "urgency_band": "timely",
            "surfaced_refs": [],
        },
        {
            "moment_id": "a",
            "title": "A",
            "need_basis": "reorientation",
            "urgency_band": "routine",
            "surfaced_refs": [],
        },
    ]
    receipts = [
        _receipt("b", "2026-07-09T23:00:00+00:00"),
        _receipt("a", "2026-07-09T01:00:00+00:00"),
    ]
    monkeypatch.setattr(compose_module, "load_commitments", lambda **_: list(reversed(commitments)))
    monkeypatch.setattr(compose_module, "collect_now_moments", lambda *_args, **_kwargs: list(reversed(moments)))
    monkeypatch.setattr(compose_module, "iter_decision_receipts", lambda *_: list(reversed(receipts)))
    guard = WriteGuard(lambda: {"state": "healthy"})

    compose_briefing(vault_context=context, for_date=BRIEFING_DATE, write_guard=guard)
    first = _target(root).read_bytes()
    _target(root).unlink()
    compose_briefing(vault_context=context, for_date=BRIEFING_DATE, write_guard=guard)
    second = _target(root).read_bytes()

    assert first == second
    text = first.decode()
    assert "secret_body" not in text
    assert "generated_at" not in text
    assert ".tmp" not in text


def test_review_return_is_included_once(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    _seed_commitment(context, "review-next", kind="review_return", state="next")
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert [item.commitment_id for item in note.sections["commitments"].items] == ["review-next"]


def test_empty_sources_are_available_not_degraded(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert note.degraded_sections == ()
    assert all(section.status == "available" for section in note.sections.values())
    assert _target(root).read_text(encoding="utf-8").count("No items.") == 3


def test_receipt_window_is_half_open_previous_utc_day(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    _seed_receipts(
        root,
        [
            _receipt("before", "2026-07-08T23:59:59Z"),
            _receipt("start", "2026-07-09T00:00:00-00:00"),
            _receipt("end", "2026-07-10T00:00:00Z"),
        ],
    )
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert [item.object_id for item in note.sections["decision_receipts"].items] == ["start"]
    assert note.sections["decision_receipts"].items[0].created_at == "2026-07-09T00:00:00Z"


def test_invalid_returned_item_degrades_whole_section(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.briefing import compose as compose_module

    _root, context = vault
    monkeypatch.setattr(
        compose_module,
        "collect_now_moments",
        lambda *_args, **_kwargs: [{"moment_id": "missing-required-fields"}],
    )
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert note.degraded_sections == ("moments",)
    assert note.sections["moments"].reason == "invalid_source_record"


def test_invalid_receipt_timestamp_degrades_receipt_section(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.briefing import compose as compose_module

    _root, context = vault
    monkeypatch.setattr(
        compose_module,
        "iter_decision_receipts",
        lambda *_: [_receipt("bad", "not-a-timestamp")],
    )
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert note.degraded_sections == ("decision_receipts",)


def test_atomic_replace_failure_preserves_prior_note(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.briefing.compose as compose_module

    root, context = vault
    target = _target(root)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"prior complete note")

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(compose_module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        compose_briefing(
            vault_context=context,
            for_date=BRIEFING_DATE,
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )

    assert target.read_bytes() == b"prior complete note"
    assert list(target.parent.glob("*.tmp")) == []
    assert list(target.parent.glob(".*.tmp")) == []


def test_load_briefing_round_trip_absent_and_invalid_schema(
    vault: tuple[Path, VaultContext],
) -> None:
    root, context = vault
    assert load_briefing(vault_context=context, for_date=BRIEFING_DATE) is None

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    assert load_briefing(vault_context=context, for_date=BRIEFING_DATE) is not None

    target = _target(root)
    payload = yaml.safe_load(target.read_text(encoding="utf-8").split("---", 2)[1])
    payload["schema_version"] = 999
    target.write_text(f"---\n{yaml.safe_dump(payload)}---\ninvalid\n", encoding="utf-8")
    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)
