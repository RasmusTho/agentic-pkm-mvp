from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.briefing.compose import BriefingIdentityMigration
from app.ops import native_source_identity_supportable_repair as repair
from app.vault.manager import VaultContext
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


class AllowGuard:
    def assert_writes_allowed(self, _action: str) -> None:
        return None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _companion_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    identity = str(uuid4())
    source_rel = "notes/current.md"
    source = tmp_path / source_rel
    source.parent.mkdir(parents=True)
    source.write_text(dump_frontmatter({"uuid": identity, "title": "Current"}, "body\n"))
    companion_rel = f"_system/companions/{identity}.md"
    companion = tmp_path / companion_rel
    companion.parent.mkdir(parents=True)
    old_hash = "0" * 64
    original_fm = {
        "uuid": identity,
        "source_ref": "_system/companions/old-sidecar.md",
        "title": "Current",
        "content_hash": old_hash,
        "ingest_state": "indexed",
        "last_ingested": "2026-10-20T00:00:00+00:00",
        "created_by_instance": "dev",
        "custom": {"preserve": True},
        "identity_history": [{
            "timestamp": "2026-10-19T00:00:00+00:00",
            "event": "repair",
            "before": {},
            "after": {},
            "reason": "prior",
        }],
    }
    original = dump_frontmatter(original_fm, "")
    companion.write_text(original)
    observation = SimpleNamespace(path=source)
    monkeypatch.setattr(repair, "_canonical_inventory", lambda _root: (observation,))
    monkeypatch.setattr(
        repair,
        "_source_claims",
        lambda _root, _observations: ({identity: 1}, {source_rel}),
    )
    return identity, source_rel, companion, original_fm, original


def test_companion_continuity_repairs_only_source_ref_hash_and_bounded_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, source_rel, companion, original_fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    proposal = repair.prepare_companion_continuity_repair(
        vault_root=tmp_path,
        source_rel=source_rel,
        observed_at="2026-10-22T00:00:00+00:00",
    )
    before, before_body = load_frontmatter(proposal.original_text)
    after, after_body = load_frontmatter(proposal.candidate_text)
    assert proposal.identity == identity
    assert proposal.companion_rel == companion.relative_to(tmp_path).as_posix()
    assert after["source_ref"] == source_rel
    assert after["content_hash"] != original_fm["content_hash"]
    assert after["identity_history"][-1]["event"] == "path_change"
    assert len(after["identity_history"]) <= 10
    for key in ("source_ref", "content_hash", "identity_history"):
        before.pop(key, None)
        after.pop(key, None)
    assert after == before
    assert after_body == before_body

    repair.commit_companion_continuity_repair(
        proposal,
        vault_root=tmp_path,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    )
    assert _sha(companion.read_text()) == proposal.candidate_sha256


def test_companion_continuity_refuses_uuid_locator_hash_version_or_descriptor_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity, source_rel, companion, _fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    proposal = repair.prepare_companion_continuity_repair(
        vault_root=tmp_path,
        source_rel=source_rel,
        observed_at="2026-10-22T00:00:00+00:00",
    )
    companion.write_text(proposal.original_text + "drift")
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.commit_companion_continuity_repair(
            proposal,
            vault_root=tmp_path,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )

    companion.unlink()
    companion.symlink_to(tmp_path / source_rel)
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.prepare_companion_continuity_repair(
            vault_root=tmp_path,
            source_rel=source_rel,
            observed_at="2026-10-22T00:00:00+00:00",
        )


def test_descriptor_reads_refuse_ancestor_alias_swap_and_fifo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "note.md").write_text("ok")
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair._regular_nofollow_text(tmp_path, "alias/note.md")

    fifo = tmp_path / "pipe.md"
    os.mkfifo(fifo)
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair._regular_nofollow_text(tmp_path, "pipe.md")

    stable = tmp_path / "stable"
    stable.mkdir()
    (stable / "one.md").write_text("one")
    original_listdir = os.listdir
    calls = 0

    def swapping_listdir(descriptor):
        nonlocal calls
        calls += 1
        result = original_listdir(descriptor)
        if calls == 1:
            stable.rename(tmp_path / "moved")
            stable.mkdir()
            (stable / "two.md").write_text("two")
        return result

    monkeypatch.setattr(repair.os, "listdir", swapping_listdir)
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair._stable_directory_names(tmp_path, "stable")


