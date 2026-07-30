from __future__ import annotations

import json
from copy import deepcopy
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
from app.services.commitment_persistence import commitment_artifact_path, persist_commitment
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
    from app.briefing import compose as compose_module
    from app.episodes.stream_registry import STATUS_LIVE, StreamRegistry, StreamRegistryEntry

    monkeypatch.setattr(
        compose_module,
        "load_registry",
        lambda: StreamRegistry(
            entries={
                "calendar": StreamRegistryEntry(
                    stream_id="calendar",
                    status=STATUS_LIVE,
                    owner_constituent="private-bindings",
                    dimensions_fed=("time",),
                    transport="module:app.episodes.calendar_stream",
                    consent_class="operator-bound",
                    cadence="sparse",
                )
            }
        ),
    )
    monkeypatch.setattr(compose_module, "read_calendar_raw_items_for_tick", lambda: ([], []))
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


def test_briefing_write_rechecks_guard_before_any_mutation(
    vault: tuple[Path, VaultContext],
) -> None:
    root, context = vault
    snapshots = iter(
        [
            {"state": "healthy"},
            {"state": "safe_mode", "reason": "health changed"},
        ]
    )
    guard = WriteGuard(lambda: next(snapshots))

    with pytest.raises(WritesBlockedError) as exc_info:
        compose_briefing(vault_context=context, for_date=BRIEFING_DATE, write_guard=guard)

    assert exc_info.value.action == "briefing.write_note"
    assert not _target(root).exists()
    assert not (root / "_system" / "briefings").exists()
    assert list(root.rglob("*.tmp")) == []


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
            "surfaced_refs": [
                {"ref": "Notes/Z.md", "why": "second", "uuid": "uuid-z"},
                {"ref": "Notes/A.md", "why": "first", "uuid": "uuid-a"},
            ],
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
    calls = {"commitments": 0, "moments": 0, "receipts": 0}

    def shuffled_commitments(**_: object) -> list[CommitmentRecord]:
        calls["commitments"] += 1
        return list(reversed(commitments)) if calls["commitments"] == 1 else list(commitments)

    def shuffled_moments(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        calls["moments"] += 1
        snapshot = deepcopy(moments)
        if calls["moments"] == 1:
            snapshot.reverse()
        else:
            snapshot[0]["surfaced_refs"] = list(
                reversed(snapshot[0]["surfaced_refs"])  # type: ignore[arg-type]
            )
        return snapshot

    def shuffled_receipts(*_: object) -> list[dict[str, object]]:
        calls["receipts"] += 1
        return list(reversed(receipts)) if calls["receipts"] == 1 else list(receipts)

    monkeypatch.setattr(compose_module, "load_commitments", shuffled_commitments)
    monkeypatch.setattr(compose_module, "collect_now_moments", shuffled_moments)
    monkeypatch.setattr(compose_module, "iter_decision_receipts", shuffled_receipts)
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
    assert calls == {"commitments": 2, "moments": 2, "receipts": 2}


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


def test_commitments_order_next_waiting_review_return_with_dedup_and_done_exclusion(
    vault: tuple[Path, VaultContext],
) -> None:
    _root, context = vault
    _seed_commitment(context, "next-2", kind="next_action", state="next")
    _seed_commitment(context, "next-1", kind="next_action", state="next")
    _seed_commitment(context, "next-review", kind="review_return", state="next")
    _seed_commitment(context, "waiting-1", kind="waiting", state="waiting")
    _seed_commitment(context, "review-1", kind="review_return", state="open")
    _seed_commitment(context, "review-done", kind="review_return", state="done")

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert [item.commitment_id for item in note.sections["commitments"].items] == [
        "next-1",
        "next-2",
        "next-review",
        "waiting-1",
        "review-1",
    ]


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
    assert _target(root).read_text(encoding="utf-8").count("No items.") == 4


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


def test_receipts_preserve_subsecond_precision_for_chronological_order(
    vault: tuple[Path, VaultContext],
) -> None:
    root, context = vault
    _seed_receipts(
        root,
        [
            _receipt("earlier", "2026-07-09T12:00:00.100000Z", key="z"),
            _receipt("later", "2026-07-09T12:00:00.900000Z", key="a"),
        ],
    )
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    items = note.sections["decision_receipts"].items
    assert [item.object_id for item in items] == ["earlier", "later"]
    assert [item.created_at for item in items] == [
        "2026-07-09T12:00:00.100000Z",
        "2026-07-09T12:00:00.900000Z",
    ]


def test_each_public_source_reader_is_called_exactly_once(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.briefing import compose as compose_module

    _root, context = vault
    calls = {"commitments": 0, "moments": 0, "receipts": 0}

    def commitments(**_: object) -> list[CommitmentRecord]:
        calls["commitments"] += 1
        return []

    def moments(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        calls["moments"] += 1
        return []

    def receipts(*_: object) -> list[dict[str, object]]:
        calls["receipts"] += 1
        return []

    monkeypatch.setattr(compose_module, "load_commitments", commitments)
    monkeypatch.setattr(compose_module, "collect_now_moments", moments)
    monkeypatch.setattr(compose_module, "iter_decision_receipts", receipts)
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    assert calls == {"commitments": 1, "moments": 1, "receipts": 1}


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


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("commitment_id", 1),
        ("target_ref", 1),
        ("summary", 1),
        ("commitment_kind", 1),
        ("state", 1),
        ("commitment_kind", " next_action "),
        ("commitment_kind", "unknown-kind"),
        ("state", " next "),
        ("state", "unknown-state"),
        ("summary", "   "),
        ("summary", "Summary\x00bad"),
        ("target_ref", " Projects/A.md "),
        ("target_ref", "Projects/A.md\nProjects/B.md"),
        ("commitment_id", " bad "),
    ],
)
def test_invalid_commitment_scalar_degrades_whole_section(
    vault: tuple[Path, VaultContext],
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    from app.briefing import compose as compose_module

    root, context = vault
    record_values: dict[str, object] = {
        "commitment_id": "bad",
        "commitment_kind": "next_action",
        "state": "next",
        "target_ref": "Projects/A.md",
        "summary": "Summary bad",
    }
    record_values[field] = invalid_value
    invalid_record = CommitmentRecord(**record_values)  # type: ignore[arg-type]
    monkeypatch.setattr(
        compose_module,
        "load_commitments",
        lambda **_: [invalid_record],
    )
    _seed_moment(root, "moment-kept")
    _seed_receipts(root, [_receipt("receipt-kept", "2026-07-09T12:00:00Z")])

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert note.degraded_sections == ("commitments",)
    assert note.sections["commitments"].status == "degraded"
    assert note.sections["commitments"].reason == "invalid_source_record"
    assert note.sections["commitments"].items == ()
    assert len(note.sections["moments"].items) == 1
    assert len(note.sections["decision_receipts"].items) == 1


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("moment_id", " padded "),
        ("moment_id", "moment\nother"),
        ("moment_id", "../../secret"),
        ("moment_id", "nested/moment"),
        ("ref", " Notes/A.md "),
        ("ref", "Notes/A.md\nNotes/B.md"),
        ("ref", "Notes/\x00.md"),
        ("uuid", " uuid "),
        ("uuid", "uuid\nother"),
        ("need_basis", " reorientation "),
        ("need_basis", "unknown-basis"),
        ("urgency_band", " timely "),
        ("urgency_band", "unknown-band"),
    ],
)
def test_invalid_moment_provenance_text_degrades_whole_section(
    vault: tuple[Path, VaultContext],
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: str,
) -> None:
    from app.briefing import compose as compose_module

    root, context = vault
    raw_ref: dict[str, object] = {"ref": "Notes/A.md", "why": "Useful", "uuid": "uuid"}
    record: dict[str, object] = {
        "moment_id": "moment-bad",
        "title": "Moment bad",
        "need_basis": "reorientation",
        "urgency_band": "timely",
        "surfaced_refs": [raw_ref],
    }
    if field in {"moment_id", "need_basis", "urgency_band"}:
        record[field] = invalid_value
    else:
        raw_ref[field] = invalid_value
    monkeypatch.setattr(compose_module, "collect_now_moments", lambda *_: [record])
    _seed_commitment(context, "commitment-kept", kind="next_action", state="next")
    _seed_receipts(root, [_receipt("receipt-kept", "2026-07-09T12:00:00Z")])

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)

    assert note is not None
    assert note.degraded_sections == ("moments",)
    assert note.sections["moments"].reason == "invalid_source_record"
    assert note.sections["moments"].items == ()
    assert len(note.sections["commitments"].items) == 1
    assert len(note.sections["decision_receipts"].items) == 1


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("object_id", " padded "),
        ("object_id", "object\nother"),
        ("object_id", "object\x00bad"),
        ("key", " review "),
        ("key", "review\nother"),
        ("vault_uuid", " uuid "),
        ("vault_uuid", "uuid\nother"),
        ("created_at", " 2026-07-09T12:00:00Z "),
    ],
)
def test_invalid_receipt_provenance_text_degrades_whole_section(
    vault: tuple[Path, VaultContext],
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: str,
) -> None:
    from app.briefing import compose as compose_module

    root, context = vault
    record = _receipt("receipt-bad", "2026-07-09T12:00:00Z")
    record[field] = invalid_value
    monkeypatch.setattr(compose_module, "iter_decision_receipts", lambda *_: [record])
    _seed_commitment(context, "commitment-kept", kind="next_action", state="next")
    _seed_moment(root, "moment-kept")

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)

    assert note is not None
    assert note.degraded_sections == ("decision_receipts",)
    assert note.sections["decision_receipts"].reason == "invalid_source_record"
    assert note.sections["decision_receipts"].items == ()
    assert len(note.sections["commitments"].items) == 1
    assert len(note.sections["moments"].items) == 1


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


