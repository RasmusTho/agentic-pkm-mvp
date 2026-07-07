"""#3119 — a capture made to a vault the watcher isn't bound to must surface
a visible warning in the workspace, not just the downstream "Find unavailable"
symptom.

A vault selected/initialized through the Companion UI picker
(``POST /api/companion/vault/select`` / ``/vault/initialize``) sets an
in-process API selection only; the watcher/worker bind their own vault path
independently at boot (``WATCHER_VAULT_PATH``, #2476 — a deliberate split, not
a bug). Before this fix, a capture in that state showed a bare "written ·
Inbox/inbox.md" success with nothing connecting it to the fact that ingest
never saw it.

Two surfaces carry the warning:

1. The workspace shell renders a banner (mirroring the existing
   ``workspace-vault-unreachable-banner`` pattern) when the runtime reports
   ``runtime_ingest_state`` as ``"unbound"`` or ``"diverged"``.
2. The capture acknowledgement itself (``ack.ingest_warning``, threaded from
   ``CaptureResponse.ingest_warning``) carries the same warning so the
   moment of capture is not silently declared safe.

These tests exercise the pure rendering functions directly — no live runtime,
no Docker — mirroring ``tests/companion_ui/test_workspace_vault_unreachable_banner.py``'s
established fixture convention.
"""

from __future__ import annotations

from companion_ui.workspace.capture_modal import CaptureAck
from companion_ui.workspace.serve_dev_page import render_index_html


def _render(**overrides) -> str:
    fields: dict = {
        "title": "Test Note",
        "note_path": "Notes/test.md",
        "artifact_id": "art-001",
        "content_hash": "sha256-abc",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": True,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "TestVault",
        "runtime_vault_channel": "dev",
        "runtime_ingest_state": "bound",
        "runtime_ingest_bound": True,
        "runtime_ingest_detail": "",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_proposals": [],
        "panel_message": "",
        "find_candidates": [],
        "reorient_sections": None,
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "body": "# Test Note\n\nBody content.",
    }
    fields.update(overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


class TestIngestUnboundBanner:
    def test_capture_warns_when_pipeline_unbound(self) -> None:
        """The exact AC2 scenario: ingest is unbound -> a visible banner,
        not just the bare workspace render."""

        html = _render(
            runtime_ingest_state="unbound",
            runtime_ingest_bound=False,
            runtime_ingest_detail=(
                "watcher has not reported a heartbeat yet; captures to this "
                "vault will not be ingested until the watcher/worker are bound"
            ),
        )
        assert 'data-testid="workspace-ingest-unbound-banner"' in html
        assert "Ingest not yet bound to this vault" in html
        assert "watcher has not reported a heartbeat yet" in html
        assert 'data-testid="workspace-ingest-retry"' in html

    def test_banner_appears_when_diverged(self) -> None:
        html = _render(
            runtime_ingest_state="diverged",
            runtime_ingest_bound=False,
            runtime_ingest_detail=(
                "the watcher/worker are bound to a different vault than the "
                "one currently selected"
            ),
        )
        assert 'data-testid="workspace-ingest-unbound-banner"' in html
        assert "different vault" in html

    def test_banner_absent_when_bound(self) -> None:
        html = _render(runtime_ingest_state="bound", runtime_ingest_bound=True)
        assert 'data-testid="workspace-ingest-unbound-banner"' not in html

    def test_banner_absent_when_unknown_no_vault_selected_yet(self) -> None:
        """`unknown` (nothing selected yet) is not itself a mismatch — it
        must stay silent like the vault_unreachable convention does for its
        own non-error states."""

        html = _render(runtime_ingest_state="unknown", runtime_ingest_bound=True)
        assert 'data-testid="workspace-ingest-unbound-banner"' not in html

    def test_banner_independent_of_vault_reachability(self) -> None:
        """Ingest binding and vault reachability are separate signals — a
        reachable vault can still be un-ingested, and the two banners must
        not be conflated into one."""

        html = _render(
            runtime_vault_provenance="resolved",
            runtime_ingest_state="unbound",
            runtime_ingest_bound=False,
            runtime_ingest_detail="watcher has not reported a heartbeat yet",
        )
        assert 'data-testid="workspace-vault-unreachable-banner"' not in html
        assert 'data-testid="workspace-ingest-unbound-banner"' in html


class TestCaptureAckIngestWarning:
    def test_ack_carries_ingest_warning_field(self) -> None:
        """The pure model mirrors the shipped CaptureResponse contract: an
        ack can carry an advisory ingest_warning without being downgraded
        from `written` — the write itself always succeeded."""

        ack = CaptureAck(
            note_path="Inbox/inbox.md",
            operation="append",
            adapter="markdown",
            captured_at="2026-07-07T00:00:00Z",
            trace_id="trace-1",
            ingest_warning="watcher has not reported a heartbeat yet",
        )
        assert ack.ingest_warning == "watcher has not reported a heartbeat yet"

    def test_ack_ingest_warning_defaults_to_none(self) -> None:
        """A capture to a properly-bound vault must not fabricate a warning."""

        ack = CaptureAck(
            note_path="Inbox/inbox.md",
            operation="append",
            adapter="markdown",
            captured_at="2026-07-07T00:00:00Z",
            trace_id="trace-1",
        )
        assert ack.ingest_warning is None
