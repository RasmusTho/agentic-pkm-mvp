"""Guidance layer — opt-in explanatory callouts (#1788, SEP-06).

Split "help" into its two kinds (`docs/SYSTEM_ENTRY_POINT/GUIDANCE_LAYER.md`;
`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Data-attribute vocabulary —
``data-guidance="on"``, absent = off; §Intent vocabulary —
``guidance.toggle``, UI-local; design package §Earned guidance, not embedded
help):

- evidence (provenance lines, authority tags, receipt pills) is always
  present, terse, and entirely unaffected by this layer;
- explanation (what is this surface, how does re-entry work) is opt-in,
  off by default in every entry state, and decays to nothing;
- the ⓘ toggle (topbar, overlay heads, re-entry card) flips the shell-root
  attribute only — nothing durable persisted, no authority, no
  save/projection endpoint; the stored *default* belongs to the Settings
  drawer (#1789) and is reconciled, not duplicated, here;
- callouts may deep-link into the shipped ``/help`` guide (#1755), which
  remains the long-form document.

Like ``test_overlay_host.py``, the pure vocabulary in ``guidance_layer.py``
is the contract the in-page controller mirrors; tests assert both.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.guidance_layer import (
    GUIDANCE_ATTRIBUTE,
    GUIDANCE_CALLOUTS,
    GUIDANCE_ON,
    GUIDANCE_TOGGLE_INTENT,
    GUIDANCE_TOGGLE_SURFACES,
    HELP_GUIDE_ROUTE,
    guidance_enabled,
    guidance_toggle_markup,
    toggled_guidance,
)
from companion_ui.workspace.overlay_host import SHIPPED_OVERLAY_OCCUPANTS
from companion_ui.workspace.serve_dev_page import render_index_html

# ---------------------------------------------------------------------------
# Fixtures (workspace fields mirror test_settings_drawer / test_overlay_host;
# orientation payload mirrors test_reentry_orientation_treatment)
# ---------------------------------------------------------------------------

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
_GAP_FULL_MIST = timedelta(days=1)


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Guidance Note",
        "note_path": "Notes/guidance.md",
        "artifact_id": "art-guidance",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-guidance",
        "body": "# Note\n\nCanonical source paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-guidance",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 1,
        "panel_proposals": [
            {
                "proposal_id": "prop-1",
                "description": "Append summary section",
                "proposal_class": "governed",
                "status": "proposed",
                "actions": [{"action_id": "confirm", "label": "Confirm"}],
            }
        ],
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
        "governance_receipts": [
            {
                "data_testid": "receipt-pill",
                "label": "queue_review logged",
                "display_timestamp": "2026-06-10 11:58",
                "outcome": "logged",
            }
        ],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _render(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _orientation_payload(gap: timedelta = _GAP_FULL_MIST) -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-orientation-guidance",
            "freshness": "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": [],
        },
        "leave_point": {
            "status": "present",
            "artifact_ref": {
                "artifact_id": "art-resume",
                "note_path": "Notes/resume.md",
                "title": "Resume plan",
            },
            "label": "Resume the runtime API contract",
            "captured_at": _iso(_AS_OF - gap),
            "last_session_id": "session-123",
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        },
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "orientation.signals"},
        },
        "guards": {"read_only": True, "runtime_posture": "healthy"},
    }


def _render_orientation(**kwargs: Any) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(**kwargs),
    )


def _body_tag(html: str) -> str:
    match = re.search(r"<body[^>]*>", html)
    assert match, "page must render a body tag"
    return match.group(0)


def _guidance_script(html: str) -> str:
    start = html.index("/* guidance-layer-controller */")
    end = html.index("/* /guidance-layer-controller */", start)
    return html[start:end]


def _callout_fragments(html: str) -> dict[str, str]:
    fragments: dict[str, str] = {}
    for match in re.finditer(
        r'<div class="callout guidance guidance-callout"[^>]*'
        r'data-guidance-surface="([^"]+)"[^>]*>.*?</div>',
        html,
        re.S,
    ):
        fragments[match.group(1)] = match.group(0)
    return fragments


# ---------------------------------------------------------------------------
# AC1: off by default in every entry state — no explanatory callouts shown
# ---------------------------------------------------------------------------


def test_guidance_off_by_default() -> None:
    # Pure model: absent is off; only the exact spec value "on" enables.
    assert guidance_enabled(None) is False
    assert guidance_enabled("") is False
    assert guidance_enabled("true") is False
    assert guidance_enabled(GUIDANCE_ON) is True
    assert GUIDANCE_ATTRIBUTE == "data-guidance"
    assert GUIDANCE_ON == "on"

    # shell_active: the shell root never declares data-guidance server-side
    # — the established-user default is off.
    workspace = _render()
    assert "data-guidance" not in _body_tag(workspace)

    # orienting (full mist, re-entry card present): off by default too.
    orienting = _render_orientation()
    assert "data-guidance" not in _body_tag(orienting)

    # The visibility gate hides every callout while the attribute is absent:
    # callouts may exist in the DOM but display only under
    # body[data-guidance="on"].
    for html in (workspace, orienting):
        assert ".guidance-callout { display: none; }" in html
        assert 'body[data-guidance="on"] .guidance-callout' in html

    # No alternate reveal path: nothing outside the guidance layer keys on
    # the attribute (every data-guidance CSS selector is .guidance-scoped).
    for selector in re.findall(
        r'([^{}]*\[data-guidance="on"\][^{]*)\{', workspace
    ):
        assert ".guidance-" in selector, (
            f"non-guidance element keys on data-guidance: {selector!r}"
        )


# ---------------------------------------------------------------------------
# AC2: toggling reveals callouts on the shell and open overlays; toggling
# again removes them
# ---------------------------------------------------------------------------


def test_toggle_reveals_and_hides_callouts() -> None:
    # Pure model round-trip: off -> on -> off (attribute removed).
    assert toggled_guidance(None) == GUIDANCE_ON
    assert toggled_guidance(GUIDANCE_ON) is None
    assert toggled_guidance(toggled_guidance(None)) is None

    html = _render()
    fragments = _callout_fragments(html)

    # Callouts are present (hidden) for the shell and every shipped
    # overlay-host occupant, so one attribute flip reveals them everywhere
    # at once — shell plus whichever overlays are open.
    expected = {"shell", *SHIPPED_OVERLAY_OCCUPANTS}
    assert expected <= set(fragments), (
        f"missing callouts for: {expected - set(fragments)}"
    )
    for surface, fragment in fragments.items():
        assert f'data-testid="guidance-callout-{surface}"' in fragment
        assert 'data-authority="explanation"' in fragment

    # The re-entry card carries its own callout on the orienting state.
    orienting = _render_orientation()
    reentry_card = re.search(
        r'<section class="reentry-card".*?</section>', orienting, re.S
    )
    assert reentry_card, "full mist must render the re-entry card"
    assert 'data-testid="guidance-callout-reentry"' in reentry_card.group(0)

    # The controller mirrors the pure model: set on, remove on re-toggle.
    script = _guidance_script(html)
    assert "setAttribute('data-guidance', 'on')" in script
    assert "removeAttribute('data-guidance')" in script

    # Integration with /help (#1755): callouts deep-link into the shipped
    # long-form guide; the guidance layer does not replace it.
    assert HELP_GUIDE_ROUTE == "/help"
    for surface, fragment in fragments.items():
        anchor = GUIDANCE_CALLOUTS[surface]["help_anchor"]
        assert f'href="{HELP_GUIDE_ROUTE}#{anchor}"' in fragment


# ---------------------------------------------------------------------------
# AC3: the toggle is UI-local — nothing durable persisted, no save/projection
# endpoint reached
# ---------------------------------------------------------------------------


def test_guidance_toggle_is_ui_local() -> None:
    html = _render()
    script = _guidance_script(html)

    # No transport of any kind, and no storage of any kind — not even
    # session storage: reload -> guidance off again (the stored *default*
    # belongs to the Settings drawer, #1789, and is not written here).
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "WebSocket",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "/api/",
    ):
        assert forbidden not in script, (
            f"guidance controller must stay UI-local; found {forbidden!r}"
        )

    # The toggle affordance carries the declared UI-local intent and flips
    # the layer through the controller only (no href, no form action).
    toggle = guidance_toggle_markup("topbar")
    assert GUIDANCE_TOGGLE_INTENT == "guidance.toggle"
    assert f'data-intent="{GUIDANCE_TOGGLE_INTENT}"' in toggle
    assert 'type="button"' in toggle
    assert "guidanceLayer.toggle()" in toggle
    assert "href=" not in toggle

    # The spec intent table says guidance.toggle never routes through the
    # governed pipeline: the rendered toggles carry no confirm transport.
    for match in re.finditer(
        r'<button[^>]*data-intent="guidance.toggle"[^>]*>', html
    ):
        assert 'onclick="guidanceLayer.toggle()"' in match.group(0)

    # Reconciliation with the Settings drawer default (#1789): the drawer
    # stays the single owner of the stored default; the guidance controller
    # only observes the root attribute it shares.
    assert "companion.settingsPreferences.v1" not in script
    assert "MutationObserver" in script


# ---------------------------------------------------------------------------
# AC4: evidence elements render identically with guidance on and off
# ---------------------------------------------------------------------------


def test_evidence_unaffected_by_guidance() -> None:
    html = _render()

    # Evidence is present on the page: receipt pills, authority tags, and
    # provenance lines all render without the guidance attribute set.
    assert 'data-testid="receipt-pill"' in html
    assert "data-authority-role=" in html
    assert 'data-testid="workspace-vault-provenance"' in html

    # The server render takes no guidance input at all: the toggle is
    # client-side CSS visibility, so the rendered evidence markup is the
    # same bytes in both states by construction. Assert the gate cannot
    # touch evidence: every rule keying on data-guidance selects only
    # .guidance-scoped elements...
    for selector in re.findall(r'([^{}]*\[data-guidance[^{]*)\{', html):
        assert ".guidance-" in selector, (
            f"evidence may not key on data-guidance: {selector!r}"
        )

    # ...and no evidence element lives inside a guidance callout, so
    # revealing/hiding callouts cannot show or hide evidence.
    for surface, fragment in _callout_fragments(html).items():
        for evidence_marker in (
            "receipt-pill",
            "data-authority-role=",
            "provenance",
        ):
            assert evidence_marker not in fragment, (
                f"evidence {evidence_marker!r} inside guidance callout "
                f"{surface!r}"
            )

    # Guidance adds explanation only: callouts are static prose + a help
    # link; they restate no runtime state (no counts, statuses, outcomes).
    for fragment in _callout_fragments(html).values():
        assert 'role="note"' in fragment
        assert "<button" not in fragment


# ---------------------------------------------------------------------------
# AC5: guidance reachable from the re-entry card and each shipped overlay head
# ---------------------------------------------------------------------------


def test_guidance_affordance_present_on_reentry_and_overlay_heads() -> None:
    html = _render()

    # Topbar ⓘ (issue scope: topbar + overlay heads + re-entry card).
    assert 'data-testid="guidance-toggle-topbar"' in html

    # Every shipped overlay-host occupant head carries the ⓘ affordance.
    for occupant in SHIPPED_OVERLAY_OCCUPANTS:
        assert f'data-testid="guidance-toggle-{occupant}"' in html, (
            f"shipped occupant {occupant!r} must carry the guidance toggle"
        )
        assert occupant in GUIDANCE_TOGGLE_SURFACES

    # The re-entry card (orienting, full mist) carries the ⓘ affordance and
    # the guidance controller ships with the orientation page.
    orienting = _render_orientation()
    reentry_card = re.search(
        r'<section class="reentry-card".*?</section>', orienting, re.S
    )
    assert reentry_card, "full mist must render the re-entry card"
    assert 'data-testid="guidance-toggle-reentry"' in reentry_card.group(0)
    assert "/* guidance-layer-controller */" in orienting

    # The system map (#1787) is a shipped occupant and is covered by the
    # loops above; its callout copy lives in the shared registry like every
    # other surface (extension point: later surfaces register copy +
    # render the toggle/callout helpers from their own head).
    assert "map" in GUIDANCE_CALLOUTS
    assert "map" in GUIDANCE_TOGGLE_SURFACES
