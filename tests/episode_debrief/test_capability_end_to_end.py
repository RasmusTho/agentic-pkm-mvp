"""Episode Debrief capability loop on a fixture: closure -> trigger -> synthesis -> review."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.episode_debrief import review
from app.episode_debrief.trigger import debrief_id_for_episode
from app.expansion import create
from scripts.yaml_roundtrip import load_frontmatter
from tests.api._vault_test_helpers import bind_initialized_vault
from tests.episode_debrief.test_synthesis import episode, run  # noqa: F401  (pytest fixture)

pytestmark = [pytest.mark.pg, pytest.mark.usefixtures("product_model_access_gateway")]


def test_fixture_closure_full_loop(episode, monkeypatch):  # noqa: F811
    db, ep, payload, _ = episode
    debrief_id = debrief_id_for_episode(ep)
    # One closure produced exactly one trigger; a second tick adds none.
    db.tick()
    assert [trigger["episode_id"] for trigger in db.triggers()] == [ep]

    created = run(episode)
    assert created["status"] == "created"
    draft = db.root / created["draft"]
    episode_note = db.root / "episodes" / f"{ep}.md"
    assert load_frontmatter(episode_note.read_text())[0]["debrief_ref"] == [debrief_id]
    body = load_frontmatter(draft.read_text())[1]
    for heading in ("decisions", "commitments", "open_loops", "key_captures"):
        assert f"## {heading}" in body

    bind_initialized_vault(monkeypatch, db.root, channel="test")
    client = TestClient(app)
    fresh = client.get("/api/companion/episode-debriefs").json()["fresh"]
    assert [item["debrief_id"] for item in fresh] == [debrief_id]

    published, episode_bytes = draft.read_text(), episode_note.read_bytes()
    dismissed = client.post(f"/api/companion/episode-debriefs/{debrief_id}/review", json={"disposition": "dismissed"})
    assert dismissed.status_code == 200 and dismissed.json()["review_state"] == "archived"
    assert draft.is_file() and episode_note.read_bytes() == episode_bytes
    receipts = [line for line in (draft.parent / "outbox.jsonl").read_text().splitlines() if review.DISMISSED_EVENT in line]
    assert len(receipts) == 1
    assert client.get("/api/companion/episode-debriefs").json()["fresh"] == []

    # At-least-once trigger redelivery after review is still an idempotent no-op.
    monkeypatch.setattr(create, "_run_cognition", lambda *_: pytest.fail("replay must not regenerate"))
    assert run(episode)["status"] == "already_debriefed"
    after = draft.read_text()
    assert load_frontmatter(after)[0]["review_state"] == "archived"
    assert after == published.replace("review_state: draft", "review_state: archived", 1)
