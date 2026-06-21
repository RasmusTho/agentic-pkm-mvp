"""Read-only commitment surface in the companion workspace state.

Governing issue: #2074 (parent #1960) — Commitment Surfacing slice 2.
Spec: docs/COMMITMENT_SURFACING/EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md
Contracts:
- docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md (commitment layer is read/proposal-only here)
- docs/CONCEPTS/STATE_AXES_CONTRACT.md (commitment state never collapsed into review_state/maturity)

These tests pin the read-only companion-route surface that exposes the durable
commitments persisted in slice 1 (#2073):

1. The companion workspace state exposes active commitments (next_action / waiting /
   review_return) as a read-only field on ``RuntimeState``.
2. The surface is populated from the durable source (``load_commitments``), not from
   ephemeral ``AgentState`` — asserted at the route production call site.
3. The surface is read-only: an explicit read-only marker is present and reading it
   triggers no write or state transition.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.domain.commitments import CommitmentRecord
from app.services.commitment_persistence import persist_commitment
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.api._vault_test_helpers import bind_selected_vault


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def vault_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A vault with one active note, selected in the VaultManager like the other
    companion workspace tests (Option-2: ``_active_companion_vault_root`` requires
    a selected vault)."""
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    note = tmp_path / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: note-uuid-commitments\n---\n\n# Test Note\n\nBody.\n",
        encoding="utf-8",
    )
    return tmp_path


