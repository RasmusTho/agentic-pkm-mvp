"""Executable design check for the Mimer side of the Karakeep handoff (#3372, #3375)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal import candidate_projection
from app.heimdal.candidate_projection import CANDIDATE_CONSUMER_ID, project_pending_candidates
from app.heimdal.cursor_store import get_cursor, reset_memory_cursor_store
from app.heimdal.observation_log import reset_memory_observation_log
from app.heimdal.publish import publish_observation
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    REPO_ROOT
    / "docs"
    / "KARAKEEP_MIMER_ACQUISITION"
    / "DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md"
)


def test_contract_extends_existing_mimer_projector_without_parallel_consumer() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    projector_source = inspect.getsource(candidate_projection.project_pending_candidates)

    assert "## Additive Mimer candidate mapping" in contract
    assert "`reading_source_note`" in contract
    assert "`requires_review: true`" in contract
    assert "`review_state: draft`" in contract
    assert "`Sources/Reading/Karakeep/<item-id>-<revision-prefix>.md`" in contract
    assert "first-write-wins" in contract
    assert "never deletes or overwrites" in contract
    assert "tombstone candidate" in contract

    # The chosen extension point is a shipped production path with the one
    # existing consumer identity and the real guarded materialization call.
    assert candidate_projection.CANDIDATE_CONSUMER_ID == "mimer.candidate_projector"
    assert "read_observations_for_consumer(consumer_id" in projector_source
    assert "write_candidate_note(" in projector_source
    # KMA-04 delivered the contiguous-durable-prefix advance the contract below
    # requires: the projector still advances only through the one sanctioned
    # cursor seam, now across the durable prefix instead of the whole batch.
    assert "advance_cursor_for_consumer(consumer_id, prefix)" in projector_source
    # KMA-01 names the necessary KMA-04 repair rather than claiming the
    # current whole-batch advance is already safe for blocked writes.
    assert "KMA-04 must change that\nbehavior before enabling Karakeep projection" in contract
    assert "advances only the contiguous durable prefix of\nrows" in contract
    assert "blocked middle row followed by a successful row" in contract
    assert "one candidate per immutable\n`observation_id` rather than applying the generic `episode_id` fold" in contract
    assert "two source\nrevisions plus a tombstone in one production-call-site batch test" in contract

    for forbidden in (
        "/api/capture",
        "companion capture",
        "Karakeep MCP",
    ):
        assert f"forbids `{forbidden}`" in contract


def test_consumer_starts_at_handoff_and_owns_only_consumer_cursor(tmp_path: Path) -> None:
    """The Mimer consumer reads only published evidence (zero Karakeep egress /
    re-attribution) and advances only its own cursor after a durable outcome."""
    reset_memory_observation_log()
    reset_memory_cursor_store()
    try:
        # Zero egress: the consumer module never imports the Karakeep source
        # adapter or any network/re-attribution path.
        tree = ast.parse(Path(candidate_projection.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "app.heimdal.karakeep_ingest" not in imported
        assert not any(name in {"httpx", "requests"} for name in imported)

        content_hex = ("a" * 64)
        observation_id = f"karakeep:item-c:{content_hex}:{'c' * 64}"
        publish_observation(
            topic=HEIMDAL_OBSERVATION_PUBLISHED,
            observation_id=observation_id,
            payload={
                "observation_id": observation_id,
                "episode_id": "karakeep:item-c",
                "sequence": 0,
                "content": "saved reading evidence",
                "raw_ref": "raw:karakeep:item-c:aaaa",
                "content_structure": {"karakeep": {"item_kind": "link", "source_item_identity": "karakeep:item-c", "tombstone": False, "source_url": "https://example.com/c"}},
                "provenance": {
                    "sensor": "karakeep_rest",
                    "capture_chain": ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"],
                    "content_identity": f"sha256:{content_hex}",
                },
            },
            source="heimdal_karakeep_adapter",
            stage_versions={"karakeep_adapter": "contract-v1"},
        )

        vault_root = tmp_path / "vault"
        vault_root.mkdir(parents=True, exist_ok=True)
        vault = VaultContext(status="selected", active_vault_id="v", active_vault_name="V", active_vault_path=str(vault_root))

        results = project_pending_candidates(vault_context=vault, write_guard=WriteGuard(lambda: {"state": "healthy"}))
        assert [r.status for r in results] == ["written"]

        # Provenance is reused from the published evidence, not re-derived.
        note = (vault_root / results[0].artifact_path).read_text(encoding="utf-8")
        assert "sensor: karakeep_rest" in note
        assert observation_id in note

        # Advances ONLY its own consumer cursor; a different consumer is untouched.
        assert get_cursor(CANDIDATE_CONSUMER_ID) == 1
        assert get_cursor("some.other.consumer") == 0
    finally:
        reset_memory_observation_log()
        reset_memory_cursor_store()
