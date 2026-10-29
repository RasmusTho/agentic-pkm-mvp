"""DEBRIEF-03 review surface: accept/dismiss flips review_state, never deletes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.episode_debrief import review
from app.episode_debrief.trigger import debrief_id_for_episode
from app.expansion import create
from app.services.outbox import read_jsonl_outbox_records
from app.write_guard import WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter
from tests.api._vault_test_helpers import bind_initialized_vault

HEALTHY = WriteGuard(lambda: {"state": "healthy"})


def _publish_debrief(root: Path, *, episode_id: str | None = None) -> tuple[str, Path, Path]:
    """Publish one debrief exactly as Create does: draft, integrity, proposal receipt."""
    episode_id = episode_id or "ep-" + uuid4().hex
    debrief_id = debrief_id_for_episode(episode_id)
    episode_note = root / "episodes" / f"{episode_id}.md"
    episode_note.parent.mkdir(parents=True, exist_ok=True)
    episode_note.write_text(dump_frontmatter({
        "episode_id": episode_id, "scope": "work", "title": "Planning",
        "time": {"start": "2026-10-13T08:00:00Z", "closed": True}, "segmentation": "proposed",
        "debrief_ref": [debrief_id],
    }, "Human content stays unchanged.\n"), encoding="utf-8")
    source = create.SourceInput(object_id="obj-1", note_path="notes/a.md", text="Decided X.", quoted_spans=("Decided X.",))
    frontmatter = create._draft_frontmatter(
        kind=create.OutputKind.EPISODE_DEBRIEF, draft_id=debrief_id, sources=[source],
        cognition_metadata={"model": "fixture"}, created_at=datetime(2026, 10, 13, 9, tzinfo=timezone.utc),
        staleness_days=7, request_fingerprint="fp-" + debrief_id,
    )
    frontmatter.update({"episode_id": episode_id, "scope": "work"})
    body = "# Episode debrief: Planning\n\n## Decisions\n\n- Decided X. [obj-1]\n"
    text = create._draft_note_text(frontmatter=frontmatter, body=body, draft_id=debrief_id)
    draft = root / review.DEBRIEF_DIR / f"{debrief_id}.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    create._write_draft_integrity(draft, draft_id=debrief_id, request_fingerprint="fp-" + debrief_id, draft_sha256=digest)
    create._emit_receipt(create.CREATE_PROPOSED_EVENT, {"draft_id": debrief_id, "draft_sha256": digest},
                         outbox_path=draft.parent / "outbox.jsonl", trace_id=None, event_id=uuid4().hex)
    return debrief_id, draft, episode_note


def _receipts(draft: Path, event: str) -> list[dict]:
    return [r for r in read_jsonl_outbox_records(draft.parent / "outbox.jsonl", read_only=True) if r["event"] == event]


def _without_review_state(text: str) -> tuple[dict, str]:
    fields, body = load_frontmatter(text)
    fields.pop("review_state")
    return fields, body


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path, channel="test")
    monkeypatch.setattr(companion_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None)
    return tmp_path


def test_fresh_debrief_surfaced_from_durable_source(vault: Path) -> None:
    debrief_id, draft, _ = _publish_debrief(vault)
    # A draft without a publication receipt/integrity is not a reviewable debrief.
    unpublished = vault / review.DEBRIEF_DIR / f"{debrief_id_for_episode('ep-unpublished')}.md"
    unpublished.write_text(draft.read_text(encoding="utf-8").replace(debrief_id, unpublished.stem), encoding="utf-8")
    before = draft.read_bytes()

    response = TestClient(app).get("/api/companion/episode-debriefs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert [item["debrief_id"] for item in payload["fresh"]] == [debrief_id]
    item = payload["fresh"][0]
    assert item["review_state"] == "draft" and item["authority_state"] == "proposal"
    assert item["title"] == "Episode debrief: Planning" and "Decided X." in item["body"]
    assert "AI:Start" not in item["body"]
    assert draft.read_bytes() == before  # reading never writes

    # The projection re-reads durable truth: once disposed it is no longer fresh.
    review.review_debrief(debrief_id, "dismissed", vault_root=vault, write_guard=HEALTHY)
    assert TestClient(app).get("/api/companion/episode-debriefs").json()["fresh"] == []


def test_accept_flips_review_state_and_emits_receipt(vault: Path) -> None:
    debrief_id, draft, episode_note = _publish_debrief(vault)
    before, episode_before = draft.read_text(encoding="utf-8"), episode_note.read_bytes()

    response = TestClient(app).post(f"/api/companion/episode-debriefs/{debrief_id}/review",
                                    json={"disposition": "accepted"})

    assert response.status_code == 200
    assert response.json()["review_state"] == "reviewed"
    after = draft.read_text(encoding="utf-8")
    assert load_frontmatter(after)[0]["review_state"] == "reviewed"
    assert _without_review_state(after) == _without_review_state(before)
    assert episode_note.read_bytes() == episode_before  # debrief_ref link untouched
    [receipt] = _receipts(draft, review.REVIEWED_EVENT)
    assert receipt["payload"] == {"debrief_id": debrief_id, "episode_id": load_frontmatter(before)[0]["episode_id"],
                                  "prior_review_state": "draft", "review_state": "reviewed"}
    assert response.json()["receipt"] == f"{review.REVIEWED_EVENT}:{receipt['event_id']}"


def test_dismiss_does_not_delete_artifact(vault: Path) -> None:
    debrief_id, draft, episode_note = _publish_debrief(vault)
    before, episode_before = draft.read_text(encoding="utf-8"), episode_note.read_bytes()

    # Production call site: the companion dismiss route.
    response = TestClient(app).post(f"/api/companion/episode-debriefs/{debrief_id}/review",
                                    json={"disposition": "dismissed"})

    assert response.status_code == 200
    assert response.json()["review_state"] == "archived"
    assert draft.is_file() and create._draft_integrity_path(draft).is_file()
    after = draft.read_text(encoding="utf-8")
    assert load_frontmatter(after)[0]["review_state"] == "archived"
    assert _without_review_state(after) == _without_review_state(before)
    assert episode_note.read_bytes() == episode_before
    assert debrief_id in load_frontmatter(episode_note.read_text(encoding="utf-8"))[0]["debrief_ref"]
    assert [r["payload"]["review_state"] for r in _receipts(draft, review.DISMISSED_EVENT)] == ["archived"]
    # Still discoverable as a published durable debrief, and DEBRIEF-02 replay
    # still verifies its publication integrity rather than refusing forever.
    assert review.published_debrief(draft) is not None
    metadata, digest = review.replay_published_metadata(draft, request_fingerprint="fp-" + debrief_id,
                                                        draft_id=debrief_id)
    assert metadata["review_state"] == "draft" and digest == hashlib.sha256(before.encode("utf-8")).hexdigest()
    # Unlike EXP-4 decline, nothing was retired or renamed in the debrief directory.
    assert not [p for p in draft.parent.iterdir() if "retire" in p.name or "declined" in p.name]


@pytest.mark.parametrize("disposition", ["accepted", "dismissed"])
def test_review_actions_never_advance_authority_state(vault: Path, disposition: str) -> None:
    debrief_id, draft, _ = _publish_debrief(vault)

    result = review.review_debrief(debrief_id, disposition, vault_root=vault, write_guard=HEALTHY)

    fields = load_frontmatter(draft.read_text(encoding="utf-8"))[0]
    assert result["authority_state"] == fields["authority_state"] == "proposal"
    assert fields["derived_by"] == "synthesis"
    assert "accepted_by" not in fields and "evidence_role" not in fields


def test_no_acceptance_by_silence_for_debriefs(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    debrief_id, draft, _ = _publish_debrief(vault)
    before = draft.read_bytes()
    far_future = datetime.now(timezone.utc) + timedelta(days=3650)
    monkeypatch.setattr(create, "_now", lambda: far_future)

    for _ in range(2):
        listed = review.list_fresh_debriefs(vault)

    assert [item["review_state"] for item in listed] == ["draft"]
    assert draft.read_bytes() == before
    assert "expires" not in load_frontmatter(before.decode("utf-8"))[0]
    assert _receipts(draft, review.REVIEWED_EVENT) == _receipts(draft, review.DISMISSED_EVENT) == []


def test_review_disposition_idempotent(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    debrief_id, draft, _ = _publish_debrief(vault)
    client = TestClient(app)

    first = client.post(f"/api/companion/episode-debriefs/{debrief_id}/review", json={"disposition": "dismissed"})
    flipped = draft.read_bytes()
    second = client.post(f"/api/companion/episode-debriefs/{debrief_id}/review", json={"disposition": "dismissed"})

    assert first.json()["changed"] is True and second.json()["changed"] is False
    assert first.json()["receipt"] == second.json()["receipt"]
    assert draft.read_bytes() == flipped
    assert len(_receipts(draft, review.DISMISSED_EVENT)) == 1
    # A different disposition never overwrites the first one.
    conflict = client.post(f"/api/companion/episode-debriefs/{debrief_id}/review", json={"disposition": "accepted"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "episode_debrief_already_disposed"
    assert draft.read_bytes() == flipped and _receipts(draft, review.REVIEWED_EVENT) == []

    # Interrupted first click (flip committed, receipt lost): a re-click recovers
    # exactly one receipt without flipping again.
    other_id, other, _ = _publish_debrief(vault)
    real = review._ensure_receipt
    monkeypatch.setattr(review, "_ensure_receipt", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        review.review_debrief(other_id, "accepted", vault_root=vault, write_guard=HEALTHY)
    monkeypatch.setattr(review, "_ensure_receipt", real)
    assert load_frontmatter(other.read_text(encoding="utf-8"))[0]["review_state"] == "reviewed"
    recovered = review.review_debrief(other_id, "accepted", vault_root=vault, write_guard=HEALTHY)
    assert recovered["changed"] is False
    assert [r["payload"]["debrief_id"] for r in _receipts(other, review.REVIEWED_EVENT)] == [other_id]


def test_review_refusals_leave_debrief_unchanged(vault: Path) -> None:
    debrief_id, draft, _ = _publish_debrief(vault)
    before = draft.read_bytes()
    blocked = WriteGuard(lambda: {"state": "safe_mode", "reason": "operator hold"})
    with pytest.raises(WritesBlockedError):
        review.review_debrief(debrief_id, "accepted", vault_root=vault, write_guard=blocked)
    with pytest.raises(review.DebriefNotFoundError):
        review.review_debrief(debrief_id_for_episode("ep-missing"), "accepted", vault_root=vault, write_guard=HEALTHY)
    with pytest.raises(review.DebriefNotFoundError):
        review.review_debrief("../../escape", "accepted", vault_root=vault, write_guard=HEALTHY)
    # Tampered publication (integrity mismatch) is not reviewable.
    integrity = create._draft_integrity_path(draft)
    record = json.loads(integrity.read_text(encoding="utf-8"))
    integrity.write_text(json.dumps({**record, "draft_sha256": "0" * 64}), encoding="utf-8")
    response = TestClient(app).post(f"/api/companion/episode-debriefs/{debrief_id}/review",
                                    json={"disposition": "dismissed"})
    assert response.status_code == 404
    assert draft.read_bytes() == before
    assert TestClient(app).post(f"/api/companion/episode-debriefs/{debrief_id}/review",
                                json={"disposition": "deleted"}).status_code == 422
