"""Proposal-builder tests for v6.x Knowledge Compilation (#1535, parent #1533).

Deterministic, provider-free builders that turn explicitly supplied, approved context into
non-canonical CompilationDraft / CurationCandidate proposals — without laundering hidden
authority and without storage/API/event/UI wiring.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import app.knowledge_compilation.proposal_builders as proposal_builders
from app.knowledge_compilation.proposal_builders import (
    ProposalContext,
    build_compilation_draft,
    build_curation_candidate,
)
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    CurationCandidate,
    SourceRef,
    TrustVerb,
)


def _clean_source() -> SourceRef:
    return SourceRef(artifact_id="note:x", note_path="vault://x.md", role="source")


def test_compilation_draft_preserves_source_refs_and_uncertainty() -> None:
    src = _clean_source()
    ctx = ProposalContext(
        source_refs=(src,),
        content="synthesis body",
        uncertainty_notes="two sources disagree on the date",
        trace_ref="trace:abc",
        generated_by="compiler",
    )
    draft = build_compilation_draft(ctx, title="Draft A")

    assert isinstance(draft, CompilationDraft)
    assert draft.source_refs == (src,)
    assert draft.body == "synthesis body"
    assert draft.uncertainty_notes == "two sources disagree on the date"
    assert draft.trace_ref == "trace:abc"
    assert draft.generated_by == "compiler"
    # Non-canonical, suggest-only posture preserved from the #1534 contract.
    assert draft.canonical is False
    assert draft.trust_verb is TrustVerb.SUGGEST
    assert draft.admission_state is AdmissionState.PENDING_REVIEW


def test_curation_candidate_preserves_rationale_and_exclusions() -> None:
    kept = SourceRef(artifact_id="note:keep", role="retained")
    excluded = SourceRef(artifact_id="note:old", role="excluded: superseded by note:keep")
    ctx = ProposalContext(
        source_refs=(kept,),
        rationale="retain the primary; the newer source supersedes the older draft",
        excluded_refs=(excluded,),
    )
    candidate = build_curation_candidate(ctx, title="Curation A")

    assert isinstance(candidate, CurationCandidate)
    assert candidate.source_refs == (kept,)
    assert candidate.rationale == "retain the primary; the newer source supersedes the older draft"
    # Excluded source links and their reasons (carried on the ref) are preserved, not dropped.
    assert candidate.excluded_refs == (excluded,)
    assert candidate.canonical is False
    assert candidate.trust_verb is TrustVerb.SUGGEST


def test_builders_reject_hidden_authority_context() -> None:
    clean = _clean_source()

    # Unprovenanced context.
    with pytest.raises(ValueError, match="provenance"):
        build_compilation_draft(ProposalContext(source_refs=()), title="t")

    # Stale inputs.
    with pytest.raises(ValueError, match="stale"):
        build_compilation_draft(ProposalContext(source_refs=(clean,), stale=True), title="t")

    # Write-authorizing context bundle.
    with pytest.raises(ValueError, match="write-authorizing"):
        build_curation_candidate(
            ProposalContext(
                source_refs=(clean,),
                authority_limits=ContextAuthorityLimits(may_write=True),
            ),
            title="t",
        )

    # Unreviewed memory laundering.
    with pytest.raises(ValueError, match="unreviewed"):
        build_compilation_draft(
            ProposalContext(source_refs=(SourceRef(artifact_id="m", review_state="unreviewed"),)),
            title="t",
        )

    for review_state in ("queued", "candidate", "rejected"):
        with pytest.raises(ValueError, match="non-approved review_state"):
            build_compilation_draft(
                ProposalContext(
                    source_refs=(SourceRef(artifact_id=f"m-{review_state}", review_state=review_state),)
                ),
                title="t",
            )

    protected = build_compilation_draft(
        ProposalContext(
            source_refs=(SourceRef(artifact_id="note:protected", review_state="protected"),)
        ),
        title="protected source",
    )
    assert protected.source_refs[0].review_state == "protected"

    # Retrieval-ranked source presented as approved authority.
    with pytest.raises(ValueError, match="retrieval"):
        build_compilation_draft(
            ProposalContext(source_refs=(SourceRef(artifact_id="r", retrieval_score=0.92),)),
            title="t",
        )

    # Machine-derived (embedding / generated summary) source.
    with pytest.raises(ValueError, match="machine-derived"):
        build_curation_candidate(
            ProposalContext(source_refs=(SourceRef(artifact_id="s", derived_by="generated_summary"),)),
            title="t",
        )


_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "sqlalchemy",
    "app.db",
    "app.io",
    "app.objects",
    "app.index",
    "app.outbox",
    "app.events",
    "objectstore",
    "knowledgeport",
    "vaultport",
    "writeguard",
    "outbox",
)

_FORBIDDEN_SYMBOLS = (
    "ObjectStore",
    "KnowledgePort",
    "VaultPort",
    "WriteGuard",
    "Session",
    "sessionmaker",
    "emit",
    "open",
)


def test_builders_do_not_emit_events_write_vault_or_import_db() -> None:
    src = inspect.getsource(proposal_builders)
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
            f"proposal_builders must not import {forbidden!r}; imports={sorted(imported_modules)}"
        )
    for symbol in _FORBIDDEN_SYMBOLS:
        assert symbol not in used_names, f"proposal_builders must not reference {symbol!r}"
