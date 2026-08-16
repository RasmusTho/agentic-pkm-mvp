"""Default multi-architecture app-image TTS packaging contract (#4655)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
TTS_REQUIREMENTS_PATH = REPO_ROOT / "requirements-tts.txt"
APP_IMAGE_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/app-image-build.yml"
TTS_CONFIG_PATH = REPO_ROOT / "app/tts/config.py"
TTS_OWNER_DOC_PATH = REPO_ROOT / "companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md"
TTS_RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/RUNBOOK_TTS_PROVISIONING.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_default_app_image_installs_both_tts_engines() -> None:
    dockerfile = _text(DOCKERFILE_PATH)
    requirements = _text(TTS_REQUIREMENTS_PATH)
    builder_stage = dockerfile.split("FROM ", 2)[1]

    assert "INSTALL_TTS" not in dockerfile
    assert "pip install --no-cache-dir -r requirements-tts.txt" in builder_stage
    assert re.search(r"^piper-tts==1\.6\.0$", requirements, flags=re.MULTILINE)
    assert re.search(r"^kokoro-onnx==0\.5\.0$", requirements, flags=re.MULTILINE)


def test_app_image_workflow_probes_tts_engines_on_each_platform() -> None:
    workflow = _text(APP_IMAGE_WORKFLOW_PATH)

    assert "Probe TTS engines in PR image" in workflow
    assert "command -v piper" in workflow
    assert "import kokoro_onnx" in workflow
    assert "Verify pushed app image runtime, platforms, and TTS engines" in workflow
    assert "app-image-tts-engine-proof.v1" in workflow
    assert 'image_ref="${image%:*}@${{ steps.build-app-main.outputs.digest }}"' in workflow
    assert "image_index_digest" in workflow
    assert "platform_digest" in workflow
    assert 'platform_ref="${image%:*}@${platform_digest}"' in workflow
    assert '"${platform_ref}" \\' in workflow
    assert "linux/amd64" in workflow
    assert "linux/arm64" in workflow
    assert "Upload TTS engine proof" in workflow


def test_engine_proof_is_truthful_about_package_presence_scope() -> None:
    workflow = _text(APP_IMAGE_WORKFLOW_PATH)
    owner_doc = _text(TTS_OWNER_DOC_PATH)
    runbook = _text(TTS_RUNBOOK_PATH)

    assert 'probe_scope: $probe_scope' in workflow
    assert (
        '--arg probe_scope "package_presence_cli_load_import_app_health"' in workflow
    )
    assert '.probe_scope == "package_presence_cli_load_import_app_health"' in workflow
    assert "package-presence proof, not model-backed synthesis" in owner_doc
    assert "package-presence proof, not model-backed synthesis" in runbook


def test_tts_dependency_contract_is_identical_across_linux_platforms() -> None:
    dockerfile = _text(DOCKERFILE_PATH)
    workflow = _text(APP_IMAGE_WORKFLOW_PATH)

    assert len(
        re.findall(r"^(?:COPY|RUN).*requirements-tts\.txt", dockerfile, flags=re.MULTILINE)
    ) == 2
    assert "TARGETARCH" not in dockerfile
    assert "TARGETPLATFORM" not in dockerfile
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "requirements-tts-amd64" not in workflow
    assert "requirements-tts-arm64" not in workflow


def test_engine_image_excludes_models_and_preserves_disabled_local_only_defaults() -> None:
    dockerfile = _text(DOCKERFILE_PATH)
    config = _text(TTS_CONFIG_PATH)

    for forbidden in ("*.onnx", "voices-v1.0.bin", "fetch_tts_models.sh"):
        assert forbidden not in dockerfile
    assert 'enabled=_truthy_env("TTS_ENABLED")' in config
    assert 'local_only=_truthy_env("TTS_LOCAL_ONLY", default=True)' in config
    # Legacy environment flags remain the final one-release compatibility
    # override, while the default posture comes from the tier-gated Settings
    # Spine resolver.
    assert 'allow_browser_fallback=_truthy_env("TTS_ALLOW_BROWSER_FALLBACK", default=configured_browser)' in config
    assert 'allow_cloud_fallback=_truthy_env("TTS_ALLOW_CLOUD_FALLBACK", default=configured_cloud)' in config
    assert 'if not is_lab_profile():' in config
