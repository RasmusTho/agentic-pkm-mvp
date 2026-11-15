# Epic workspace worker image (#6615 / #6616).
# Built on the worker VM by the trusted controller host; never by a worker.
# Contains native CLIs only: no credentials, no Docker client, no publication tooling.
FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.311

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 python3-venv ripgrep \
 && rm -rf /var/lib/apt/lists/*

RUN npm install --global --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && claude --version

# uid/gid 1000 is the image's `node` user; the controller runs containers as 1000:1000
# with HOME=/home/worker bind-mounted from the worker's persistent home directory.
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
USER 1000:1000
WORKDIR /workspace
