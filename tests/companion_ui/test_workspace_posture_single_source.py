"""#3361 — Companion UI posture is one source of truth.

DESIGN_AUDIT.md (`companion-ui/design_handoff/2026-07-07-uat-design-audit/
DESIGN_AUDIT.md`) §3.1 / top-10 #1 documented bugs B1/B2/B5: the topbar chip,
a rail line, and the vault browser each described runtime health
independently and could contradict each other; the no-vault picker invented a
false "Initialize this vault" CTA on a live, merely-unreachable vault (B1);
and raw errno/DNS transport strings ("[Errno -2] Name or service not known")
leaked into user-facing copy (B2).

These tests pin the fix: `companion_ui.workspace.workspace_posture` is the
single derivation point for the vault-reachability posture, and the topbar
chip, the one calm banner, the error-state copy, and the vault picker all
subscribe to it — none of them classifies vault reachability independently.
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_posture import (
    CALM_RECONNECT_BANNER_TEXT,
    CANT_REACH_VAULT_COPY,
    RECONNECTING_PICKER_SUB,
    RECONNECTING_PICKER_TITLE,
)

from tests.companion_ui._visible_text import visible_text as _visible_text

# Tokens DESIGN_AUDIT.md §3.1/§6 names as never allowed on a user-facing
# surface: raw errno/DNS transport text and internal guard-state vocabulary.
_FORBIDDEN_TOKENS = (
    "errno",
    "name or service not known",
    "connection refused",
    "guard state",
)


def _shell_fields(**overrides: Any) -> dict:
    fields: dict = {
        "title": "Test Note",
        "note_path": "Notes/test.md",
        "artifact_id": "art-001",
        "content_hash": "sha256-abc",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "Niflheim",
        "runtime_vault_channel": "dev",
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
        "body": "# Cached Note\n\nThis is the cached body content.",
    }
    fields.update(overrides)
    return fields


def _render_shell(**overrides: Any) -> str:
    fields = _shell_fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


# ---------------------------------------------------------------------------
# AC1 — topbar chip and the one calm banner derive from one posture value
# ---------------------------------------------------------------------------
def test_topbar_and_banner_derive_from_one_posture() -> None:
    healthy_html = _render_shell()
    assert 'data-testid="workspace-vault-chip"' in healthy_html
    assert 'data-state="ok"' in healthy_html
    assert 'data-vault-posture="healthy"' in healthy_html
    assert "niflheim · vault ok" in _visible_text(healthy_html)
    # Healthy posture: no banner anywhere — the rail/topbar never disagree
    # because there is nothing degraded to disagree about.
    assert 'data-testid="workspace-vault-unreachable-banner"' not in healthy_html

    degraded_html = _render_shell(vault_unreachable=True)
    assert 'data-state="unreachable"' in degraded_html
    assert 'data-vault-posture="degraded"' in degraded_html
    # The chip label reads "reconnecting" — never a lingering "vault ok"
    # alongside a degraded banner (DESIGN_AUDIT.md §3.1 contradiction).
    assert "niflheim · reconnecting" in _visible_text(degraded_html)
    assert "vault ok" not in _visible_text(degraded_html)
    # Exactly the one calm banner, with the single calm sentence.
    assert degraded_html.count('data-testid="workspace-vault-unreachable-banner"') == 1
    assert CALM_RECONNECT_BANNER_TEXT.lower() in _visible_text(degraded_html)


# ---------------------------------------------------------------------------
# AC2 — errno / DNS / guard-state tokens never reach visible text
# ---------------------------------------------------------------------------
def test_errno_never_in_visible_text() -> None:
    dns_error_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        fields=None,
        error="[Errno -2] Name or service not known",
    )
    transport_error_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        fields=None,
        error="[Errno 61] Connection refused",
    )
    degraded_shell_html = _render_shell(vault_unreachable=True)
    reconnecting_picker_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        vault_selection_required={
            "state": "vault_selection_required",
            "reason": "no_vault_bound",
            "message": "No vault is selected. Open the configured vault to continue.",
            "configured_vault_root": "/Users/me/Vaults/Niflheim",
            "requested_note_path": "",
            "context": {"status": "none"},
            "recent_vaults": [],
            "actions": [],
            "runtime_reconnecting": True,
        },
    )

    for surface_html in (
        dns_error_html,
        transport_error_html,
        degraded_shell_html,
        reconnecting_picker_html,
    ):
        visible = _visible_text(surface_html)
        for token in _FORBIDDEN_TOKENS:
            assert token not in visible, f"{token!r} leaked into visible text"

    # The calm replacement copy is present on the errno/DNS surfaces instead
    # of the raw exception text.
    assert CANT_REACH_VAULT_COPY.lower() in _visible_text(dns_error_html)
    assert CANT_REACH_VAULT_COPY.lower() in _visible_text(transport_error_html)
    # The raw errno text is absent from the *rendered error element* — pinned
    # against that specific region rather than the whole document, since
    # unrelated inert `<script>` source carries an "Errno 61" doc comment
    # elsewhere on the page that is not user-facing copy.
    transport_region = re.search(
        r'data-testid="workspace-error-state".*?</div>', transport_error_html, re.DOTALL
    )
    assert transport_region is not None
    assert "Errno 61" not in transport_region.group()
    dns_region = re.search(
        r'data-testid="workspace-error-state".*?</div>', dns_error_html, re.DOTALL
    )
    assert dns_region is not None
    assert "Errno -2" not in dns_region.group()
    # The classified state still arrives — the runtime-unavailable marker is
    # present even though the raw text is gone (server declares, UI renders).
    assert 'data-testid="workspace-runtime-unavailable-state"' in dns_error_html
    assert 'data-testid="workspace-runtime-unavailable-state"' in transport_error_html


# ---------------------------------------------------------------------------
# AC3 — the Initialize CTA renders only when reason == "uninitialized"
# ---------------------------------------------------------------------------
def test_picker_initialize_cta_only_when_uninitialized() -> None:
    uninitialized_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        vault_selection_required={
            "state": "vault_selection_required",
            "reason": "uninitialized",
            "message": (
                "The selected vault is not initialized yet. Initialize it to "
                "enable writes, or open a different vault to continue."
            ),
            "configured_vault_root": "/Users/me/Vaults/Niflheim",
            "requested_note_path": "",
            "context": {"status": "uninitialized", "active_vault_path": "/Users/me/Vaults/Niflheim"},
            "recent_vaults": [],
            "actions": [],
        },
    )
    assert 'data-testid="vault-picker-initialize-submit"' in uninitialized_html
    assert "Initialize this vault" in uninitialized_html

    # A configured vault the runtime declares as currently reconnecting
    # (additive `runtime_reconnecting` flag, #3361) — the live-vault false
    # Initialize CTA from bug B1 must be impossible here, and the picker
    # shows the calm "reconnecting" copy instead of the generic first-contact
    # message.
    reconnecting_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        vault_selection_required={
            "state": "vault_selection_required",
            "reason": "no_vault_bound",
            "message": "No vault is selected. Open the configured vault to continue.",
            "configured_vault_root": "/Users/me/Vaults/Niflheim",
            "requested_note_path": "",
            "context": {"status": "none"},
            "recent_vaults": [],
            "actions": [],
            "runtime_reconnecting": True,
        },
    )
    assert 'data-testid="vault-picker-initialize-submit"' not in reconnecting_html
    assert 'data-testid="vault-picker-create-submit"' not in reconnecting_html
    assert "Initialize this vault" not in reconnecting_html
    assert 'data-reconnecting="true"' in reconnecting_html
    visible = _visible_text(reconnecting_html)
    assert RECONNECTING_PICKER_TITLE.lower() in visible
    assert RECONNECTING_PICKER_SUB.lower() in visible
    assert "is not initialized yet" not in visible
