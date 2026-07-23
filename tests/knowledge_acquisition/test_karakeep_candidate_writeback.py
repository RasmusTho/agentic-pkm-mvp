"""Mimer reading-candidate writeback for the Karakeep handoff (KMA-04, #3375).

Exercises the real production call site
``app.heimdal.candidate_projection.project_pending_candidates`` end to end
against the in-memory observation log: published Karakeep evidence becomes a
governed, review-required ``reading_source_note`` per immutable
``observation_id``, written behind WriteGuard, with a contiguous-durable-prefix
consumer cursor. No Karakeep egress, no companion capture.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal import candidate_projection
from app.heimdal.candidate_projection import (
    CANDIDATE_CONSUMER_ID,
    READING_ARTIFACT_CLASS,
    project_pending_candidates,
)
from app.heimdal.cursor_store import get_cursor, reset_memory_cursor_store
from app.heimdal.observation_log import read_observations_from, reset_memory_observation_log
from app.heimdal.publish import publish_observation
from app.heimdal.quarantine import FENCE_CLOSE, FENCE_OPEN
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_HEX = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_memory_observation_log()
    reset_memory_cursor_store()
    yield
    reset_memory_observation_log()
    reset_memory_cursor_store()


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


def _content_hex(seed: str) -> str:
    return (seed * 64)[:64]


def _karakeep_payload(
    item_id: str,
    content_seed: str,
    *,
    item_kind: str = "link",
    source_url: str | None = "https://example.com/read",
    content: str | None = "a saved note",
    tags: tuple[str, ...] = (),
    tombstone: bool = False,
    sequence: int = 0,
    supersedes: str | None = None,
    revision_of: str | None = None,
) -> tuple[str, dict]:
    episode_id = f"karakeep:{item_id}"
    content_hex = _content_hex(content_seed)
    profile_hex = _content_hex("c")
    observation_id = f"{episode_id}:{content_hex}:{profile_hex}"
    karakeep_block: dict = {
        "item_kind": item_kind,
        "source_item_identity": episode_id,
        "tombstone": tombstone,
    }
    if source_url and not tombstone:
        karakeep_block["source_url"] = source_url
    if tags:
        karakeep_block["tags"] = list(tags)
    payload = {
        "observation_id": observation_id,
        "episode_id": episode_id,
        "sequence": sequence,
        "supersedes": supersedes,
        "revision_of": revision_of,
        "content": None if tombstone else content,
        "raw_ref": f"raw:karakeep:{item_id}:{content_hex[:8]}",
        "scope_hint": "operator_reading_inbox",
        "content_structure": {"karakeep": karakeep_block},
        "provenance": {
            "sensor": "karakeep_rest",
            "capture_chain": ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"],
            "content_identity": f"sha256:{content_hex}",
            "raw_ref": f"raw:karakeep:{item_id}:{content_hex[:8]}",
        },
    }
    return observation_id, payload


def _publish(observation_id: str, payload: dict) -> None:
    publish_observation(
        topic=HEIMDAL_OBSERVATION_PUBLISHED,
        observation_id=observation_id,
        payload=payload,
        source="heimdal_karakeep_adapter",
        stage_versions={"karakeep_adapter": "contract-v1"},
    )


def _frontmatter(vault: VaultContext, artifact_path: str) -> tuple[dict, str]:
    raw = (Path(vault.active_vault_path) / artifact_path).read_text(encoding="utf-8")
    front, _, body = raw.removeprefix("---\n").partition("\n---\n")
    return yaml.safe_load(front), body


# ---------------------------------------------------------------------------
# AC1
# ---------------------------------------------------------------------------


def test_link_note_highlight_mapping_preserves_evidence_and_provenance(tmp_path: Path) -> None:
    oid_link, p_link = _karakeep_payload("item-link", "a", item_kind="link", source_url="https://example.com/a", content="my saved thought", tags=("ai", "reading"))
    oid_note, p_note = _karakeep_payload("item-note", "b", item_kind="note", source_url=None, content="a standalone note body")
    oid_hl, p_hl = _karakeep_payload("item-hl", "d", item_kind="highlight", source_url="https://example.com/h", content="a highlighted passage")
    _publish(oid_link, p_link)
    _publish(oid_note, p_note)
    _publish(oid_hl, p_hl)

    vault = _vault(tmp_path / "vault")
    results = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())

    assert [r.status for r in results] == ["written", "written", "written"]
    by_oid = {r.observation_id: r for r in results}

    fm_link, body_link = _frontmatter(vault, by_oid[oid_link].artifact_path)
    assert fm_link["artifact_class"] == READING_ARTIFACT_CLASS
    assert fm_link["provenance"]["sensor"] == "karakeep_rest"
    assert fm_link["provenance"]["observation_id"] == oid_link
    assert fm_link["provenance"]["content_identity"] == p_link["provenance"]["content_identity"]
    assert fm_link["source"]["url"] == "https://example.com/a"
    assert fm_link["source"]["item_kind"] == "link"
    assert fm_link["source"]["tags"] == ["ai", "reading"]
    assert fm_link["authority"] == {"source_authoritative": False, "ai_generated": True, "requires_review": True}
    assert fm_link["review_state"] == "draft"
    assert fm_link["triage_state"] == "captured"
    # Observed text is present only as fenced, quarantined evidence (no fabricated fields).
    assert FENCE_OPEN in body_link and FENCE_CLOSE in body_link
    assert "my saved thought" in body_link
    assert "## Human takeaways" in body_link

    fm_note, body_note = _frontmatter(vault, by_oid[oid_note].artifact_path)
    assert fm_note["source"]["item_kind"] == "note"
    assert "a standalone note body" in body_note

    fm_hl, body_hl = _frontmatter(vault, by_oid[oid_hl].artifact_path)
    assert fm_hl["source"]["item_kind"] == "highlight"
    assert "a highlighted passage" in body_hl

    # Deterministic, distinct per-item paths under the reading directory.
    for result in results:
        assert result.artifact_path.startswith("Sources/Reading/Karakeep/")
    assert len({r.artifact_path for r in results}) == 3


# ---------------------------------------------------------------------------
# AC2
# ---------------------------------------------------------------------------


def test_reading_candidate_is_review_required_and_first_write_wins(tmp_path: Path) -> None:
    oid, payload = _karakeep_payload("item-fw", "a", content="original evidence")
    _publish(oid, payload)
    vault = _vault(tmp_path / "vault")

    # advance=False keeps the same rows readable so we can assert idempotent
    # replay of the SAME revision (cursor-advance semantics are covered elsewhere).
    first = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard(), advance=False)
    assert first[0].status == "written"
    note_path = Path(vault.active_vault_path) / first[0].artifact_path

    fm, _ = _frontmatter(vault, first[0].artifact_path)
    assert fm["authority"]["requires_review"] is True
    assert fm["authority"]["source_authoritative"] is False

    # A human reviews the note in place (frontmatter provenance preserved).
    human_edited = note_path.read_text(encoding="utf-8") + "\nMy own human takeaway.\n"
    note_path.write_text(human_edited, encoding="utf-8")

    # Replaying the same revision is already_exists and never overwrites the
    # human edit (first-write-wins).
    second = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard(), advance=False)
    assert second[0].status == "already_exists"
    assert "My own human takeaway." in note_path.read_text(encoding="utf-8")

    # A path occupied by a foreign (non-matching) artifact is never overwritten.
    oid2, payload2 = _karakeep_payload("item-occupied", "b", content="evidence")
    _publish(oid2, payload2)
    row2 = next(r for r in read_observations_from(0) if r.envelope["payload"]["observation_id"] == oid2)
    reading_path = candidate_projection.reading_candidate_note_path(
        candidate_projection.build_reading_candidate(row2)
    )
    occupied = Path(vault.active_vault_path) / reading_path
    occupied.parent.mkdir(parents=True, exist_ok=True)
    occupied.write_text("a pre-existing human note, not a candidate", encoding="utf-8")
    blocked = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard(), advance=False)
    occupied_result = next(r for r in blocked if r.observation_id == oid2)
    assert occupied_result.status == "blocked"
    assert "a pre-existing human note, not a candidate" in occupied.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC3
# ---------------------------------------------------------------------------


def test_reading_candidate_uses_kap_writeback_not_capture(tmp_path: Path) -> None:
    module_path = Path(candidate_projection.__file__)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # The governed write path is WriteGuard + write_note_relative -- never
    # companion capture or the /api/capture route family (KMA-INV boundary).
    forbidden = ("app.heimdal.capture_adapter", "app.heimdal.capture_note", "app.heimdal.capture_runtime", "app.api.routes")
    assert not any(name.startswith(forbidden) for name in imported)
    assert "app.write_guard" in imported
    assert "app.knowledge.write_ops" in imported
    source = module_path.read_text(encoding="utf-8")
    assert "/api/capture" not in source

    # WriteGuard actually gates the write: a blocked guard yields a blocked,
    # re-runnable result rather than a silent write.
    oid, payload = _karakeep_payload("item-guard", "a")
    _publish(oid, payload)
    vault = _vault(tmp_path / "vault")
    blocked = project_pending_candidates(vault_context=vault, write_guard=_blocking_guard())
    assert blocked[0].status == "blocked"
    assert not list((Path(vault.active_vault_path) / "Sources/Reading/Karakeep").glob("*.md")) if (Path(vault.active_vault_path) / "Sources/Reading/Karakeep").exists() else True


# ---------------------------------------------------------------------------
# AC5 (blocked/idempotent) + KMA-01 batch (two revisions + tombstone) + prefix
# ---------------------------------------------------------------------------


def test_blocked_write_retries_idempotently(tmp_path: Path) -> None:
    oid, payload = _karakeep_payload("item-retry", "a")
    _publish(oid, payload)
    vault = _vault(tmp_path / "vault")

    blocked = project_pending_candidates(vault_context=vault, write_guard=_blocking_guard())
    assert blocked[0].status == "blocked"
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 0

    retried = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())
    assert retried[0].status == "written"
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 1

    again = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())
    assert again == []  # nothing new; cursor already past it
    notes = list((Path(vault.active_vault_path) / "Sources/Reading/Karakeep").glob("*.md"))
    assert len(notes) == 1  # no duplicate note


def test_two_revisions_and_tombstone_in_one_batch(tmp_path: Path) -> None:
    oid0, p0 = _karakeep_payload("item-9", "a", content="first version", sequence=0)
    oid1, p1 = _karakeep_payload("item-9", "d", content="edited version", sequence=1, supersedes=oid0)
    oid_tomb, p_tomb = _karakeep_payload("item-9", "e", tombstone=True, sequence=2, supersedes=oid1)
    _publish(oid0, p0)
    _publish(oid1, p1)
    _publish(oid_tomb, p_tomb)

    vault = _vault(tmp_path / "vault")
    results = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())

    # One candidate per immutable observation_id -- NOT folded onto the shared
    # episode. Three distinct notes at three distinct paths.
    assert [r.status for r in results] == ["written", "written", "written"]
    assert len({r.artifact_path for r in results}) == 3
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 3

    by_oid = {r.observation_id: r for r in results}
    fm0, body0 = _frontmatter(vault, by_oid[oid0].artifact_path)
    fm1, body1 = _frontmatter(vault, by_oid[oid1].artifact_path)
    fm_t, body_t = _frontmatter(vault, by_oid[oid_tomb].artifact_path)

    assert "first version" in body0
    assert "edited version" in body1
    assert fm1["provenance"]["supersedes"] == oid0
    # Tombstone: review-required, links the prior revision, deletes nothing.
    assert fm_t["tombstone"] is True
    assert fm_t["prior_revision"] == oid1
    assert fm_t["authority"]["requires_review"] is True
    assert "tombstone" in body_t.lower()
    # Prior revisions untouched by the tombstone.
    assert "first version" in (Path(vault.active_vault_path) / by_oid[oid0].artifact_path).read_text(encoding="utf-8")
    assert "edited version" in (Path(vault.active_vault_path) / by_oid[oid1].artifact_path).read_text(encoding="utf-8")


def test_blocked_middle_row_advances_only_durable_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    published = []
    for idx, item in enumerate(("a", "b", "c", "d")):
        oid, payload = _karakeep_payload(f"item-{item}", item, sequence=0)
        _publish(oid, payload)
        published.append(oid)
    vault = _vault(tmp_path / "vault")

    original = candidate_projection.write_reading_candidate_note

    def block_c(candidate, **kwargs):
        if candidate.item_id == "item-c":
            return candidate_projection.CandidateWriteResult(
                status="blocked", artifact_path=None, observation_id=candidate.observation_id, reason="test block"
            )
        return original(candidate, **kwargs)

    monkeypatch.setattr(candidate_projection, "write_reading_candidate_note", block_c)
    partial = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())
    assert [r.status for r in partial] == ["written", "written", "blocked", "written"]
    # Contiguous durable prefix stops at the blocked row: only a, b acknowledged.
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 2

    monkeypatch.setattr(candidate_projection, "write_reading_candidate_note", original)
    replay = project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())
    # c and d replay (never skipped); a and b already advanced, not re-read.
    # d was durably WRITTEN in the partial run (only c was blocked) but not
    # acknowledged past the blocked prefix, so its replay is already_exists --
    # proving the later success was neither skipped nor duplicated (KMA-INV-3).
    assert [r.observation_id for r in replay] == [published[2], published[3]]
    assert [r.status for r in replay] == ["written", "already_exists"]
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 4
    notes = list((Path(vault.active_vault_path) / "Sources/Reading/Karakeep").glob("*.md"))
    assert len(notes) == 4  # a, b, c, d -- no duplicates
