from __future__ import annotations

from pathlib import Path

from app.version import get_runtime_version


WORKFLOW_PATH = Path(".github/workflows/app-image-build.yml")
DOCKERFILE_PATH = Path("Dockerfile")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_builds_sha_tagged_image() -> None:
    workflow = _workflow_text()

    assert "  workflow_dispatch:" in workflow
    assert "  push:" in workflow
    assert 'vcs_ref="${GITHUB_SHA}"' in workflow
    assert 'owner="${GITHUB_REPOSITORY_OWNER,,}"' in workflow
    assert 'image="ghcr.io/${owner}/pkm-app:${vcs_ref}"' in workflow
    assert "uses: docker/build-push-action@v6" in workflow
    assert "context: ." in workflow
    assert "file: Dockerfile" in workflow
    assert "tags: ${{ steps.build-identity.outputs.image }}" in workflow
    assert "push: false" in workflow


def test_built_image_version_reports_build_sha(monkeypatch) -> None:
    workflow = _workflow_text()
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert 'built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in workflow
    assert "VCS_REF=${vcs_ref}" in workflow
    assert "BUILT_AT=${built_at}" in workflow
    assert "VCS_REF=${{ env.VCS_REF }}" in workflow
    assert "BUILT_AT=${{ env.BUILT_AT }}" in workflow
    assert "ENV VCS_REF=$VCS_REF" in dockerfile
    assert "BUILT_AT=$BUILT_AT" in dockerfile
    assert "get_runtime_version" in workflow
    assert 'version["git_sha"] == os.environ["VCS_REF"]' in workflow
    assert 'version["built_at"] == os.environ["BUILT_AT"]' in workflow

    monkeypatch.setenv("VCS_REF", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("BUILT_AT", "2026-06-30T00:00:00Z")
    assert get_runtime_version() == {
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "built_at": "2026-06-30T00:00:00Z",
    }


def test_single_image_artifact_per_commit() -> None:
    workflow = _workflow_text()

    assert "strategy:" not in workflow
    assert workflow.count("uses: docker/build-push-action@") == 1
    assert "matrix:" not in workflow
    assert "CHANNEL" not in workflow
    assert "ENVIRONMENT" not in workflow