@pytest.mark.parametrize(
    "corruption",
    [
        "arbitrary_body",
        "truncated_section",
        "contradicting_provenance",
    ],
)
def test_load_briefing_rejects_body_that_disagrees_with_frontmatter(
    vault: tuple[Path, VaultContext], corruption: str
) -> None:
    root, context = vault
    _seed_commitment(context, "commitment-1", kind="next_action", state="next")
    _seed_moment(root, "moment-1")
    _seed_receipts(root, [_receipt("object-1", "2026-07-09T12:00:00Z")])
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    target = _target(root)
    text = target.read_text(encoding="utf-8")
    _opening, yaml_text, body = text.split("---\n", 2)

    if corruption == "arbitrary_body":
        corrupted_body = "CORRUPTED BODY\n"
    elif corruption == "truncated_section":
        corrupted_body = body.split("## Decision receipts", 1)[0]
    else:
        canonical_path = commitment_artifact_path("commitment-1", root)
        assert canonical_path in body
        corrupted_body = body.replace(canonical_path, "Human/contradiction.md", 1)

    target.write_text(f"---\n{yaml_text}---\n{corrupted_body}", encoding="utf-8")

    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("agent_maintained", 1),
        ("read_only", 1),
    ],
)
def test_load_briefing_rejects_scalar_type_confusion(
    vault: tuple[Path, VaultContext],
    field: str,
    malformed_value: object,
) -> None:
    root, context = vault
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    target = _target(root)
    payload = yaml.safe_load(target.read_text(encoding="utf-8").split("---", 2)[1])
    payload[field] = malformed_value
    target.write_text(
        f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\nmalformed\n",
        encoding="utf-8",
    )

    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)