def test_companion_continuity_refuses_canonical_equivalent_duplicate_uuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity, source_rel, companion, _fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    duplicate = companion.with_name("duplicate.md")
    duplicate.write_text(dump_frontmatter({
        "uuid": identity.upper(),
        "source_ref": "_system/companions/another-sidecar.md",
    }, ""))
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.prepare_companion_continuity_repair(
            vault_root=tmp_path,
            source_rel=source_rel,
            observed_at="2026-10-22T00:00:00+00:00",
        )


def test_source_claims_fail_closed_on_unparseable_observation(tmp_path: Path) -> None:
    identity = str(uuid4())
    valid = tmp_path / "valid.md"
    invalid = tmp_path / "invalid.md"
    valid.write_text(dump_frontmatter({"uuid": identity}, "valid\n"))
    invalid.write_text(f"---\nuuid: [{identity}\n---\ninvalid\n")
    observations = (
        SimpleNamespace(path=valid),
        SimpleNamespace(path=invalid),
    )
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair._source_claims(tmp_path, observations)


def test_companion_commit_rechecks_and_refuses_unknown_global_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    production_source_claims = repair._source_claims
    _identity, source_rel, _companion, _fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    proposal = repair.prepare_companion_continuity_repair(
        vault_root=tmp_path,
        source_rel=source_rel,
        observed_at="2026-10-22T00:00:00+00:00",
    )
    malformed = tmp_path / "notes" / "unknown.md"
    malformed.write_text("---\nuuid: [unclosed\n---\nunknown\n")
    observations = (
        SimpleNamespace(path=tmp_path / source_rel),
        SimpleNamespace(path=malformed),
    )
    monkeypatch.setattr(repair, "_canonical_inventory", lambda _root: observations)
    monkeypatch.setattr(repair, "_source_claims", production_source_claims)
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.commit_companion_continuity_repair(
            proposal,
            vault_root=tmp_path,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )


def _briefing_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "System/Briefings/2026-10-22.md"
    target.parent.mkdir(parents=True)
    original = dump_frontmatter({
        "schema_version": 2,
        "artifact_class": "daily_briefing",
        "agent_maintained": True,
        "read_only": True,
        "authority_role": "derived",
        "briefing_date": "2026-10-22",
        "sections": {},
        "degraded_sections": [],
        "custom": "preserved",
    }, "# Briefing\n")
    candidate_fm, body = load_frontmatter(original)
    candidate_fm["uuid"] = str(uuid4())
    candidate = dump_frontmatter(candidate_fm, body)
    target.write_text(original)
    migration = BriefingIdentityMigration(
        note_rel_path=target.relative_to(tmp_path).as_posix(),
        expected_version=_sha(original),
        content=candidate,
    )
    calls: list[str] = []
    def prepare(**_kwargs):
        calls.append("prepare")
        return migration

    monkeypatch.setattr(repair, "prepare_briefing_identity_migration", prepare)

    def migrate(**_kwargs):
        calls.append("migrate")
        target.write_text(candidate)
        return SimpleNamespace(outcome="written")

    monkeypatch.setattr(repair, "migrate_briefing_identity", migrate)
    context = VaultContext(status="selected", active_vault_path=str(tmp_path))
    return context, target, original, candidate, calls


def test_briefing_batch_uses_exact_composer_identity_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, target, original, candidate, calls = _briefing_fixture(tmp_path, monkeypatch)
    proposal = repair.prepare_briefing_repair(
        vault_context=context,
        for_date=date(2026, 10, 22),
    )
    before, before_body = load_frontmatter(original)
    after, after_body = load_frontmatter(candidate)
    after.pop("uuid")
    assert after == before
    assert after_body == before_body
    repair.commit_briefing_repair(
        proposal,
        vault_context=context,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    )
    assert calls == ["prepare", "prepare", "migrate"]
    assert _sha(target.read_text()) == proposal.candidate_sha256


