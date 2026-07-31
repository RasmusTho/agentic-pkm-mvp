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
6. scripts/ is NOT dev-only wholesale: app/** imports scripts.<module>
   Python modules at module top level (scripts.yaml_roundtrip in
   app/services/companion_note.py, app/chat/session_log.py,
   app/promotion/queue.py, ...; scripts.validate_* in app/builderops/).
   Every such module (plus scripts/__init__.py, so `scripts` resolves as a
   package) must be re-included in .dockerignore and COPYed by the runtime
   stage or the worker/watcher/heimdal compose services crash at boot with
   ModuleNotFoundError.
7. The TTS layer (requirements-tts.txt) is opt-in: its pins cannot install
   on the python:3.12 base (piper-phonemize~=1.1.0 has no cp312 linux
   wheels), so attempting it by default makes `docker build .` fail — the
   #3896 AC requires the default build to produce a working image.
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

# Python package trees the runtime stage COPYs into /app. Any scripts.<module>
# import reachable from these trees must be baked into the image too, or the
# importing service crashes at boot (contract 6 in the module docstring).
RUNTIME_PACKAGE_DIRS = ("app", "mimer_runtime", "companion-ui/companion-app")

_SCRIPTS_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+scripts\.([A-Za-z0-9_]+)\s+import\b|import\s+scripts\.([A-Za-z0-9_]+))",
    flags=re.MULTILINE,
)


def _dockerfile_text() -> str:
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _from_lines() -> list[str]:
    return [line.strip() for line in _dockerfile_text().splitlines() if line.startswith("FROM ")]


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
    assert (
        len(digests) == 1
    ), f"all stages must share the same pinned base digest, got {sorted(digests)}"


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
        assert (
            script in final_stage
        ), f"runtime stage must copy {script} (compose executes it in-container)"
    assert (
        'CMD ["/app/scripts/start_api.sh"]' in final_stage
    ), "image entrypoint/startup behavior must not change"


def test_runtime_image_installs_gh_for_the_cockpit_live_plane() -> None:
    """#4484: the cockpit's `github-live` plane shells out to `gh` in-container.

    `app/builderops/cockpit_github_plane.py :: _run_gh` is the single transport
    every live REST read passes through, and the `api` service that serves
    `/api/cockpit/registry` runs from this image. Without the binary in the
    RUNTIME stage the plane raises `GithubReadError("gh CLI not found ...")` on
    its first call in every channel, so no configuration can enable it.
    """
    text = _dockerfile_text()
    final_stage = text[text.rindex("FROM ") :]
    install_lines = [
        line for line in final_stage.splitlines() if "apt-get install" in line
    ]
    assert install_lines, "runtime (final) stage must have an apt-get install layer"
    assert any(re.search(r"(?<![\w-])gh(?![\w-])", line) for line in install_lines), (
        "runtime (final) stage must install the gh CLI: it is the only "
        "transport the cockpit live GitHub plane has (#4484). Installed "
        f"packages found: {install_lines}"
    )


def test_dockerignore_excludes_dev_only_surfaces() -> None:
    patterns = _dockerignore_patterns()
    for required in ("tests", "docs", ".git", "*.md", "ops", "scripts"):
        assert required in patterns, (
            f".dockerignore must exclude {required!r} from the build context; " f"got {patterns}"
        )


def test_dockerignore_reincludes_compose_runtime_scripts() -> None:
    patterns = _dockerignore_patterns()
    for script in COMPOSE_RUNTIME_SCRIPTS:
        assert f"!{script}" in patterns, (
            f".dockerignore must re-include {script} (negation pattern) so the "
            f"runtime stage can copy the compose entrypoint"
        )


def _runtime_imported_scripts_modules() -> set[str]:
    """scripts.<module> names imported (top-level or lazily) anywhere in the
    package trees the runtime stage bakes into the image."""
    modules: set[str] = set()
    for package_dir in RUNTIME_PACKAGE_DIRS:
        for path in sorted((REPO_ROOT / package_dir).rglob("*.py")):
            for from_mod, import_mod in _SCRIPTS_IMPORT_RE.findall(
                path.read_text(encoding="utf-8")
            ):
                modules.add(from_mod or import_mod)
    return modules


def test_runtime_imported_scripts_modules_are_baked_into_image() -> None:
    """app/** imports scripts.yaml_roundtrip and scripts.validate_* at module
    top level (app/services/companion_note.py, app/chat/session_log.py,
    app/promotion/queue.py, app/builderops/model_inquiry_promotion.py, ...).
    If the image bakes only the two .sh entrypoints, the worker
    (`python -m app.workers.outbox_worker`), watcher (`python -m app.cli
    watcher run`) and heimdal-capture-watch compose services all die at boot
    with ModuleNotFoundError: No module named 'scripts.yaml_roundtrip'
    (#3896 adversarial review). Derive the needed modules from the source so
    a future scripts.<module> import cannot silently reopen the gap."""
    modules = _runtime_imported_scripts_modules()
    assert modules, (
        f"expected runtime packages {RUNTIME_PACKAGE_DIRS} to import "
        "scripts.<module>; if that is no longer true this guard (and the "
        "scripts/*.py COPY in the Dockerfile) can be retired"
    )
    needed_files = sorted(f"scripts/{module}.py" for module in modules | {"__init__"})

    patterns = _dockerignore_patterns()
    # Join backslash line continuations so a multi-line COPY matches.
    text = _dockerfile_text().replace("\\\n", " ")
    final_stage = text[text.rindex("FROM ") :]
    for needed in needed_files:
        assert (REPO_ROOT / needed).is_file(), (
            f"runtime code imports scripts.{Path(needed).stem} but {needed} "
            "does not exist in the repo"
        )
        assert f"!{needed}" in patterns, (
            f".dockerignore must re-include {needed} (negation pattern under "
            f"the scripts/ exclusion) — app/** imports it at runtime"
        )
        assert re.search(
            rf"^\s*COPY\s[^\n]*{re.escape(needed)}(\s|$)",
            final_stage,
            flags=re.MULTILINE,
        ), (
            f"runtime stage must COPY {needed} — app/** imports it at runtime "
            "(worker/watcher/heimdal services crash at boot without it)"
        )


def test_tts_layer_is_opt_in_so_default_build_succeeds() -> None:
    """requirements-tts.txt pins piper-tts==1.2.0 -> piper-phonemize~=1.1.0,
    which publishes no cp312 linux wheels and no sdist, so installing it on
    the python:3.12 base fails EVERY default build (`docker build .`,
    compose build, app-image-build.yml — none pass INSTALL_TTS). The #3896 AC
    requires the default build to produce a working image, so the TTS layer
    must be opt-in (default 0) until the pins gain 3.12 support; the guarded
    RUN keeps the skip loud in the build log."""
    text = _dockerfile_text()
    assert re.search(r"^ARG INSTALL_TTS=0\s*$", text, flags=re.MULTILINE), (
        "INSTALL_TTS must default to 0: the TTS pins cannot install on the "
        "python:3.12 base, so a default of 1 makes every default build fail "
        "(#3896 AC: image builds)"
    )
    assert 'if [ "$INSTALL_TTS" = "1" ]' in text, (
        "the TTS install must stay behind the INSTALL_TTS guard so it can be "
        "re-enabled with --build-arg INSTALL_TTS=1 once the pins support 3.12"
    )
    assert "requirements-tts.txt" in text, (
        "the guarded TTS layer (requirements-tts.txt) must remain in the "
        "builder stage as the opt-in path"
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


def test_episode_stream_registry_is_reincluded_and_copied() -> None:
    """The default episode stream registry is runtime input, not dev-only docs."""
    registry = "docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md"
    patterns = _dockerignore_patterns()
    assert f"!{registry}" in patterns, (
        ".dockerignore must re-include the default episode stream registry "
        "so the runtime stage can copy it"
    )

    final_stage = _dockerfile_text()[_dockerfile_text().rindex("FROM ") :]
    assert re.search(
        rf"^\s*COPY\s+{re.escape(registry)}\s+\./{re.escape(registry)}\s*$",
        final_stage,
        flags=re.MULTILINE,
    ), (
        "runtime stage must copy the default episode stream registry to its "
        "existing /app/docs path"
    )
