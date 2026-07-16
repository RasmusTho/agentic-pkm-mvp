# Python minor version must match CI (ci-smoke.yaml python-version). The digest
# pins the multi-arch index for reproducibility; to refresh it after a base bump:
# token from auth.docker.io (scope repository:library/python:pull), then HEAD
# registry-1.docker.io/v2/library/python/manifests/<tag> (Accept: oci.image.index.v1+json).
FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28

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

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-tts.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
  && pip install --no-cache-dir -r requirements-tts.txt

COPY . .
RUN chmod +x scripts/start_api.sh

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
# subdir is `.gitignore`d) so `COPY . .` above never bakes it; without this
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

CMD ["/app/scripts/start_api.sh"]