def test_briefing_batch_refuses_damaged_unowned_profile_bound_or_stale_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, target, _original, _candidate, _calls = _briefing_fixture(tmp_path, monkeypatch)
    proposal = repair.prepare_briefing_repair(
        vault_context=context,
        for_date=date(2026, 10, 22),
    )
    target.write_text("damaged")
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.commit_briefing_repair(
            proposal,
            vault_context=context,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )
    monkeypatch.setattr(
        repair,
        "prepare_briefing_identity_migration",
        lambda **_kwargs: None,
    )
    with pytest.raises(repair.SupportableRepairRefusal, match="authority_refused"):
        repair.prepare_briefing_repair(
            vault_context=context,
            for_date=date(2026, 10, 22),
        )


class FakeEffects:
    def __init__(self, authority: repair.RepairAuthoritySnapshot) -> None:
        self.authority = authority
        self.events: list[str] = []

    @contextmanager
    def owned_repair_fence(self):
        self.events.append("enter")
        try:
            yield
        finally:
            self.events.append("exit")

    def read_repair_authority(self) -> repair.RepairAuthoritySnapshot:
        self.events.append("read")
        return self.authority


def _batch(tmp_path: Path) -> tuple[repair.RepairBatch, FakeEffects, VaultContext]:
    revision = "a" * 40
    image = "sha256:" + "b" * 64
    selection = "c" * 64
    companion_rows = []
    from app.services.companion_note import companion_path
    for index in range(repair.EXPECTED_COMPANION_COUNT):
        identity = str(uuid4())
        companion_rows.append(repair.CompanionContinuityProposal(
            source_rel=f"notes/{index}.md",
            companion_rel=companion_path(identity, tmp_path).as_posix(),
            identity=identity,
            observed_at="2026-10-22T00:00:00+00:00",
            original_text="before",
            candidate_text="after",
            original_sha256=_sha("before"),
            candidate_sha256=_sha("after"),
        ))
    companions = tuple(companion_rows)
    start = date(2026, 9, 26)
    context = VaultContext(status="selected", active_vault_path=str(tmp_path))
    from app.briefing.compose import briefing_note_path
    briefings = tuple(
        repair.BriefingRepairProposal(
            for_date=start + timedelta(days=index),
            migration=BriefingIdentityMigration(
                note_rel_path=briefing_note_path(
                    vault_context=context,
                    for_date=start + timedelta(days=index),
                ).relative_to(tmp_path).as_posix(),
                expected_version=_sha("before"),
                content="after",
            ),
            original_text="before",
            original_sha256=_sha("before"),
            candidate_sha256=_sha("after"),
        )
        for index in range(repair.EXPECTED_BRIEFING_COUNT)
    )
    target_set = repair._target_set_sha256(companions, briefings)
    vault_fingerprint = repair._vault_fingerprint(tmp_path)
    batch = repair.RepairBatch(
        revision,
        image,
        selection,
        target_set,
        vault_fingerprint,
        companions,
        briefings,
    )
    authority = repair.RepairAuthoritySnapshot(
        revision,
        image,
        selection,
        target_set,
        vault_fingerprint,
        controller_unloaded=True,
        write_guard_healthy=True,
        writers_isolated=True,
        owned_operation_fences_healthy=True,
    )
    return batch, FakeEffects(authority), context


