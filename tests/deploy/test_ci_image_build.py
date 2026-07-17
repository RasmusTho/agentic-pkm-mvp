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
    assert "  pull_request:" in workflow
    assert "    paths:" in workflow
    for path in (
        "'app/**'",
        "'scripts/start_api.sh'",
        "'Dockerfile'",
        "'requirements.txt'",
        "'requirements-tts.txt'",
        "'.github/workflows/app-image-build.yml'",
    ):
        assert path in workflow
    assert "uses: docker/setup-qemu-action@v3" in workflow
    assert 'vcs_ref="${GITHUB_SHA}"' in workflow
    assert 'owner="${GITHUB_REPOSITORY_OWNER,,}"' in workflow
    assert 'image="ghcr.io/${owner}/pkm-app:${vcs_ref}"' in workflow
    assert "uses: docker/build-push-action@v6" in workflow
    assert "context: ." in workflow
    assert "file: Dockerfile" in workflow
    assert "tags: ${{ steps.build-identity.outputs.image }}" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "Publish the exact restore-proved BuilderOps images" in workflow
    assert 'docker push "${{ steps.images.outputs.control_plane }}"' in workflow
    assert 'docker push "${{ steps.images.outputs.postgres }}"' in workflow
    publish = workflow.split("Publish the exact restore-proved BuilderOps images", maxsplit=1)[1]
    assert "docker build" not in publish
    assert "load: true" in workflow
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
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert "manifest_platforms=\"" in workflow
    assert "awk '" in workflow
    assert "--platform linux/amd64" in workflow

    monkeypatch.setenv("VCS_REF", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("BUILT_AT", "2026-06-30T00:00:00Z")
    assert get_runtime_version() == {
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "built_at": "2026-06-30T00:00:00Z",
    }


def test_single_image_artifact_per_commit() -> None:
    workflow = _workflow_text()
    product_image_job = workflow.split("\n  build-builderops-images:", maxsplit=1)[0]

    assert "strategy:" not in product_image_job
    assert product_image_job.count("uses: docker/build-push-action@") == 2
    assert product_image_job.count("if: github.event_name == 'pull_request'") == 2
    assert (
        product_image_job.count("if: github.event_name == 'push' && github.ref == 'refs/heads/main'")
        >= 1
    )
    assert "matrix:" not in product_image_job
    assert "CHANNEL" not in product_image_job
    assert "ENVIRONMENT" not in product_image_job


def test_builderops_publish_reuses_the_restore_proved_images() -> None:
    builderops_job = _workflow_text().split("\n  build-builderops-images:", maxsplit=1)[1]
    restore = builderops_job.index("Prove encrypted full-backup plus archived-WAL restore")
    publish = builderops_job.index("Publish the exact restore-proved BuilderOps images")

    assert restore < publish
    assert "docker build" not in builderops_job[publish:]
    assert 'docker push "${{ steps.images.outputs.control_plane }}"' in builderops_job[publish:]
    assert 'docker push "${{ steps.images.outputs.postgres }}"' in builderops_job[publish:]
    receipt = builderops_job.index("Write the restore-proved candidate pair receipt")
    attestation = builderops_job.index("Attest the restore-proved candidate pair receipt")
    assert publish < receipt < attestation
    assert "actions/attest-build-provenance@v2" in builderops_job
    assert "subject-path: builderops-candidate-pair.json" in builderops_job
    assert "id-token: write" in builderops_job
    assert "attestations: write" in builderops_job