@pytest.mark.parametrize(
    "malformed_case",
    [
        "empty_surfaced_ref",
        "invalid_surfaced_ref_uuid",
        "invalid_receipt_vault_uuid",
        "noncanonical_receipt_timestamp",
        "noncanonical_commitment_artifact_path",
        "noncanonical_moment_artifact_path",
        "noncanonical_receipt_path",
        "degraded_without_reason",
    ],
)
def test_load_briefing_rejects_malformed_schema_v1_provenance(
    vault: tuple[Path, VaultContext], malformed_case: str
) -> None:
    root, context = vault
    _seed_commitment(context, "commitment-1", kind="next_action", state="next")
    _seed_moment(root, "moment-1", refs=[SurfacedRef(ref="Notes/A.md", why="why")])
    _seed_receipts(root, [_receipt("object-1", "2026-07-09T12:00:00Z")])
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    target = _target(root)
    text = target.read_text(encoding="utf-8")
    payload = yaml.safe_load(text.split("---", 2)[1])

    if malformed_case == "empty_surfaced_ref":
        payload["sections"]["moments"]["items"][0]["surfaced_refs"] = [{}]
    elif malformed_case == "invalid_surfaced_ref_uuid":
        payload["sections"]["moments"]["items"][0]["surfaced_refs"][0]["uuid"] = ""
    elif malformed_case == "invalid_receipt_vault_uuid":
        payload["sections"]["decision_receipts"]["items"][0]["vault_uuid"] = ""
    elif malformed_case == "noncanonical_receipt_timestamp":
        payload["sections"]["decision_receipts"]["items"][0]["created_at"] = (
            "2026-07-09T12:00:00+00:00"
        )
    elif malformed_case == "noncanonical_commitment_artifact_path":
        payload["sections"]["commitments"]["items"][0]["artifact_path"] = (
            "Human/private.md"
        )
    elif malformed_case == "noncanonical_moment_artifact_path":
        payload["sections"]["moments"]["items"][0]["artifact_path"] = (
            "Human/private.md"
        )
    elif malformed_case == "noncanonical_receipt_path":
        payload["sections"]["decision_receipts"]["items"][0]["receipt_path"] = (
            "_system/receipts/decisions/wrong-shard.jsonl"
        )
    else:
        payload["degraded_sections"] = ["moments"]
        payload["sections"]["moments"] = {"status": "degraded", "items": []}

    target.write_text(
        f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\nmalformed\n",
        encoding="utf-8",
    )
    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("commitment_kind", " next_action "),
        ("commitment_kind", "unknown-kind"),
        ("state", " next "),
        ("state", "unknown-state"),
        ("need_basis", " reorientation "),
        ("need_basis", "unknown-basis"),
        ("urgency_band", " timely "),
        ("urgency_band", "unknown-band"),
    ],
)
def test_load_briefing_rejects_noncanonical_categorical_values(
    vault: tuple[Path, VaultContext], field: str, invalid_value: str
) -> None:
    root, context = vault
    _seed_commitment(context, "commitment-1", kind="next_action", state="next")
    _seed_moment(root, "moment-1")
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    target = _target(root)
    text = target.read_text(encoding="utf-8")
    _opening, yaml_text, body = text.split("---\n", 2)
    payload = yaml.safe_load(yaml_text)

    if field in {"commitment_kind", "state"}:
        payload["sections"]["commitments"]["items"][0][field] = invalid_value
        if field == "state":
            body = body.replace("[next]", f"[{invalid_value}]", 1)
    else:
        payload["sections"]["moments"]["items"][0][field] = invalid_value
        if field == "urgency_band":
            body = body.replace("[timely]", f"[{invalid_value}]", 1)

    target.write_text(
        f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\n{body}",
        encoding="utf-8",
    )

    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)


def test_load_briefing_rejects_unsafe_moment_id_in_provenance_path(
    vault: tuple[Path, VaultContext],
) -> None:
    root, context = vault
    _seed_moment(root, "moment-1")
    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    target = _target(root)
    text = target.read_text(encoding="utf-8")
    _opening, yaml_text, body = text.split("---\n", 2)
    payload = yaml.safe_load(yaml_text)
    item = payload["sections"]["moments"]["items"][0]
    item["moment_id"] = "../../secret"
    item["artifact_path"] = "_system/moments/../../secret.md"
    body = body.replace("_system/moments/moment-1.md", item["artifact_path"], 1)
    target.write_text(
        f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\n{body}",
        encoding="utf-8",
    )

    with pytest.raises(BriefingReadError):
        load_briefing(vault_context=context, for_date=BRIEFING_DATE)