def test_batch_fences_partial_commit_and_indeterminate_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch, effects, context = _batch(tmp_path)
    calls = 0

    def companion_commit(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("private error")

    monkeypatch.setattr(repair, "commit_companion_continuity_repair", companion_commit)
    monkeypatch.setattr(repair, "commit_briefing_repair", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(repair, "_classify_readback", lambda *_args, **_kwargs: "indeterminate")
    receipt = repair.run_supportable_repair_batch(
        batch,
        effects=effects,
        vault_root=tmp_path,
        vault_context=context,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    )
    assert receipt == {
        "contract": repair.RECEIPT_CONTRACT,
        "channel": "dev",
        "result": "indeterminate",
        "planned_count": 49,
        "repaired_count": 48,
        "refused_count": 0,
        "indeterminate_count": 1,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    }
    assert effects.events == ["enter", "read", "read", "exit"]


def test_batch_binds_exact_target_set_and_vault_root(
    tmp_path: Path,
) -> None:
    batch, effects, context = _batch(tmp_path)
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.run_supportable_repair_batch(
            replace(batch, target_set_sha256="0" * 64),
            effects=effects,
            vault_root=tmp_path,
            vault_context=context,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )

    other = tmp_path / "other"
    other.mkdir()
    other_context = VaultContext(status="selected", active_vault_path=str(other))
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.run_supportable_repair_batch(
            batch,
            effects=effects,
            vault_root=tmp_path,
            vault_context=other_context,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )


def test_rollback_requires_exact_repair_bytes_and_never_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity, source_rel, companion, _fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    proposal = repair.prepare_companion_continuity_repair(
        vault_root=tmp_path,
        source_rel=source_rel,
        observed_at="2026-10-22T00:00:00+00:00",
    )
    batch, effects, context = _batch(tmp_path)
    companions = (proposal, *batch.companion[1:])
    target_set = repair._target_set_sha256(companions, batch.briefings)
    batch = replace(batch, companion=companions, target_set_sha256=target_set)
    effects.authority = replace(effects.authority, target_set_sha256=target_set)
    companion.write_text(proposal.candidate_text)
    assert repair.rollback_companion_continuity_repair(
        proposal,
        batch=batch,
        effects=effects,
        vault_root=tmp_path,
        vault_context=context,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    ) == "committed"
    assert companion.exists()
    assert companion.read_text() == proposal.original_text
    companion.write_text("foreign")
    assert repair.rollback_companion_continuity_repair(
        proposal,
        batch=batch,
        effects=effects,
        vault_root=tmp_path,
        vault_context=context,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    ) == "indeterminate"
    assert companion.read_text() == "foreign"


def test_rollback_refuses_tampered_bytes_path_escape_and_authority_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity, source_rel, companion, _fm, _original = _companion_fixture(
        tmp_path, monkeypatch,
    )
    proposal = repair.prepare_companion_continuity_repair(
        vault_root=tmp_path,
        source_rel=source_rel,
        observed_at="2026-10-22T00:00:00+00:00",
    )
    batch, effects, context = _batch(tmp_path)
    companions = (proposal, *batch.companion[1:])
    target_set = repair._target_set_sha256(companions, batch.briefings)
    batch = replace(batch, companion=companions, target_set_sha256=target_set)
    effects.authority = replace(effects.authority, target_set_sha256=target_set)
    companion.write_text(proposal.candidate_text)

    tampered = replace(proposal, original_text=proposal.original_text + "tampered")
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.rollback_companion_continuity_repair(
            tampered,
            batch=replace(batch, companion=(tampered, *batch.companion[1:])),
            effects=effects,
            vault_root=tmp_path,
            vault_context=context,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )
    assert companion.read_text() == proposal.candidate_text

    escaped = replace(proposal, companion_rel="../outside.md")
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.rollback_companion_continuity_repair(
            escaped,
            batch=replace(batch, companion=(escaped, *batch.companion[1:])),
            effects=effects,
            vault_root=tmp_path,
            vault_context=context,
            write_guard=AllowGuard(),  # type: ignore[arg-type]
        )
    assert companion.read_text() == proposal.candidate_text

    class DriftingEffects(FakeEffects):
        def read_repair_authority(self) -> repair.RepairAuthoritySnapshot:
            value = super().read_repair_authority()
            if self.events.count("read") == 2:
                return replace(value, writers_isolated=False)
            return value

    drifting = DriftingEffects(effects.authority)
    assert repair.rollback_companion_continuity_repair(
        proposal,
        batch=batch,
        effects=drifting,
        vault_root=tmp_path,
        vault_context=context,
        write_guard=AllowGuard(),  # type: ignore[arg-type]
    ) == "indeterminate"


def test_public_receipt_is_closed_content_free_and_reconciled() -> None:
    payload = {
        "contract": repair.RECEIPT_CONTRACT,
        "channel": "dev",
        "result": "failed",
        "planned_count": 49,
        "repaired_count": 48,
        "refused_count": 1,
        "indeterminate_count": 0,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    }
    assert repair.validate_public_receipt(payload) == payload
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.validate_public_receipt({**payload, "private_path": "/secret"})
    with pytest.raises(repair.SupportableRepairRefusal, match="context_refused"):
        repair.validate_public_receipt({**payload, "planned_count": 50})
