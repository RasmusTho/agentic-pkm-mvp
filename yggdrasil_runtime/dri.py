"""DRI stage — derived representations that preserve provenance (no naked segment).

``derive_segment(artifact_id)`` produces a ``Segment`` whose ``MetadataBundle``:

- is ``object_type="segment"`` with a non-empty ``derived_from`` (lineage survives derivation);
- **inherits** ``scope_id`` / ``source_role`` / ``authority_state`` / ``evidence_role`` /
  ``sensitivity`` from the source artifact (not re-stamped fresh);
- preserves the source's provenance and adds a derivation event (``provenance_event_ids`` non-empty).

Source resolution: a captured artifact (``capture.get_captured``) when present — the path the
conformance test exercises — otherwise a synthetic source stub with sane defaults, so the skeleton's
bare ``derive_segment("art-1")`` (an artifact never captured) still yields a coherent inherited
segment. This represents "an artifact not in the in-memory store" (e.g. a pre-existing one).

No naked segment: a ``Segment`` requires a ``MetadataBundle``, and a segment-type bundle requires
``derived_from`` (enforced in ``metadata.MetadataBundle.__post_init__``). ``derive_segment`` is the
production call site that guarantees both. In-memory only; segments are rebuildable, never durable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from yggdrasil_runtime import capture
from yggdrasil_runtime.metadata import MetadataBundle


@dataclass(frozen=True)
class Segment:
    """A derived segment: its metadata bundle plus a pointer back to its source artifact.

    Frozen + runtime-guarded so the "no naked segment" guarantee does not rely on the type
    annotation alone: a ``Segment`` cannot be constructed without a segment-typed ``MetadataBundle``,
    and its bundle cannot be replaced with ``None`` after construction.
    """

    metadata_bundle: MetadataBundle
    source_artifact_id: str
    text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.metadata_bundle, MetadataBundle):
            raise TypeError("Segment requires a MetadataBundle (no naked segment)")
        if self.metadata_bundle.object_type != "segment":
            raise ValueError(
                "Segment.metadata_bundle.object_type must be 'segment' "
                f"(got {self.metadata_bundle.object_type!r})"
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unresolved_source_bundle(artifact_id: str) -> MetadataBundle:
    """Honest source bundle for an artifact_id NOT present in the in-memory capture store.

    The xfail skeleton ``test_provenance_survives_derivation`` calls ``derive_segment("art-1")`` with
    no prior capture and requires a valid segment back, so failing loud here is not possible without
    weakening that skeleton (forbidden). Instead of fabricating a *real-looking* internal source
    (which would mask a missing producer and let the segment masquerade as genuine inherited
    work-scope provenance), the unregistered path is transparently labelled: an **external /
    unresolved** scope, ``source_role=external_source``, lowest standing, and a provenance event that
    explicitly records the unresolved origin. A reviewer can therefore tell at a glance that this
    segment's source was not resolved. Real captured artifacts (and, later, corpus docs) inherit
    their true scope/role normally.
    """
    return MetadataBundle(
        object_id=artifact_id,
        object_type="artifact",
        scope_id="scope:external/unresolved",
        source_role="external_source",
        authority_state="captured",
        evidence_role="reference",
        sensitivity="private",
        suppression_state="visible",
        created_by="system:dri",
        created_at=_now_iso(),
        provenance_event_ids=[f"prov:source-unresolved:{artifact_id}:{uuid4().hex[:8]}"],
        vault_id=capture.DEFAULT_VAULT_ID,
    )


def derive_segment(artifact_id: str, *, text: str = "") -> Segment:
    """Derive a segment that inherits its source artifact's bundle and preserves provenance."""
    captured = capture.get_captured(artifact_id)
    source = (
        captured.metadata_bundle
        if captured is not None
        else _unresolved_source_bundle(artifact_id)
    )

    bundle = MetadataBundle(
        object_id=f"segment:{uuid4().hex[:12]}",
        object_type="segment",
        scope_id=source.scope_id,                # inherited, not re-stamped
        source_role=source.source_role,          # inherited
        authority_state=source.authority_state,  # inherited (preserved)
        evidence_role=source.evidence_role,      # inherited (never upgraded)
        sensitivity=source.sensitivity,
        suppression_state=source.suppression_state,
        created_by="system:dri",
        created_at=_now_iso(),
        # provenance preserved (source events) + the derivation event; always non-empty
        provenance_event_ids=[*source.provenance_event_ids, f"prov:derive:{uuid4().hex[:8]}"],
        derived_from=[artifact_id],              # lineage survives derivation
        vault_id=source.vault_id,
        principal_id=source.principal_id,
        # preserve the receipt if the source carries accepted/canonical standing
        authority_receipt_ref=source.authority_receipt_ref,
    )
    seg_text = text or (captured.text if captured is not None else "")
    return Segment(metadata_bundle=bundle, source_artifact_id=artifact_id, text=seg_text)
