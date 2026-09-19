from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from app.builderops.devui_exact_reuse_candidate import (
    DevuiCandidateProvenanceError,
    _immutable_source_texts,
    _load_manifest,
    _validate_bindings,
    _validate_browser_safety,
    _validate_candidate_tokens,
    validate_devui_exact_reuse_candidate,
)


def test_candidate_inventory_git_object_and_transform_binding_fails_closed() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    reviewed_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()

    result = validate_devui_exact_reuse_candidate(repo_root, revision=reviewed_sha)

    assert result == {
        "candidate_subtree": "companion-ui/companion-app/companion_ui/workspace/devui_candidate",
        "inventory_status": "complete",
        "source_objects_status": "verified",
        "transform_binding_status": "closed_allowlist",
        "no_egress_status": "verified",
    }


def test_historical_reuse_target_blob_oid_is_full_and_content_bound() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    target_commit = "8056841cf7d060ba7c1cfcb4e46da14eb3206e62"
    target_path = "companion-ui/companion-app/companion_ui/workspace/devui_candidate/overview.js"
    oid = subprocess.run(
        ["git", "rev-parse", f"{target_commit}:{target_path}"],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    assert len(oid) == 40 and all(character in "0123456789abcdef" for character in oid)
    assert subprocess.run(["git", "cat-file", "-e", oid], cwd=repo_root, check=False).returncode == 0
    blob = subprocess.run(
        ["git", "cat-file", "blob", oid], cwd=repo_root, capture_output=True, check=True
    ).stdout
    assert hashlib.sha256(blob).hexdigest() == "a578f24e0eecb431cdeb7e60f61483d89b20ab16289106ed881ba479703f7ea2"
    assert b"matrix(body, evidence);" in blob
    assert b"rows(body, evidence, true);" in blob
    for manifest_path in (
        repo_root / "app/builderops/devui_managed_reuse.json",
        repo_root / "companion-ui/companion-app/companion_ui/workspace/devui_candidate_provenance.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        historical = []

        def collect(value):
            if isinstance(value, dict):
                if value.get("target_role") == "historical_intermediate":
                    historical.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(manifest)
        assert len(historical) == 1
        target = historical[0]
        assert target["target_commit"] == target_commit
        assert target["target_path"] == target_path
        assert target["target_git_blob_oid"] == oid
        assert target["target_content_sha256"] == f"sha256:{hashlib.sha256(blob).hexdigest()}"


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
        match="explicit canonical reviewed commit SHA is required",
    ):
        validate_devui_exact_reuse_candidate(
            Path(__file__).resolve().parents[2], revision=None  # type: ignore[arg-type]
        )

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="explicit canonical reviewed commit SHA is required",
    ):
        validate_devui_exact_reuse_candidate(
            Path(__file__).resolve().parents[2], revision="HEAD"
        )


def test_candidate_binding_refuses_anchor_absent_from_immutable_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
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
            candidate_texts={
                path.name: path.read_text(encoding="utf-8")
                for path in (repo_root / forged["candidate"]["subtree"]).iterdir()
                if path.is_file()
            },
        )


def test_candidate_tokens_refuse_declaration_added_after_source_commit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
    source_texts = _immutable_source_texts(repo_root, manifest["source"])

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="token absent from the immutable accepted source",
    ):
        _validate_candidate_tokens(
            candidate_text="color:var(--post-source-token)",
            token_source=source_texts["app/web/static/colors_and_type.css"],
        )


def test_candidate_tokens_require_source_value_parity_but_allow_local_fonts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
    source = _immutable_source_texts(repo_root, manifest["source"])

    _validate_candidate_tokens(
        candidate_text=(
            ":root{--bg-base:#070b12;"
            "--font-ui:system-ui,-apple-system,sans-serif}"
        ),
        token_source=source["app/web/static/colors_and_type.css"],
    )

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="candidate token value differs from the immutable accepted source: --bg-base",
    ):
        _validate_candidate_tokens(
            candidate_text=":root{--bg-base:#0b0d12}",
            token_source=source["app/web/static/colors_and_type.css"],
        )


def test_candidate_binding_refuses_forged_candidate_anchor() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
    forged = copy.deepcopy(manifest)
    forged["bindings"][0]["candidate_patterns"]["overview.html"].append(
        "forged-candidate-anchor"
    )
    candidate_root = repo_root / forged["candidate"]["subtree"]

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="binding anchor is absent from candidate",
    ):
        _validate_bindings(
            forged,
            inventory=forged["candidate"]["inventory"],
            source_texts=_immutable_source_texts(repo_root, forged["source"]),
            candidate_texts={
                path.name: path.read_text(encoding="utf-8")
                for path in candidate_root.iterdir()
                if path.is_file()
            },
        )


def test_candidate_binding_refuses_anchor_not_shared_with_immutable_source() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
    forged = copy.deepcopy(manifest)
    forged["bindings"][0]["shared_patterns"]["overview.html"] = [
        'class="band primary"'
    ]
    candidate_root = repo_root / forged["candidate"]["subtree"]

    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="shared binding anchor is not present on both sides",
    ):
        _validate_bindings(
            forged,
            inventory=forged["candidate"]["inventory"],
            source_texts=_immutable_source_texts(repo_root, forged["source"]),
            candidate_texts={
                path.name: path.read_text(encoding="utf-8")
                for path in candidate_root.iterdir()
                if path.is_file()
            },
        )


def test_candidate_browser_safety_refuses_extra_fetch_or_mutation_primitive() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = _load_manifest(repo_root, revision=None)
    candidate_root = repo_root / manifest["candidate"]["subtree"]
    texts = {
        path.name: path.read_text(encoding="utf-8")
        for path in candidate_root.iterdir()
        if path.is_file()
    }

    forged_fetch = copy.deepcopy(texts)
    forged_fetch["overview.js"] += '\nfetch("/api/devui/extra")\n'
    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="exactly the two reviewed API reads",
    ):
        _validate_browser_safety(forged_fetch)

    forged_mutation = copy.deepcopy(texts)
    forged_mutation["focus.js"] += "\nnavigator.sendBeacon('/effect')\n"
    with pytest.raises(
        DevuiCandidateProvenanceError,
        match="unreviewed browser capability",
    ):
        _validate_browser_safety(forged_mutation)
