"""Companion UI workspace module — real-note workspace dev page and HTTP client.

Provides:
- WorkspaceHttpClient: transport layer to the runtime API.
- RealNoteWorkspaceDevPage: in-memory page model for the real-note workspace.
- serve_dev_page: minimal browser dev server (run with python -m companion_ui.workspace.serve_dev_page).

The workspace module never reads vault files directly.
Vault binding is owned by the runtime environment, not by Companion UI.
"""
