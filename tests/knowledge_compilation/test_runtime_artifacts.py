"""Runtime artifact contract tests for v6.x Knowledge Compilation (#1534, parent #1533).

These cover the bounded slice: pure, non-canonical, SUGGEST-posture runtime support
models for CompilationDraft, CurationCandidate, and ReorientationPacket — with no
storage, API, event, or UI wiring and no hidden authority.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import app.knowledge_compilation.runtime_artifacts as runtime_artifacts
from app.knowledge_compilation.runtime_artifacts import (
    AGENT_MEMORY_CLASS,
    BRIDGE_ARTIFACT_CLASSES,
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    CurationCandidate,
    ReorientationPacket,
    SourceRef,
    TrustVerb,
)


def _source() -> SourceRef:
    return SourceRef(
        artifact_id="note:abc123",
        note_path="vault://notes/abc.md",
        role="source",
    )


def test_generated_artifacts_default_to_noncanonical_suggest_posture() -> None:
    draft = CompilationDraft(title="Synthesis candidate", source_refs=[_source()])
    candidate = CurationCandidate(title="Retained set", source_refs=[_source()])
    packet = ReorientationPacket(summary="Return-to-work", source_refs=[_source()])

    for artifact in (draft, candidate, packet):
        assert artifact.canonical is False
        assert artifact.trust_verb is TrustVerb.SUGGEST
        assert artifact.admission_state is AdmissionState.PENDING_REVIEW
        # Default authority posture is inform-only: never write/promote/act.
        assert artifact.authority_limits.may_write is False
        assert artifact.authority_limits.may_promote is False
        assert artifact.authority_limits.may_authorize_action is False

    # Provenance is mandatory: construction fails without at least one source_ref.
    with pytest.raises(ValueError, match="requires at least one source_ref"):
        CompilationDraft(title="No sources")

    # Generated artifacts cannot be marked canonical.
    with pytest.raises(ValueError, match="non-canonical"):
        CurationCandidate(title="Tries canonical", source_refs=[_source()], canonical=True)

    # Generated artifacts cannot self-escalate trust without explicit admission.
    with pytest.raises(ValueError, match="without explicit admission"):
        CompilationDraft(
            title="Tries to assert",
            source_refs=[_source()],
            trust_verb=TrustVerb.APPLY,
        )


def test_reorientation_packet_is_bridge_artifact_not_memory_or_receipt_authority() -> None:
    packet = ReorientationPacket(
        summary="Resume work on X",
        source_refs=[_source()],
        memory_handoff_refs=["agentic_memory:cand_123"],
        admission_receipt_ref="receipt:abc",
    )

    # Bridge/assembly classification.
    assert packet.artifact_class == "reorientation_packet"
    assert packet.artifact_class in BRIDGE_ARTIFACT_CLASSES
    assert packet.is_bridge_artifact is True

    # Not agent memory.
    assert packet.artifact_class != AGENT_MEMORY_CLASS

    # Not receipt authority: references receipts by id only, never *is* one.
    assert isinstance(packet.admission_receipt_ref, str)
    assert packet.grants_receipt_authority is False

    # References memory by id only — it does not embed or become memory.
    assert packet.memory_handoff_refs == ["agentic_memory:cand_123"]
    assert packet.canonical is False

    # Orient-capable by default (its whole purpose is re-orientation), while write/promote/
    # action authority stay disabled.
    assert packet.authority_limits.may_orient is True
    assert packet.authority_limits.may_write is False
    assert packet.authority_limits.may_promote is False
    assert packet.authority_limits.may_authorize_action is False

    # Compilation/curation outputs are not bridge artifacts and are not orient-capable.
    draft = CompilationDraft(title="d", source_refs=[_source()])
    assert draft.is_bridge_artifact is False
    assert draft.authority_limits.may_orient is False


def test_unreviewed_memory_and_rankings_cannot_grant_hidden_authority() -> None:
    # Provenance carrying unreviewed memory, embeddings, retrieval scores, generated summaries.
    hidden_authority_sources = [
        SourceRef(artifact_id="agentic_memory:cand_x", review_state="unreviewed"),
        SourceRef(artifact_id="embed:chunk_y", derived_by="embedding", retrieval_score=0.99),
        SourceRef(artifact_id="summary:z", derived_by="generated_summary"),
    ]
    draft = CompilationDraft(title="From rankings", source_refs=hidden_authority_sources)

    # High retrieval scores / unreviewed memory / generated summaries never elevate authority.
    assert draft.authority_limits.may_write is False
    assert draft.authority_limits.may_promote is False
    assert draft.authority_limits.may_authorize_action is False
    assert draft.trust_verb is TrustVerb.SUGGEST

    # Explicitly trying to hand a generated artifact write/action authority is refused.
    with pytest.raises(ValueError, match="hidden authority"):
        CompilationDraft(
            title="Tries to grab write authority",
            source_refs=hidden_authority_sources,
            authority_limits=ContextAuthorityLimits(may_write=True),
        )
    with pytest.raises(ValueError, match="hidden authority"):
        ReorientationPacket(
            summary="Tries to authorize action",
            source_refs=[_source()],
            authority_limits=ContextAuthorityLimits(may_authorize_action=True),
        )


_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "sqlalchemy",
    "app.db",
    "app.io",
    "app.objects",
    "app.index",
    "app.outbox",
    "objectstore",
    "knowledgeport",
    "vaultport",
    "writeguard",
    "outbox",
)

# Identifiers that would imply storage/vault/outbox/filesystem write wiring. Checked
# against actual usage (Name/Attribute/import nodes) via AST, not raw text, so the module
# may still describe its own constraints in docstrings.
_FORBIDDEN_SYMBOLS = (
    "ObjectStore",
    "KnowledgePort",
    "VaultPort",
    "WriteGuard",
    "Session",
    "sessionmaker",
    "open",
)


def test_runtime_artifacts_are_pure_domain_no_db_or_vault_writes() -> None:
    src = inspect.getsource(runtime_artifacts)
    tree = ast.parse(src)

    imported_modules: set[str] = set()
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            imported_modules.add(module)
            for alias in node.names:
                imported_modules.add(f"{module}.{alias.name}".lower())
                used_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)

    for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
        assert not any(forbidden in mod for mod in imported_modules), (
            f"runtime_artifacts must not import {forbidden!r}; imports={sorted(imported_modules)}"
        )

    # No DB/vault/outbox/filesystem-write symbols referenced anywhere in the module.
    for symbol in _FORBIDDEN_SYMBOLS:
        assert symbol not in used_names, f"runtime_artifacts must not reference {symbol!r}"
