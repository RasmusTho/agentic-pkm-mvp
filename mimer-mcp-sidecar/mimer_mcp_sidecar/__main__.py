"""Run the client-spawned Mimer MCP stdio sidecar."""

from .transport import main

if __name__ == "__main__":
    raise SystemExit(main())
