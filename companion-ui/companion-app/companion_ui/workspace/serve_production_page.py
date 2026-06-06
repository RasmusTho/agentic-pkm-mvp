"""Production launch profile for the Companion real-note workspace.

This profile is separate from the dev/staging server. It keeps the same
runtime-mediated workspace boundary but uses production defaults and omits
dev/staging markers from rendered output.
"""

from __future__ import annotations

import os
import sys

from companion_ui.workspace.serve_dev_page import (
    _DEFAULT_HOST,
    CompanionThreadingHTTPServer,
    WorkspaceHttpClient,
    make_handler,
    render_index_html,
)

_PRODUCTION_PORT = 8113
_PRODUCTION_API_BASE_URL = "http://127.0.0.1:18000"
_PRODUCTION_SAFETY_WARNING = (
    "Local-only default. Public internet exposure is not supported; "
    "this profile does not provide auth, TLS, or a reverse proxy."
)
_PRODUCTION_STATIC_ASSETS = {
    "/static/companion-workspace.css": (
        "text/css; charset=utf-8",
        b":root{color-scheme:dark;} body{min-height:100vh;}\n",
    )
}


def load_config() -> dict:
    """Load production profile config from environment variables."""
    return {
        "host": os.environ.get("HOST", _DEFAULT_HOST),
        "port": int(os.environ.get("PORT", str(_PRODUCTION_PORT))),
        "api_base_url": os.environ.get(
            "COMPANION_API_BASE_URL",
            _PRODUCTION_API_BASE_URL,
        ),
    }


def render_production_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: dict | None = None,
    error: str = "",
) -> str:
    """Render the workspace shell with production-profile chrome."""
    return render_index_html(
        api_base_url=api_base_url,
        note_path=note_path,
        fields=fields,
        error=error,
        production_profile=True,
    )


def main() -> None:
    """Entry point: read production config, bind server, serve until stopped."""
    config = load_config()
    client = WorkspaceHttpClient(base_url=config["api_base_url"])
    handler = make_handler(
        client=client,
        api_base_url=config["api_base_url"],
        production_profile=True,
        static_assets=_PRODUCTION_STATIC_ASSETS,
    )
    server = CompanionThreadingHTTPServer((config["host"], config["port"]), handler)
    print("[companion-ui] Production profile", flush=True)
    print(f"[companion-ui] Safety:     {_PRODUCTION_SAFETY_WARNING}", flush=True)
    print(
        f"[companion-ui] Listening:   http://{config['host']}:{config['port']}/",
        flush=True,
    )
    print(f"[companion-ui] Runtime API: {config['api_base_url']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
