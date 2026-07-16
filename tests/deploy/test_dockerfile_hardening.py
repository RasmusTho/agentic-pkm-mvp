"""Guard Dockerfile multi-stage hardening (builder-ops-stability spec Issue 7).

The runtime image must not bake the full repo (`COPY . .` pulled in tests,
docs, .git, ops). Contracts guarded here:

1. Multi-stage build: a builder stage installs the runtime requirement
   manifests; the runtime stage copies the installed site-packages plus only
   the assets the services in docker-compose.yaml genuinely need at runtime
   (app/, mimer_runtime/, schemas/, config/, configs/, vault/, docs/settings/,
   companion-ui/companion-app/, the two compose entrypoint scripts, alembic
   config, sitecustomize.py).
2. Every stage stays on the digest-pinned python:3.x-slim base
   (tests/deploy/test_dockerfile_python_alignment.py owns the CI alignment;
   this file only asserts the stages agree with each other).
3. ffmpeg stays installed in the runtime (final) stage.
4. A HEALTHCHECK probes the existing API health endpoint (`/readyz`, the same
   endpoint config/runtime.defaults.env points API_HEALTHCHECK_URL at).
5. .dockerignore keeps dev-only surfaces (tests/, docs/, .git/, root *.md,
   ops/, scripts/) out of the build context while re-including the two
   scripts compose actually executes inside containers
   (scripts/start_api.sh, scripts/run_migrations.sh) and docs/settings/**,
   the one docs/ subtree read at runtime (settings registries: model/tool/
   agent/graph/event/prompt loaders in app/components/settings/, plus
   app/settings/ fallbacks and panel-action wiring).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

# Runtime entrypoints executed inside containers by docker-compose.yaml
# (`migrate` runs run_migrations.sh; `api` and the image CMD run start_api.sh).
COMPOSE_RUNTIME_SCRIPTS = ("scripts/start_api.sh", "scripts/run_migrations.sh")


def _dockerfile_text() -> str:
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _from_lines() -> list[str]:
    return [
        line.strip()
        for line in _dockerfile_text().splitlines()
        if line.startswith("FROM ")
    ]


def _dockerignore_patterns() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_dockerfile_is_multi_stage() -> None:
    from_lines = _from_lines()
    assert len(from_lines) >= 2, (
        f"Dockerfile must be a multi-stage build (builder + runtime), "
        f"got FROM lines: {from_lines}"
    )


def test_all_stages_share_one_pinned_base_digest() -> None:
    digests = set()
    for from_line in _from_lines():
        match = re.search(r"@sha256:([0-9a-f]{64})", from_line)
        assert match, f"stage base image is not digest-pinned: {from_line}"
        digests.add(match.group(1))
    assert len(digests) == 1, (
        f"all stages must share the same pinned base digest, got {sorted(digests)}"
    )


def test_no_full_context_copy() -> None:
    text = _dockerfile_text()
    assert not re.search(r"^\s*COPY\s+\.\s+\.\s*$", text, flags=re.MULTILINE), (
        "Dockerfile must not COPY the whole build context; the runtime stage "
        "copies only genuine runtime assets"
    )


def test_healthcheck_probes_existing_health_endpoint() -> None:
    text = _dockerfile_text()
    assert "HEALTHCHECK" in text, "Dockerfile must declare a HEALTHCHECK"
    assert "readyz" in text, (
        "HEALTHCHECK must use the existing API health endpoint (/readyz, the "
        "endpoint API_HEALTHCHECK_URL in config/runtime.defaults.env targets)"
    )
    assert "API_HEALTHCHECK_URL" in text, (
        "HEALTHCHECK must honor the API_HEALTHCHECK_URL override the compose "
        "healthchecks already use"
    )


def test_runtime_stage_keeps_ffmpeg_and_compose_entrypoints() -> None:
    text = _dockerfile_text()
    # ffmpeg must be installed in the FINAL stage (after the last FROM), not
    # only in the builder.
    final_stage = text[text.rindex("FROM ") :]
    assert "ffmpeg" in final_stage, "runtime (final) stage must install ffmpeg"
    for script in COMPOSE_RUNTIME_SCRIPTS:
        assert script in final_stage, (
            f"runtime stage must copy {script} (compose executes it in-container)"
        )
    assert 'CMD ["/app/scripts/start_api.sh"]' in final_stage, (
        "image entrypoint/startup behavior must not change"
    )


def test_dockerignore_excludes_dev_only_surfaces() -> None:
    patterns = _dockerignore_patterns()
    for required in ("tests", "docs", ".git", "*.md", "ops", "scripts"):
        assert required in patterns, (
            f".dockerignore must exclude {required!r} from the build context; "
            f"got {patterns}"
        )


def test_dockerignore_reincludes_compose_runtime_scripts() -> None:
    patterns = _dockerignore_patterns()
    for script in COMPOSE_RUNTIME_SCRIPTS:
        assert f"!{script}" in patterns, (
            f".dockerignore must re-include {script} (negation pattern) so the "
            f"runtime stage can copy the compose entrypoint"
        )


def test_docs_settings_runtime_tree_is_reincluded_and_copied() -> None:
    """docs/ is dev-only EXCEPT docs/settings/**, which app code reads at
    RUNTIME relative to /app: the model/tool/agent/graph/event/prompt
    registries (app/components/settings/*_loader.py defaults, consumed by the
    LLM router, MCP tool provider and settings compiler), the flow/agent
    fallbacks (app/settings/flows.py, app/settings/agents.py,
    app/config/paths.py) and panel-action wiring
    (app/agents/panel_agent/wiring.py). Dropping it from the image turns every
    LLM-routed request into a FileNotFoundError."""
    patterns = _dockerignore_patterns()
    assert "!docs/settings" in patterns, (
        ".dockerignore must re-include docs/settings (negation pattern) — it "
        "is read at runtime by the settings loaders"
    )
    text = _dockerfile_text()
    final_stage = text[text.rindex("FROM ") :]
    assert re.search(r"^\s*COPY\s+docs/settings/\s", final_stage, flags=re.MULTILINE), (
        "runtime stage must COPY docs/settings/ (settings registries read at "
        "runtime by app/components/settings/*_loader.py)"
    )
