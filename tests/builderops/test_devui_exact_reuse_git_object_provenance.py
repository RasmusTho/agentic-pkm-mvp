"""Git-object-only exact-reuse provenance tests for #4884."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.builderops.devui_exact_reuse_provenance import (
    DECLARATION_PATH,
    ExactReuseProvenanceError,
    build_review_input,
    validate_exact_reuse,
)


APPROVED_IMPORTS = [
    "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Space+Grotesk:wght@300;400;500;600&display=swap",
    "https://fonts.bunny.net/css?family=jetbrains-mono:400,500&display=swap",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True, text=True, capture_output=True
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _declaration(source_commit: str, source_blob: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "devui.exact-reuse.git-object.v1",
        "source": {"commit": source_commit, "path": "source.css", "blob_oid": source_blob},
        "remote_font_imports": APPROVED_IMPORTS,
        "source_tokens": ["--font-ui", "--font-display", "--font-mono"],
        "font_fallback": "system-ui, sans-serif",
        "transforms": ["drop_remote_font_imports", "use_declared_local_font_fallback"],
        "state_matrix": ["normal", "empty", "loading", "degraded", "error", "narrow", "200%", "keyboard", "screen-reader", "print", "javascript-off"],
    }
    value.update(overrides)
    return value


@pytest.fixture()
def object_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "objects"
    repo.mkdir()
    _git(repo, "init")
    (repo / "source.css").write_text(
        "@import url('" + APPROVED_IMPORTS[0] + "');\n"
        "@import url('" + APPROVED_IMPORTS[1] + "');\n"
        ":root { --font-display: 'EB Garamond', Georgia, serif; --font-ui: 'Space Grotesk', system-ui, sans-serif; --font-mono: 'JetBrains Mono', monospace; }\n"
    )
    source_commit = _commit(repo, "source")
    source_blob = _git(repo, "rev-parse", f"{source_commit}:source.css")
    declaration = repo / DECLARATION_PATH
    declaration.parent.mkdir(parents=True)
    declaration.write_text(json.dumps(_declaration(source_commit, source_blob)))
    candidate = _commit(repo, "candidate")
    return repo, candidate, source_blob


def test_dirty_or_replaced_worktree_declaration_cannot_change_verdict(object_repo: tuple[Path, str, str]) -> None:
    repo, candidate, _ = object_repo
    baseline = validate_exact_reuse(repo, candidate)
    (repo / DECLARATION_PATH).write_text("not json")
    assert validate_exact_reuse(repo, candidate) == baseline


def test_validator_rejects_missing_different_or_nonblob_candidate_and_source_objects(object_repo: tuple[Path, str, str]) -> None:
    repo, candidate, source_blob = object_repo
    with pytest.raises(ExactReuseProvenanceError):
        validate_exact_reuse(repo, "main")
    declaration = json.loads(_git(repo, "show", f"{candidate}:{DECLARATION_PATH}"))
    declaration["source"]["blob_oid"] = "0" * 40  # type: ignore[index]
    (repo / DECLARATION_PATH).write_text(json.dumps(declaration))
    bad_candidate = _commit(repo, "wrong object")
    with pytest.raises(ExactReuseProvenanceError):
        validate_exact_reuse(repo, bad_candidate)
    assert source_blob


def test_validator_uses_hardcoded_literal_font_pair_not_source_derived_urls(object_repo: tuple[Path, str, str]) -> None:
    repo, candidate, _ = object_repo
    assert validate_exact_reuse(repo, candidate).remote_font_imports == tuple(APPROVED_IMPORTS)
    source = (repo / "source.css")
    source.write_text("@import url('https://evil.invalid/a.css');\n@import url('https://evil.invalid/b.css');\n")
    source_commit = _commit(repo, "third party css")
    source_blob = _git(repo, "rev-parse", f"{source_commit}:source.css")
    declaration = _declaration(source_commit, source_blob, remote_font_imports=["https://evil.invalid/a.css", "https://evil.invalid/b.css"])
    (repo / DECLARATION_PATH).write_text(json.dumps(declaration))
    bad_candidate = _commit(repo, "third party candidate")
    with pytest.raises(ExactReuseProvenanceError):
        validate_exact_reuse(repo, bad_candidate)


def test_validator_preserves_closed_schema_fallback_transforms_and_state_matrix(object_repo: tuple[Path, str, str]) -> None:
    repo, candidate, _ = object_repo
    assert validate_exact_reuse(repo, candidate).state_matrix[0] == "normal"
    declaration = json.loads(_git(repo, "show", f"{candidate}:{DECLARATION_PATH}"))
    declaration["state_matrix"].append("normal")
    (repo / DECLARATION_PATH).write_text(json.dumps(declaration))
    bad_candidate = _commit(repo, "duplicate state")
    with pytest.raises(ExactReuseProvenanceError):
        validate_exact_reuse(repo, bad_candidate)


def test_review_input_requires_committed_candidate_sha_and_declaration_blob_receipt(object_repo: tuple[Path, str, str]) -> None:
    repo, candidate, _ = object_repo
    receipt = build_review_input(repo, candidate)
    assert receipt.candidate_sha == candidate
    assert len(receipt.declaration_blob_oid) == 40
    with pytest.raises(ExactReuseProvenanceError):
        build_review_input(repo, "HEAD")
