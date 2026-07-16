# Multi-stage build (builder-ops-stability spec Issue 7): the builder stage
# installs the runtime requirement manifests; the runtime stage copies the
# installed site-packages + console scripts and ONLY genuine runtime assets
# (no tests/, .git/, ops/, and no docs/ except the runtime-read docs/settings/
# subtree — see .dockerignore and tests/deploy/test_dockerfile_hardening.py).
#
# Python minor version must match CI (ci-smoke.yaml python-version). The digest
# pins the multi-arch index for reproducibility; to refresh it after a base bump:
# token from auth.docker.io (scope repository:library/python:pull), then HEAD
# registry-1.docker.io/v2/library/python/manifests/<tag> (Accept: oci.image.index.v1+json).
# BOTH stages must reference the same pinned digest
# (tests/deploy/test_dockerfile_python_alignment.py).
FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28 AS builder

# TTS layer toggle — see the guarded RUN below. Declared after FROM so it is
# in scope for this stage; default 1 preserves the previous behavior (every
# prior Dockerfile attempted the TTS install unconditionally).
ARG INSTALL_TTS=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install into /usr/local exactly as the former single-stage build did (same
# resolution order: requirements.txt first, then requirements-tts.txt), then
# hand the resulting site-packages + entry-point scripts to the runtime stage.
COPY requirements.txt requirements-tts.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# KNOWN BREAKAGE, surfaced deliberately (#3896 review): requirements-tts.txt
# pins piper-tts==1.2.0 -> piper-phonemize~=1.1.0, and piper-phonemize 1.1.0
# publishes NO cp312 linux wheels and no sdist (PyPI has cp39–cp311 manylinux
# x86_64/aarch64 wheels only; the sole cp312 wheel is macOS x86_64). On this
# python:3.12 base the TTS layer therefore CANNOT install on linux — the
# default build fails loudly here, exactly as the single-stage 3.12 Dockerfile
# from #3893 already did. It worked on the pre-#3893 python:3.11 base (cp311
# manylinux wheels exist). Kept attempted-by-default so an image never
# silently ships without piper/kokoro; until the TTS pins gain 3.12 support
# (or product policy drops the baked TTS layer), build a TTS-less image
# explicitly with: docker build --build-arg INSTALL_TTS=0 .
RUN if [ "$INSTALL_TTS" = "1" ]; then \
      pip install --no-cache-dir -r requirements-tts.txt; \
    else \
      echo "INSTALL_TTS=$INSTALL_TTS: SKIPPING requirements-tts.txt — piper/kokoro NOT baked into this image"; \
    fi


FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28 AS runtime

# Build-time arguments for version observability.
# Pass via: docker build --build-arg VCS_REF=$(git rev-parse HEAD) \
#                        --build-arg BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ) .
ARG VCS_REF=unknown
ARG BUILT_AT=unknown

# Persist build args as image labels (readable via `docker inspect`).
LABEL org.opencontainers.image.revision="$VCS_REF"
LABEL org.opencontainers.image.created="$BUILT_AT"

# Persist build args as env vars so os.getenv("VCS_REF") works at runtime.
# A bare ARG/LABEL is NOT readable via os.getenv; ENV is required.
ENV VCS_REF=$VCS_REF \
    BUILT_AT=$BUILT_AT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg stays in the RUNTIME stage: the capture/transcription path shells out
# to it (faster-whisper/yt-dlp media handling). espeak-ng backs the local TTS
# engines (piper phonemization).
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
  && rm -rf /var/lib/apt/lists/*

# Installed third-party packages and their console scripts (uvicorn, alembic,
# piper, ...) from the builder stage. Same base digest, so the interpreter
# path baked into script shebangs (/usr/local/bin/python) is identical.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Runtime assets only — each COPY below maps to a genuine in-container
# dependency of the services in docker-compose.yaml:
# - app/                        the application package (includes app/alembic
#                               migrations + app/alembic.ini used by
#                               scripts/run_migrations.sh)
# - mimer_runtime/              imported directly by app/** (cross_scope, dri, ...)
# - schemas/                    JSON schemas resolved via REPO_ROOT at runtime
#                               (app/episodes/schema.py, app/retrieval/envelope.py, ...)
# - config/ + configs/          runtime defaults/settings files (config/agent.yaml,
#                               config/runtime.defaults.env, configs/watchers.yaml)
# - vault/                      default settings/flows templates read by
#                               app/settings/** (vault/@Settings, vault/_system/**)
# - docs/settings/              the ONE runtime-read docs/ subtree: settings
#                               registries + fallbacks resolved relative to
#                               /app (app/components/settings/*_loader.py
#                               defaults — LLM router model registry, MCP tool
#                               provider tool registry, settings compiler —
#                               plus app/settings/flows.py + agents.py
#                               fallbacks and app/agents/panel_agent/wiring.py).
#                               .dockerignore re-includes it (!docs/settings).
# - companion-ui/companion-app/ the companion_ui package the companion-ui
#                               service serves (working_dir + PYTHONPATH)
# - alembic.ini                 root alembic entry (script_location=app/alembic)
# - sitecustomize.py            import-time classifier persistence hook
# - scripts/                    ONLY the two entrypoints compose executes
#                               in-container (migrate + api services)
COPY app/ ./app/
COPY mimer_runtime/ ./mimer_runtime/
COPY schemas/ ./schemas/
COPY config/ ./config/
COPY configs/ ./configs/
COPY vault/ ./vault/
COPY docs/settings/ ./docs/settings/
COPY companion-ui/companion-app/ ./companion-ui/companion-app/
COPY alembic.ini sitecustomize.py ./
COPY scripts/start_api.sh scripts/run_migrations.sh ./scripts/
RUN chmod +x scripts/start_api.sh scripts/run_migrations.sh

# Pre-create the runtime scratch dir with open perms so the container can create
# it even when run under host-uid remapping (compose `user: ${LOCAL_UID}:${LOCAL_GID}`
# for host-owned vault writes). Without this, `mkdir -p /app/tmp` in the service
# command is denied on the root-owned /app and the process crash-loops.
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp

# Pre-create /app/runtime with open perms for the same reason (#3047): every
# `app/**` module that defaults a receipt/state path to a relative
# `runtime/<subdir>/...` (ask_synthesis, expansion_records, agent_memory,
# relevance, builderops, dispatcher, orientation, panel, proposals — see
# `git grep 'Path("runtime/'` for the current set) resolves it under `/app`
# (the compose `working_dir`). `/app/runtime` does not exist in the repo (every
# subdir is `.gitignore`d) so the COPY steps above never bake it; without this
# step the *first* write from a fresh container calls
# `path.parent.mkdir(parents=True, exist_ok=True)` against the root-owned
# `/app`, which is denied under the host-uid-remapped runtime user and fails
# every request that touches a receipt (observed: POST /api/ask 500s via
# app/activation/ask_synthesis.py::emit_ask_synthesis_receipt).
# This is the general chokepoint for this defect class under the current
# image-bake-chown mechanism: a *new* root-owned runtime-writable surface
# should get its own `mkdir -p /app/<path> && chmod 1777 /app/<path>` line
# here rather than a bespoke per-module fix (e.g. #3118's heartbeat files on
# the shared `runtime-tmp` volume mounted at /app/tmp, which this same
# pattern already covers).
RUN mkdir -p /app/runtime && chmod 1777 /app/runtime

EXPOSE 8000

# Probe the existing API readiness endpoint (app/api/routes/health_contract.py
# :: /readyz). API_HEALTHCHECK_URL is the same override the compose api
# healthcheck consumes (config/runtime.defaults.env sets it to
# http://127.0.0.1:8000/readyz); the fallback keeps bare `docker run` covered.
# Compose services define their own healthcheck: blocks, which override this.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(os.environ.get('API_HEALTHCHECK_URL') or 'http://127.0.0.1:8000/readyz', timeout=2)" || exit 1

CMD ["/app/scripts/start_api.sh"]
