"""Invariant probe: episode_ref threading into the metadata bundle + derivation survival.

Invariant registry: docs/testing/invariant-tests.md :: observation_episode_binding_survives
Issue: #3178 (ERE-03). Spec: docs/EPISODE_RESOLUTION_ENGINE/THREAD_EPISODE_REF_INTO_METADATA_BUNDLE.md
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
    # (mimer_runtime.dri.derive_segment), not merely in schema validation. Real episode-id assignment
    # is out of scope here (ERE-05), so the bound/pending sources below are fabricated and injected
    # into the capture registry the way a future assignment stage would leave them -- the point of
    # this probe is that derive_segment must not drop or alter whatever binding the source carries.
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