def _vault_context(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-default",
        active_vault_name="Vault Default",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _persist(root: Path, record: CommitmentRecord) -> None:
    persist_commitment(record, vault_context=_vault_context(root), write_guard=_allowing_guard())


def _seed_commitments(root: Path) -> None:
    """Persist durable commitment artefacts spanning the surfaced kinds/states."""
    _persist(
        root,
        CommitmentRecord(
            commitment_id="c-next",
            commitment_kind="next_action",
            state="next",
            target_ref="projects/hiring.md",
            summary="Reply to Alice about the offer",
        ),
    )
    _persist(
        root,
        CommitmentRecord(
            commitment_id="c-waiting",
            commitment_kind="waiting",
            state="waiting",
            target_ref="projects/vendor.md",
            summary="Awaiting vendor quote",
        ),
    )
    _persist(
        root,
        CommitmentRecord(
            commitment_id="c-review",
            commitment_kind="review_return",
            state="open",
            target_ref="projects/weekly.md",
            summary="Weekly review return",
        ),
    )
    # A done commitment must NOT appear on the active surface.
    _persist(
        root,
        CommitmentRecord(
            commitment_id="c-done",
            commitment_kind="next_action",
            state="done",
            summary="Already closed",
        ),
    )


def _workspace(client: TestClient, note_path: str = "notes/note.md"):
    return client.get("/api/companion/workspace", params={"note_path": note_path})


def test_commitments_in_workspace_state(client: TestClient, vault_root: Path) -> None:
    """AC1: the workspace state exposes active commitments by kind/state, read-only."""
    _seed_commitments(vault_root)

    resp = _workspace(client)
    assert resp.status_code == 200
    commitments = resp.json()["runtime"]["commitments"]

    # The three active buckets are present and contain the right commitments.
    next_ids = {item["commitment_id"] for item in commitments["next"]}
    waiting_ids = {item["commitment_id"] for item in commitments["waiting"]}
    review_ids = {item["commitment_id"] for item in commitments["review_return"]}
    assert "c-next" in next_ids
    assert "c-waiting" in waiting_ids
    assert "c-review" in review_ids

    # Done commitments are not surfaced on the active landscape.
    all_ids = next_ids | waiting_ids | review_ids
    assert "c-done" not in all_ids

    # Items keep commitment semantics (kind/state), never collapsed into note axes.
    next_item = next(item for item in commitments["next"] if item["commitment_id"] == "c-next")
    assert next_item["kind"] == "next_action"
    assert next_item["state"] == "next"
    assert next_item["summary"] == "Reply to Alice about the offer"
    assert next_item["target_ref"] == "projects/hiring.md"

    # Not degraded when the durable read succeeds.
    assert commitments["degraded"] is False


def test_commitment_provenance_fields_and_freshness(
    client: TestClient, vault_root: Path
) -> None:
    """Optional provenance (waiting_on / waiting_since, review_cadence /
    last_reviewed) is surfaced, ``last_reviewed`` is given a server-computed
    relative form, and the surface carries an ``as_of`` freshness stamp.

    The relative calc is server-side (so the render stays clockless); an absent
    value stays ``None`` and is never fabricated.
    """
    import datetime

    today = datetime.datetime.now(datetime.timezone.utc).date()
    reviewed_3d = (today - datetime.timedelta(days=3)).isoformat()

    _persist(
        vault_root,
        CommitmentRecord(
            commitment_id="c-waiting",
            commitment_kind="waiting",
            state="waiting",
            target_ref="projects/vendor.md",
            summary="Awaiting vendor quote",
            waiting_on="Vendor (Acme) reply",
            waiting_since="2026-06-10",
        ),
    )
    _persist(
        vault_root,
        CommitmentRecord(
            commitment_id="c-review",
            commitment_kind="review_return",
            state="open",
            target_ref="projects/weekly.md",
            summary="Weekly review return",
            review_cadence="weekly",
            last_reviewed=reviewed_3d,
        ),
    )

    commitments = _workspace(client).json()["runtime"]["commitments"]

    waiting = next(i for i in commitments["waiting"] if i["commitment_id"] == "c-waiting")
    assert waiting["waiting_on"] == "Vendor (Acme) reply"
    assert waiting["waiting_since"] == "2026-06-10"
    # Review-only provenance is absent on a waiting item (never fabricated).
    assert waiting["review_cadence"] is None
    assert waiting["last_reviewed_relative"] is None

    review = next(i for i in commitments["review_return"] if i["commitment_id"] == "c-review")
    assert review["review_cadence"] == "weekly"
    assert review["last_reviewed"] == reviewed_3d
    assert review["last_reviewed_relative"] == "3d ago"

    # Whole-surface freshness stamp present on a healthy read.
    assert commitments["as_of"]


def test_degraded_surface_has_no_confident_freshness(
    client: TestClient, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded read carries no ``as_of`` — freshness must not be asserted when
    the durable source could not be read."""

    def _failing_load(*, vault_context):  # type: ignore[no-untyped-def]
        raise RuntimeError("vault read exploded")

    monkeypatch.setattr(companion_module, "load_commitments", _failing_load)
    commitments = _workspace(client).json()["runtime"]["commitments"]
    assert commitments["degraded"] is True
    assert commitments["as_of"] is None


def test_commitments_surface_reads_durable_source_not_agent_state(
    client: TestClient, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: the route populates the surface from the durable query path
    (``load_commitments``), not ``AgentState`` — asserted at the route call site.

    The route must invoke the durable loader, and commitments persisted to the vault
    (with no live ``AgentState`` whatsoever) must appear in the response.
    """
    _seed_commitments(vault_root)

    # Spy on the durable loader to prove the route production call site uses it.
    calls: list[object] = []
    real_load = companion_module.load_commitments

    def _spy_load(*, vault_context):  # type: ignore[no-untyped-def]
        calls.append(vault_context)
        return real_load(vault_context=vault_context)

    monkeypatch.setattr(companion_module, "load_commitments", _spy_load)

    resp = _workspace(client)
    assert resp.status_code == 200

    # The durable loader was called from the workspace production path.
    assert calls, "workspace route did not call the durable commitment loader"

    # The durably-persisted commitment is surfaced even though no AgentState exists.
    commitments = resp.json()["runtime"]["commitments"]
    next_ids = {item["commitment_id"] for item in commitments["next"]}
    assert "c-next" in next_ids
    assert commitments["source"] == "vault.commitment_artefacts"


def test_commitments_surface_durable_across_repeated_reads(
    client: TestClient, vault_root: Path
) -> None:
    """The surface is identical across two successive reads (durable, not flickering
    transient state) — the durability guarantee slice 1 establishes (CI-1)."""
    _seed_commitments(vault_root)

    first = _workspace(client).json()["runtime"]["commitments"]
    second = _workspace(client).json()["runtime"]["commitments"]
    # ``as_of`` is a per-read freshness stamp (now.isoformat(timespec="seconds"));
    # two reads straddling a one-second boundary differ by a second even though the
    # durable payload is identical. Assert freshness is present on both reads, then
    # compare the durable payload with the freshness stamp excluded.
    assert first["as_of"] is not None
    assert second["as_of"] is not None
    first_durable = {k: v for k, v in first.items() if k != "as_of"}
    second_durable = {k: v for k, v in second.items() if k != "as_of"}
    assert first_durable == second_durable


def test_commitment_surface_is_read_only(
    client: TestClient, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: explicit read-only marker, and the read triggers no write/transition."""
    _seed_commitments(vault_root)

    # Any commitment write/transition during a read is a contract violation.
    def _boom_persist(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("reading the commitment surface must not persist/mutate")

    def _boom_transition(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("reading the commitment surface must not transition state")

    monkeypatch.setattr(companion_module, "persist_commitment", _boom_persist, raising=False)
    if hasattr(companion_module, "apply_commitment_state_transition"):
        monkeypatch.setattr(
            companion_module, "apply_commitment_state_transition", _boom_transition, raising=False
        )

    resp = _workspace(client)
    assert resp.status_code == 200
    commitments = resp.json()["runtime"]["commitments"]

    # Explicit read-only / authority-role markers, matching the other companion
    # read surfaces (WorkspaceOrientationGuards / WorkspaceOrientationMemory).
    assert commitments["read_only"] is True
    assert commitments["authority_role"] == "derived"


def test_commitment_surface_degrades_honestly_on_read_failure(
    client: TestClient, vault_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-task invariant CI-2: a failed durable read degrades with a reason,
    never a confident empty surface that contradicts the durable source."""

    def _failing_load(*, vault_context):  # type: ignore[no-untyped-def]
        raise RuntimeError("vault read exploded")

    monkeypatch.setattr(companion_module, "load_commitments", _failing_load)

    resp = _workspace(client)
    assert resp.status_code == 200
    commitments = resp.json()["runtime"]["commitments"]

    assert commitments["degraded"] is True
    assert commitments["degraded_reason"]
    # Still read-only even when degraded; never a confident empty claim.
    assert commitments["read_only"] is True
