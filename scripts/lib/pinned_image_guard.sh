#!/usr/bin/env bash
# Pinned-image build guard (#4361).
#
# The service definitions in docker-compose.yaml carry both `build:` and
# `image: ${APP_IMAGE_REPOSITORY}:${APP_IMAGE_TAG}`. `scripts/start_full_system.sh`
# used to pass `docker compose up --build` unconditionally, so a pinned-image
# channel (prod: COMPOSE_FILE excludes docker-compose.app-bind.yml) would
# silently BUILD the image from the local checkout and tag the result with
# the pinned tag whenever that tag was not already present locally -- running
# content then diverged from the authorized pin (#4361), hollowing out
# `scripts/deploy_channel.sh`'s SHA-pin promotion guarantee.
#
# `scripts/deploy_channel.sh` already gets this right for the deploy path
# (`compose pull api worker watcher heimdal-capture-watch companion-ui`,
# never `--build`). This mirrors that same never-silently-build contract for
# the local/operator `start_full_system.sh` bring-up path.

# Returns 0 (true) when the resolved COMPOSE_FILE indicates pinned-image mode
# -- i.e. the code-bind overlay (docker-compose.app-bind.yml) is NOT part of
# the compose file chain, so the running `image:` tag is the only source of
# truth for what code executes. Returns 1 (false) when the app-bind overlay
# is present (local hot-reload / code-bind development mode), where building
# from the checkout is the intended, unchanged behavior.
app_image_pinned_mode() {
  local compose_file="${1:-${COMPOSE_FILE:-}}"
  case ":${compose_file}:" in
    *":docker-compose.app-bind.yml:"*) return 1 ;;
    *) return 0 ;;
  esac
}
