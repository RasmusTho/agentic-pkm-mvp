"""Module entry point: the API-only BuilderOps control-plane client CLI."""

from __future__ import annotations

from app.builderops.control_plane.client_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
