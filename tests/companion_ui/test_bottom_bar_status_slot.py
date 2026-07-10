"""Reserved bottom-bar status slot (#3364, DESIGN_AUDIT §4.1 / B3).

Static render assertions: a runtime-composed channel/vault-settings status
string used to render behind (clipped by) the Map/History/Memory/Search/
Settings/Help pill cluster at every tested width, and used alarm-red for what
was usually a benign disabled-feature note. The fix reserves a dedicated
status slot ABOVE the pill row — its own region/testid, structurally outside
``.workspace-bottom-bar`` — so the two can never collide, and downgrades the
tone to calm unless the status is a genuine error.

Pure server-render assertions against ``render_index_html`` — no live
runtime.
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.calm_degraded import CANVAS_OFF, EDITING_PAUSED
from companion_ui.workspace.serve_dev_page import render_index_html

from tests.companion_ui._orphan_text import assert_no_orphan_text


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-status-slot",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-status-slot",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-status-slot",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": "2026-06-10T21:08:00Z",
    }
    base.update(overrides)
    return base


def _shell(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _status_slot(html: str) -> re.Match[str] | None:
    return re.search(
        r'<div class="workspace-status-slot"[^>]*data-testid="workspace-status-slot"[^>]*>.*?</div>',
        html,
        re.S,
    )


def _bottom_bar_region(html: str) -> str:
    m = re.search(
        r'<div class="workspace-bottom-bar"[^>]*data-region="bottom-bar"[^>]*>(.*?)</div>',
        html,
        re.S,
    )
    assert m, "bottom-bar container must render"
    return m.group(0)


def test_status_slot_reserved_above_pills() -> None:
    # Benign disabled-feature note: guard_update_flow_available=False while
    # guard_workspace_update_available stays True. This is the exact silent
    # state #3364 exists to surface — posture stays "ok" (the posture
    # computation never inspects update_flow_available) while
    # _render_body_edit_panel simultaneously hides body editing on that flag —
    # so the slot must fire from the flag itself, not the posture token. The
    # slot renders as its own region, markup-adjacent to but structurally
    # outside the pill row, so pills and status can never occupy the same box.
    html = _shell(guard_update_flow_available=False)
    slot_match = _status_slot(html)
    assert slot_match, "reserved status slot must render when a status exists"
    slot_markup = slot_match.group(0)
    assert 'data-region="status-slot"' in slot_markup

    bottom_bar_markup = _bottom_bar_region(html)
    assert 'data-testid="workspace-status-slot"' not in bottom_bar_markup, (
        "the status slot must not be nested inside the pill row's "
        "data-region=\"bottom-bar\" container"
    )
    # The slot must appear before the bottom bar in document order (rendered
    # immediately ahead of it, per _render_help_toggle's status_slot_html
    # prefix), keeping the two visually stacked rather than co-located.
    assert html.index(slot_match.group(0)) < html.index(bottom_bar_markup)

    # Pills stay unchanged: still present, still inside their own container.
    for testid in (
        "workspace-surface-icon-map",
        "workspace-help-toggle",
    ):
        assert f'data-testid="{testid}"' in bottom_bar_markup

    assert_no_orphan_text(html)

    # Healthy posture (no status to show): the slot collapses to nothing.
    healthy_html = _shell()
    assert _status_slot(healthy_html) is None, (
        "the status slot must be absent/empty when there is no status"
    )


def test_status_tone_calm_unless_true_error() -> None:
    # Benign disabled-feature status (the update-flow channel is off, runtime
    # is otherwise fine — posture stays "ok"): calm tone, not the
    # destructive/alarm class, with the calm_degraded module's editing-paused
    # copy (the sole emitter of unavailable-state copy; no inline literal).
    calm_html = _shell(guard_update_flow_available=False)
    calm_slot = _status_slot(calm_html)
    assert calm_slot, "benign-status fixture must render the slot"
    calm_markup = calm_slot.group(0)
    assert 'data-tone="calm"' in calm_markup
    assert EDITING_PAUSED in calm_markup

    calm_tone_rule = re.search(
        r'\.workspace-status-slot\{[^}]*color:\s*var\(--fg-3\)', calm_html
    )
    assert calm_tone_rule, "the default (calm) tone must use --fg-3"

    # Canvas-off idiom is unified: the slot and the operator drawer's runtime
    # pill both read calm_degraded.CANVAS_OFF for the same server-declared
    # fact ("one slot, one string" — issue #3364 Constraints). Both flags off
    # also exercises the joined multi-note composition.
    canvas_html = _shell(guard_canvas_enabled=False)
    canvas_slot = _status_slot(canvas_html)
    assert canvas_slot, "canvas-off fixture must render the slot"
    assert CANVAS_OFF in canvas_slot.group(0)
    assert 'data-tone="calm"' in canvas_slot.group(0)
    both_html = _shell(guard_update_flow_available=False, guard_canvas_enabled=False)
    both_slot = _status_slot(both_html)
    assert both_slot, "multi-flag fixture must render the slot"
    assert EDITING_PAUSED in both_slot.group(0)
    assert CANVAS_OFF in both_slot.group(0)

    # True-error fixture (WriteGuard is genuinely blocking writes — the vault
    # itself is unavailable, not a benign disabled-feature note): the slot
    # keeps the destructive/alarm tone.
    error_html = _shell(guard_writeguard_status="blocked")
    error_slot = _status_slot(error_html)
    assert error_slot, "true-error fixture must render the slot"
    error_markup = error_slot.group(0)
    assert 'data-tone="error"' in error_markup
    assert 'data-tone="calm"' not in error_markup

    error_tone_rule = re.search(
        r'\.workspace-status-slot\[data-tone="error"\]\{[^}]*color:\s*var\(--destructive\)',
        error_html,
    )
    assert error_tone_rule, "the error tone must use the destructive token"
