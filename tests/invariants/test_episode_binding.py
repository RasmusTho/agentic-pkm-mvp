"""Invariant probe: episode_ref threading into the metadata bundle + derivation survival.

Invariant registry: docs/testing/invariant-tests.md :: observation_episode_binding_survives
Issue: #3178 (ERE-03), extended by #3180 (ERE-05, assignment end-to-end case).
Spec: docs/EPISODE_RESOLUTION_ENGINE/THREAD_EPISODE_REF_INTO_METADATA_BUNDLE.md,
docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md
Doctrine: docs/architecture/semantic-dimensions.md :: episode_ref; ADR-0051 (Episode as ontological
primitive), ADR-0029 (orthogonal semantic roles).

House convention: the probe function name matches the registry invariant id
(``test_observation_episode_binding_survives``). Modeled on
``tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation`` and
``tests/invariants/test_dri_runtime.py``, but — unlike those xfail/future-runtime skeletons —
``mimer_runtime.capture``/``mimer_runtime.dri`` are already implemented, so these tests exercise the
real production derivation path directly rather than an ``xfail`` stub.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest
from jsonschema.exceptions import ValidationError

from tests.invariants._helpers import assert_validates, load_schema

from mimer_runtime import capture, corpus, dri
from mimer_runtime.metadata import MetadataBundle

# A minimal, otherwise-valid bundle (object_type="artifact" -- not a derived type, so derived_from is
# not required) missing only episode_ref, for schema-shape probing.
_BASE_BUNDLE: dict[str, object] = {
    "object_id": "artifact:ep-shape-1",
    "object_type": "artifact",
    "scope_id": "scope:work/project-alpha",
    "source_role": "work_project",
    "authority_state": "captured",
    "evidence_role": "reference",
    "sensitivity": "internal",
    "suppression_state": "visible",
    "created_by": "p-1",
    "created_at": "2026-07-11T00:00:00+00:00",
    "provenance_event_ids": ["prov:1"],
}


def test_episode_ref_schema_shapes() -> None:
    # AC1: the bundle schema accepts 'unbound', 'pending', and a non-empty episode_id array; it
    # rejects a bundle with no episode_ref at all and rejects an empty array.
    assert_validates({**_BASE_BUNDLE, "episode_ref": "unbound"}, "metadata-bundle.schema.json")
    assert_validates({**_BASE_BUNDLE, "episode_ref": "pending"}, "metadata-bundle.schema.json")
    assert_validates({**_BASE_BUNDLE, "episode_ref": ["ep-standup-1"]}, "metadata-bundle.schema.json")
    assert_validates(
        {**_BASE_BUNDLE, "episode_ref": ["ep-standup-1", "ep-standup-2"]},
        "metadata-bundle.schema.json",
    )

    # episode_ref is now a required field -- a bundle carrying none must fail validation.
    with pytest.raises(ValidationError):
        assert_validates(dict(_BASE_BUNDLE), "metadata-bundle.schema.json")

    # An empty array is rejected -- 'unbound' is the honest way to say "no episode is known".
    with pytest.raises(ValidationError):
        assert_validates({**_BASE_BUNDLE, "episode_ref": []}, "metadata-bundle.schema.json")

    # Any string other than the two sentinels is rejected (not a free-form value).
    with pytest.raises(ValidationError):
        assert_validates({**_BASE_BUNDLE, "episode_ref": "bogus"}, "metadata-bundle.schema.json")


def test_derived_types_allof_requires_episode_ref_like_derived_from() -> None:
    # Schema-shape companion to AC1/AC2: the derived-types allOf conditional (object_type in
    # [segment, projection, retrieval_result, context_item] requires derived_from) is extended to
    # also require episode_ref, mirroring how the two dimensions both survive derivation.
    schema = load_schema("metadata-bundle.schema.json")
    derived_rule = next(
        rule for rule in schema["allOf"] if "derived_from" in json.dumps(rule.get("then", {}))
    )
    assert set(derived_rule["then"].get("required", [])) >= {"derived_from", "episode_ref"}


def test_observation_episode_binding_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: observation_episode_binding_survives
    # AC2 (enforcement): episode_ref survives segment derivation on the PRODUCTION derivation path
    # (mimer_runtime.dri.derive_segment), not merely in schema validation. The bound/pending sources
    # in this first block are still hand-fabricated (mimer_runtime is a corpus-backed, in-memory-only
    # test slice -- docs/MIMER_RUNTIME_SLICE_1/README.md -- disjoint from the real app/episodes
    # runtime, so ERE-05's real assignment logic cannot literally write into this registry); the
    # point of THIS block is that derive_segment must not drop or alter whatever binding the source
    # carries, whatever produced it. The second block below (AC5, ERE-05 #3180) closes the gap: it
    # calls the REAL app.episodes.assignment.compute_assignments rule to produce a binding, then
    # feeds that real decision through this same production derivation path end to end.
    src = capture.capture(text="a bounded situation", principal_id="p-episode-bound")

    bound_bundle = dataclasses.replace(
        src.metadata_bundle,
        object_id="artifact:ep-bound-src",
        episode_ref=["ep-standup-2026-07-11", "ep-followup-2026-07-11"],
    )
    pending_bundle = dataclasses.replace(
        src.metadata_bundle, object_id="artifact:ep-pending-src", episode_ref="pending"
    )
    unbound_bundle = dataclasses.replace(src.metadata_bundle, object_id="artifact:ep-unbound-src")

    registry = {
        b.object_id: capture.CapturedArtifact(metadata_bundle=b, text=src.text)
        for b in (bound_bundle, pending_bundle, unbound_bundle)
    }
    monkeypatch.setattr(capture, "get_captured", lambda object_id: registry.get(object_id))

    # A real (multi-)episode binding survives derivation intact.
    seg_bound = dri.derive_segment(artifact_id=bound_bundle.object_id)
    assert list(seg_bound.metadata_bundle.episode_ref) == [
        "ep-standup-2026-07-11",
        "ep-followup-2026-07-11",
    ]
    assert_validates(seg_bound.metadata_bundle.to_dict(), "metadata-bundle.schema.json")

    # A 'pending' (unconfirmed) binding survives too -- it must not silently vanish or get upgraded
    # to a confirmed binding at the first derivation step (ADR-0051 section 5: opt-out segmentation).
    seg_pending = dri.derive_segment(artifact_id=pending_bundle.object_id)
    assert seg_pending.metadata_bundle.episode_ref == "pending"

    # The trivial 'unbound' case is preserved too (no silent re-stamping to something else).
    seg_unbound = dri.derive_segment(artifact_id=unbound_bundle.object_id)
    assert seg_unbound.metadata_bundle.episode_ref == "unbound"


def test_observation_episode_binding_survives__ere05_end_to_end(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AC5 (ERE-05, #3180): the end-to-end case added to the observation_episode_binding_survives
    # probe -- assign (the REAL production assignment rule AND the REAL guarded bundle-write seam,
    # Finding 1 / review round 2) -> chunk/derive -> binding present on the derived bundle.
    #
    # Finding 1 (CRITICAL, review round 2): the PRIOR version of this test computed a real decision
    # via app.episodes.assignment.compute_assignments but then hand-stamped it onto a
    # mimer_runtime bundle via dataclasses.replace -- exercising no real write path at all (the
    # ledger-only commit never touched the artifact's own bundle, so retrieval would have kept
    # returning 'unbound' forever). This version adds a first block that runs the REAL
    # app.episodes.assignment.commit_assignment_diff -- the artifact's persisted bundle (a real
    # vault note's frontmatter, read back from disk, plus the DB-side store_objects/
    # store_vector_index payload rows, captured here since a live Postgres isn't available in this
    # lane) actually shows episode_ref upgraded to `[episode_id]` (the concrete, "pending" -- not
    # yet ERE-07-accepted -- binding; docs/architecture/semantic-dimensions.md :: episode_ref).
    # Only THEN, in the second block (unchanged in spirit from before), does that SAME real
    # episode_id get carried into a MetadataBundle the same way a real capture/assignment pipeline
    # would and pushed through mimer_runtime.dri.derive_segment -- mimer_runtime is a
    # corpus-backed, in-memory-only test slice (docs/MIMER_RUNTIME_SLICE_1/README.md) disjoint from
    # the real app/episodes runtime, so it cannot itself be the target of the real write; it is
    # still the only available derivation-survival probe in this codebase, so it remains the proof
    # that the REAL write's output specifically survives derivation.
    from app.episodes import assignment as assignment_module
    from app.episodes.assignment import (
        ArtifactCandidate,
        BASIS_PROVENANCE,
        BINDING_TABLE,
        EpisodeBoundsRecord,
        PROVENANCE_CONFIDENCE,
        commit_assignment_diff,
        compute_assignments,
    )
    from app.write_guard import WriteGuard
    from scripts.yaml_roundtrip import load_frontmatter

    episode = EpisodeBoundsRecord(
        episode_id="ep-aaaaaaaa-2222-4333-8444-555555555555",
        scope="work",
        start=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        derived_from=("vault.activity:anchor-e2e",),
    )
    artifact = ArtifactCandidate(
        artifact_ref="vault.activity:anchor-e2e",
        scope="work",
        observed_at=datetime(2026, 7, 11, 9, 15, tzinfo=timezone.utc),
    )

    decisions = compute_assignments([artifact], [episode])
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.basis == BASIS_PROVENANCE
    assert decision.confidence == PROVENANCE_CONFIDENCE

    # --- Block 1: the REAL production bundle-write path (Finding 1) --------------------------
    vault_root = tmp_path / "vault"
    note_path = vault_root / "notes" / "anchor-e2e.md"
    note_path.parent.mkdir(parents=True)
    object_id = "33333333-3333-4333-8333-333333333333"
    note_path.write_text(f"---\nuuid: {object_id}\ntitle: t\n---\n\nbody text\n", encoding="utf-8")

    monkeypatch.setattr(
        assignment_module,
        "_resolve_bundle_object_id_and_note_path",
        lambda artifact_ref, *, vault_root: (object_id, note_path),
    )

    store_rows: dict[tuple[str, str], dict] = {
        ("store_objects", object_id): {"kind": "note"},
        ("store_vector_index", object_id): {"kind": "note"},
    }

    class _FakeCursor:
        def __init__(self) -> None:
            self._result = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            stripped = sql.strip()
            if "to_regclass" in stripped:
                self._result = (BINDING_TABLE,)
            elif stripped.startswith("SELECT payload FROM store_"):
                table = "store_objects" if "store_objects" in stripped else "store_vector_index"
                row = store_rows.get((table, params[0]))
                self._result = (json.dumps(row),) if row is not None else None
            elif stripped.startswith("UPDATE store_"):
                # Finding 3: targeted jsonb_set on the episode_ref key only, never a full-column
                # overwrite (params carry the episode_ref value, not a whole payload).
                table = "store_objects" if "store_objects" in stripped else "store_vector_index"
                assert "jsonb_set" in stripped and "'{episode_ref}'" in stripped
                episode_ref_json, obj_id = params
                existing = store_rows.get((table, obj_id))
                if existing is not None:
                    existing["episode_ref"] = json.loads(episode_ref_json)
                self._result = None
            else:
                self._result = None

        def fetchone(self):
            return self._result

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(assignment_module, "conn_rw", lambda *a, **k: _FakeConn())
    allow_guard = WriteGuard(lambda: {"state": "healthy", "reason": None})

    result = commit_assignment_diff(
        [decision], [], write_guard=allow_guard, vault_root=vault_root
    )
    assert result == {"pending": 1, "corrected": 0}

    # DB-side bundle rows: both actually upgraded from nothing to the real pending id.
    assert store_rows[("store_objects", object_id)]["episode_ref"] == [decision.episode_id]
    assert store_rows[("store_vector_index", object_id)]["episode_ref"] == [decision.episode_id]

    # Vault-serialized bundle: the note's OWN frontmatter, read back from disk.
    frontmatter, _body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["episode_ref"] == [decision.episode_id]

    # --- Block 2: derivation-survival proof for that SAME real decision (mimer_runtime probe) ---
    src = capture.capture(text="a real assignment decision", principal_id="p-episode-ere05")
    assigned_bundle = dataclasses.replace(
        src.metadata_bundle,
        object_id="artifact:ep-ere05-assigned-src",
        episode_ref=[decision.episode_id],
    )
    registry = {assigned_bundle.object_id: capture.CapturedArtifact(metadata_bundle=assigned_bundle, text=src.text)}
    monkeypatch.setattr(capture, "get_captured", lambda object_id: registry.get(object_id))

    seg_assigned = dri.derive_segment(artifact_id=assigned_bundle.object_id)
    assert list(seg_assigned.metadata_bundle.episode_ref) == [decision.episode_id]
    assert_validates(seg_assigned.metadata_bundle.to_dict(), "metadata-bundle.schema.json")


def test_capture_stamps_episode_ref_unbound() -> None:
    # AC3 (call-site assertion): the capture/ingest bundle-minting path stamps episode_ref='unbound'
    # by default (real assignment is ERE-05, out of scope here).
    obj = capture.capture(text="a fresh thought", principal_id="p-episode-3")
    assert obj.metadata_bundle.episode_ref == "unbound"
    assert_validates(obj.metadata_bundle.to_dict(), "metadata-bundle.schema.json")


def test_corpus_stamps_episode_ref_unbound() -> None:
    # Additional producer coverage: mimer_runtime.corpus is also a bundle-minting/ingest path (the
    # fixture corpus loader) and must stamp the same honest default.
    docs = corpus.load_corpus()
    assert docs, "expected at least one corpus doc"
    assert all(d.metadata_bundle.episode_ref == "unbound" for d in docs)


def test_episode_ref_never_upgrades_evidence_role(monkeypatch: pytest.MonkeyPatch) -> None:
    # AC4: episode_ref never feeds evidence_role -- extends the existing no-upgrade posture
    # (tests/invariants/test_dri_runtime.py::test_segment_evidence_role_not_upgraded) to assert an
    # episode_ref-bearing item, even one bound to real episode ids, cannot gain admissibility from
    # its binding. episode_ref is orthogonal to evidence_role/authority_state (semantic-dimensions.md
    # :: episode_ref; ADR-0029), and a 'pending' binding is explicitly not authority either.
    order = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]
    src = capture.capture(text="background material", principal_id="p-episode-4")
    conservative_src = dataclasses.replace(src.metadata_bundle, evidence_role="non_evidence")

    episode_ref_variants: tuple[str | list[str], ...] = ("unbound", "pending", ["ep-1", "ep-2"])
    for index, episode_ref_value in enumerate(episode_ref_variants):
        bound_source = dataclasses.replace(
            conservative_src, object_id=f"artifact:ep4-{index}", episode_ref=episode_ref_value
        )
        artifact = capture.CapturedArtifact(metadata_bundle=bound_source, text=src.text)
        monkeypatch.setattr(
            capture,
            "get_captured",
            lambda object_id, _artifact=artifact: (
                _artifact if object_id == _artifact.metadata_bundle.object_id else None
            ),
        )
        seg = dri.derive_segment(artifact_id=bound_source.object_id)
        assert seg.metadata_bundle.evidence_role == "non_evidence", (
            f"episode_ref={episode_ref_value!r} must not upgrade evidence_role"
        )
        assert order.index(seg.metadata_bundle.evidence_role) <= order.index(
            conservative_src.evidence_role
        )
        # A binding must not upgrade authority_state toward canonical standing either.
        assert seg.metadata_bundle.authority_state == conservative_src.authority_state

    # Direct construction-level check: three otherwise-identical bundles differing only in
    # episode_ref all carry the exact same evidence_role -- the field structurally cannot influence it.
    common_kwargs = dict(
        object_id="artifact:ep4-direct",
        object_type="artifact",
        scope_id="scope:work/project-alpha",
        source_role="work_project",
        authority_state="captured",
        evidence_role="non_evidence",
        sensitivity="internal",
        suppression_state="visible",
        created_by="p-1",
        created_at="2026-07-11T00:00:00+00:00",
        provenance_event_ids=["prov:1"],
    )
    unbound = MetadataBundle(**common_kwargs, episode_ref="unbound")  # type: ignore[arg-type]
    pending = MetadataBundle(**common_kwargs, episode_ref="pending")  # type: ignore[arg-type]
    bound = MetadataBundle(**common_kwargs, episode_ref=["ep-1", "ep-2"])  # type: ignore[arg-type]
    assert unbound.evidence_role == pending.evidence_role == bound.evidence_role == "non_evidence"
