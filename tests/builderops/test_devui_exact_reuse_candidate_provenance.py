from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.builderops.devui_exact_reuse_candidate import (
    DevuiCandidateProvenanceError,
    _immutable_source_texts,
    _load_manifest,
    _validate_bindings,
    _validate_candidate_tokens,
    validate_devui_exact_reuse_candidate,
)


def test_candidate_inventory_git_object_and_transform_binding_fails_closed() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = validate_devui_exact_reuse_candidate(repo_root, revision="HEAD")

    assert result == {
        "candidate_subtree": "companion-ui/companion-app/companion_ui/workspace/devui_candidate",
        "inventory_status": "complete",
        "source_objects_status": "verified",
        "transform_binding_status": "closed_allowlist",
        "no_egress_status": "verified",
    }


def test_candidate_manifest_refuses_dirty_or_substituted_revision_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = (
        tmp_path
        / "companion-ui/companion-app/companion_ui/workspace/devui_candidate_provenance.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"schema":"substituted"}\n', encoding="utf-8")
    committed = Path(
        "companion-ui/companion-app/companion_ui/workspace/devui_candidate_provenance.json"
    ).read_bytes()
    monkeypatch.setattr(
        "app.builderops.devui_exact_reuse_candidate._git_bytes",
        lambda *_args: committed,
    )

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="working manifest differs from the reviewed revision",
    ):
        _load_manifest(tmp_path, revision="reviewed-sha")


def test_candidate_validator_requires_explicit_review_revision() -> None:
    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="explicit reviewed Git revision is required",
    ):
        validate_devui_exact_reuse_candidate(
            Path(__file__).resolve().parents[2], revision=None  # type: ignore[arg-type]
        )


def test_candidate_binding_refuses_anchor_absent_from_immutable_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision="HEAD")
    forged = copy.deepcopy(manifest)
    forged["bindings"][0]["source_patterns"].append("forged-post-source-anchor")

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="binding anchor is absent from immutable source",
    ):
        _validate_bindings(
            forged,
            inventory=forged["candidate"]["inventory"],
            source_texts=_immutable_source_texts(repo_root, forged["source"]),
        )


def test_candidate_tokens_refuse_declaration_added_after_source_commit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision="HEAD")
    source_texts = _immutable_source_texts(repo_root, manifest["source"])

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="token absent from the immutable accepted source",
    ):
        _validate_candidate_tokens(
            candidate_text="color:var(--post-source-token)",
            token_source=source_texts["app/web/static/colors_and_type.css"],
        )
