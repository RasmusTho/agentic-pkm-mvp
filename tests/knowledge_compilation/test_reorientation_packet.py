from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone

import pytest

import app.knowledge_compilation.reorientation_packet as reorientation_packet
from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExcludedItem,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)
from app.knowledge_compilation.reorientation_packet import (
    PacketAssemblyError,
    assemble_reorientation_packet_from_bundle,
)
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    ReorientationPacket,
    TrustVerb,
)
from app.orientation.bundle_consumer import BundleAuthorityViolation


_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    included: list[IncludedItem] | None = None,
    excluded: list[ExcludedItem] | None = None,
    authority: AuthorityFlags | None = None,
    expiry: ExpiryPosture | None = None,
    intended_use: list[str] | None = None,
) -> ContextBundle:
    return ContextBundle(
        id="ctx_return_to_work",
        created_at=_NOW,
        trigger=BundleTrigger(type="orientation", source="test"),
        intended_use=intended_use or ["orient"],
        scope=BundleScope(project="knowledge-compilation"),
        included=included or [],
        excluded=excluded or [],
        authority=authority or AuthorityFlags(may_orient=True),
        expiry=expiry or ExpiryPosture(),
    )


def _included(
    artifact_id: str,
    *,
    path: str | None = None,
    reason: str = "return-to-work source",
    source_role: str | None = None,
    trust_state: str | None = "reviewed",
    review_state: str | None = "confirmed",
    retrieval_score: float | None = None,
    provenance: ItemProvenance | None = None,
) -> IncludedItem:
    return IncludedItem(
        artifact_id=artifact_id,
        path=path,
        reason=reason,
        source_role=source_role,
        trust_state=trust_state,
        review_state=review_state,
        retrieval_score=retrieval_score,
        provenance=provenance or ItemProvenance(origin="vault note"),
    )


def test_reorientation_packet_projects_read_only_orientation_context() -> None:
    bundle = _bundle(
        included=[
            _included("note:one", path="vault://one.md"),
            _included("note:two", path="vault://two.md", source_role="inference"),
        ]
    )

    packet = assemble_reorientation_packet_from_bundle(
        bundle,
        trace_ref="trace:return-to-work:1",
        now=_NOW,
    )

    assert isinstance(packet, ReorientationPacket)
    assert packet.is_bridge_artifact is True
    assert packet.trust_verb is TrustVerb.SUGGEST
    assert packet.admission_state is AdmissionState.PENDING_REVIEW
    assert packet.authority_limits.may_orient is True
    assert packet.authority_limits.may_write is False
    assert packet.authority_limits.may_promote is False
    assert packet.authority_limits.may_authorize_action is False
    assert packet.trace_ref == "trace:return-to-work:1"
    assert [ref.artifact_id for ref in packet.source_refs] == ["note:one", "note:two"]


def test_packet_preserves_trace_staleness_and_caps_content() -> None:
    stale_after = _NOW - timedelta(minutes=5)
    included = [
        _included(
            f"note:{idx}",
            path=f"vault://note-{idx}.md",
            reason="long reason text that should not become unbounded packet body",
            retrieval_score=0.5,
        )
        for idx in range(6)
    ]
    excluded = [
        ExcludedItem(
            artifact_id="note:excluded",
            reason="stale source",
            trust_state="stale",
            provenance=ItemProvenance(origin="vault note"),
        )
    ]
    bundle = _bundle(
        included=included,
        excluded=excluded,
        expiry=ExpiryPosture(stale_after=stale_after, reason="bundle expired"),
    )

    packet = assemble_reorientation_packet_from_bundle(
        bundle,
        trace_ref="trace:return-to-work:2",
        now=_NOW,
        max_source_refs=3,
        max_summary_chars=96,
    )

    assert packet.trace_ref == "trace:return-to-work:2"
    assert packet.stale_after == stale_after
    assert packet.stale_reason == "bundle expired"
    assert len(packet.source_refs) == 3
    assert len(packet.summary or "") <= 96
    assert "long reason text" not in (packet.summary or "")
    assert [ref.artifact_id for ref in packet.excluded_refs] == ["note:excluded"]
    assert packet.exclusion_reasons == ("stale source",)


def test_packet_exposes_reference_only_memory_handoff() -> None:
    bundle = _bundle(
        included=[
            _included(
                "agentic_memory:cand_123",
                reason="raw candidate content must not be copied into packet",
                source_role="memory_handoff",
                trust_state="unreviewed",
                review_state="pending",
                provenance=ItemProvenance(origin="orientation intent"),
            )
        ]
    )

    packet = assemble_reorientation_packet_from_bundle(
        bundle,
        trace_ref="trace:return-to-work:3",
        now=_NOW,
    )

    assert packet.memory_handoff_refs == ("agentic_memory:cand_123",)
    assert "raw candidate content" not in (packet.summary or "")
    assert packet.admission_receipt_ref is None
    assert packet.grants_receipt_authority is False
    assert packet.authority_limits.may_write is False

    no_handoff_packet = assemble_reorientation_packet_from_bundle(
        bundle,
        trace_ref="trace:return-to-work:3",
        now=_NOW,
        max_memory_handoff_refs=0,
    )
    assert no_handoff_packet.memory_handoff_refs == ()


def test_packet_refuses_mutation_and_storage_paths() -> None:
    write_bundle = _bundle(
        included=[_included("note:one")],
        authority=AuthorityFlags(may_orient=True, may_write=True),
    )
    with pytest.raises(BundleAuthorityViolation):
        assemble_reorientation_packet_from_bundle(
            write_bundle,
            trace_ref="trace:return-to-work:4",
            now=_NOW,
        )

    mutation_bundle = _bundle(
        included=[
            _included(
                "intent:write",
                source_role="mutation_intent",
                trust_state="SUGGEST",
            )
        ]
    )
    with pytest.raises(PacketAssemblyError, match="mutation"):
        assemble_reorientation_packet_from_bundle(
            mutation_bundle,
            trace_ref="trace:return-to-work:5",
            now=_NOW,
        )

    apply_bundle = _bundle(
        included=[_included("note:apply", trust_state="APPLY")],
    )
    with pytest.raises(PacketAssemblyError, match="APPLY"):
        assemble_reorientation_packet_from_bundle(
            apply_bundle,
            trace_ref="trace:return-to-work:6",
            now=_NOW,
        )

    src = inspect.getsource(reorientation_packet)
    tree = ast.parse(src)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add((node.module or "").lower())

    forbidden = (
        "sqlalchemy",
        "app.db",
        "app.objects",
        "app.outbox",
        "objectstore",
        "knowledgeport",
        "vaultport",
        "writeguard",
    )
    assert not any(
        bad in module for bad in forbidden for module in imported_modules
    ), sorted(imported_modules)
