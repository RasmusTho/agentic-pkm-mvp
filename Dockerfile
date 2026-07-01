FROM python:3.11-slim

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

EXPOSE 8000

CMD ["/app/scripts/start_api.sh"]
