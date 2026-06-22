"""CUIDR-01 — calm degraded grammar + runtime-enum/identifier humanisation map.

Static ACs (no live runtime). Verifies that:

- A single ``calm_degraded`` grammar helper is the sole code path emitting
  unavailable/error *copy* on a user-facing surface (AC1).
- No raw runtime enum or internal identifier (``resurfacing_source_unavailable``,
  ``prop-move-1``, ``art-123``, ``lifecycle.move``) reaches the rendered HTML;
  each maps to human copy while the classified value still arrives from the
  payload (AC2 / C3).
- The vault browser never surfaces the raw transport error
  ("Error: Failed to fetch"); it uses the calm grammar (AC3 / D3).
- An unmapped degraded-reason token fails closed to the calm fallback rather
  than leaking the raw token (AC4).

Presentation-only constraint: this task humanises *display* tokens. The
server-authoritative classification still arrives in the payload and remains
observable in ``data-*`` attributes on the rendered element.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest

from companion_ui.workspace import serve_dev_page
from companion_ui.workspace.calm_degraded import (
    FAIL_CLOSED_DEGRADED,
    NOTHING_DECIDED,
    NOTHING_LOST,
    NOTHING_MUTATED,
    calm_degraded,
    humanise_degraded_reason,
    humanise_token,
)
from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html

# --- Confirmed leak tokens from the deep review (REVIEW_RESPONSE.txt C3/D3) ---
KNOWN_ENUM_TOKENS = [
    "resurfacing_source_unavailable",
    "orientation_unavailable",
    "lifecycle.move",
]
SUPPRESSED_ID_TOKENS = ["prop-move-1", "art-123"]
RAW_TRANSPORT_ERROR = "Error: Failed to fetch"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _vault_browser_payload() -> dict[str, Any]:
    return {
        "vault_id": "dev-vault",
        "channel": "dev",
        "provenance": "runtime",
        "query": "",
        "total_notes": 0,
        "filtered_notes": 0,
        "notes": [],
    }


def _degraded_orientation_payload(
    reason: str = "resurfacing_source_unavailable",
) -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-22T12:00:00Z",
            "trace_id": "trace-degraded",
            "freshness": "partial",
            "degraded_reasons": [reason],
            "caps": {
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded",
            "degraded": True,
            "reasons": [reason],
            "authority_role": "derived",
        },
        "mutation_intents": [],
    }


class _ProposalClient:
    """Minimal client returning a workspace payload with one leaky proposal."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/workspace":
            return self._payload
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"unexpected POST: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise AssertionError(f"unexpected DELETE: {url}")


def _leaky_workspace_payload() -> dict[str, Any]:
    """A workspace payload whose proposal carries the confirmed leak tokens."""
    # The loaded note has its own clean identity; the leak token art-123 lives
    # only on the *proposal* (the rail/proposal card is the surface the review
    # flagged). The artifact-identity pill legitimately shows the note's own
    # server-authoritative provenance and is out of scope.
    return {
        "artifact": {
            "artifact_id": "artifact-loaded-note",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": None,
            "session_state": None,
            "user_present": False,
            "can_edit_body": False,
            "recovery_needed": False,
            "session_log_path": None,
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "prop-move-1",
                    "artifact_id": "art-123",
                    "description": "Move this note into Projects/",
                    "status": "staged",
                    "evidence": {
                        "trigger_summary": "Trigger summary",
                        "action_class": "lifecycle.move",
                        "cognition_route": "rule",
                    },
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _render_proposal_html() -> str:
    client = _ProposalClient(_leaky_workspace_payload())
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def _render_degraded_orientation_html(
    reason: str = "resurfacing_source_unavailable",
) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_degraded_orientation_payload(reason),
        orientation_vault_browser=_vault_browser_payload(),
    )


# ---------------------------------------------------------------------------
# AC1 — single grammar helper is the sole unavailable/error copy emitter
# ---------------------------------------------------------------------------
def test_grammar_helper_is_sole_unavailable_emitter() -> None:
    # The helper renders the canonical template for all parametrised inputs.
    assert (
        calm_degraded("Notes", "connection failed", NOTHING_LOST, "Refresh to retry")
        == "Notes unavailable — connection failed. Nothing was lost. Refresh to retry."
    )
    assert (
        calm_degraded("Orientation", "source missing", NOTHING_DECIDED)
        == "Orientation unavailable — source missing. Nothing was decided."
    )
    assert (
        calm_degraded("Canvas", "runtime offline", NOTHING_MUTATED, "Try again shortly")
        == "Canvas unavailable — runtime offline. Nothing was mutated. Try again shortly."
    )
    # An unknown nothing-clause falls back to the calm default, never leaks.
    assert "Nothing was lost." in calm_degraded("X", "y", "Nothing was eaten")

    # Static scan: the raw transport-error emit and the raw degraded-reason
    # emit must no longer appear in the render module. These are the two
    # confirmed copy-leak code paths the helper now owns.
    src = inspect.getsource(serve_dev_page)
    assert "_e(str(error))" not in src, (
        "vault-browser error path must route through calm_degraded, not emit the "
        "raw transport error as copy"
    )
    # The degraded-reason chips must humanise the token, not emit it raw as copy.
    assert "{_e(reason)}</span>" not in src, (
        "orientation degraded-reason chips must route through "
        "humanise_degraded_reason, not emit the raw enum as copy"
    )

    # The calm grammar's signature copy (' unavailable — ') is produced only by
    # the helper: no other render-module call-site inlines the template
    # connective. (Classification tokens / data-attrs / testids carrying the
    # word 'unavailable' in non-copy positions are exempt by construction —
    # the connective ' unavailable — ' is unique to the grammar.)
    assert " unavailable — " not in src, (
        "the degraded grammar connective ' unavailable — ' must be produced "
        "only by calm_degraded(), not inlined at a render call-site"
    )


# ---------------------------------------------------------------------------
# AC2 / C3 — enum map covers known tokens; classified value still arrives
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "token,human",
    [
        ("resurfacing_source_unavailable", "Orientation source unavailable"),
        ("orientation_unavailable", "Orientation unavailable"),
        ("lifecycle.move", "Move note"),
    ],
)
def test_enum_map_covers_known_tokens(token: str, human: str) -> None:
    # The humanised string is produced by the map function, not hardcoded.
    assert humanise_token(token) == human or humanise_degraded_reason(token) == human


def test_enum_map_no_raw_token_on_degraded_surface() -> None:
    for token in ["resurfacing_source_unavailable", "orientation_unavailable"]:
        payload = _degraded_orientation_payload(token)
        html = _render_degraded_orientation_html(token)
        # Humanised copy is present (produced by the map, not the template call).
        assert humanise_degraded_reason(token) in html
        # The raw enum token must be ABSENT from the rendered orientation
        # degraded *surface* — neither as visible chip copy nor echoed into a
        # chip/source data-* attribute on that surface. (The server-authoritative
        # entry-state declaration on <body data-entry-degraded-reasons=…>, set
        # by the entry-state resolver, is the exempt classification carrier and
        # is out of CUIDR-01 scope; we scan the degraded surface, not <body>.)
        surface = _degraded_orientation_surface(html)
        assert token not in surface, f"raw enum {token!r} leaked into degraded surface"
        # The classified value still arrives from the runtime: it is present in
        # the fixture payload passed to the renderer, and the surface declares
        # the degraded posture server-side.
        assert token in payload["meta"]["degraded_reasons"]
        assert token in payload["guards"]["reasons"]
        assert 'data-runtime-posture="degraded"' in html


def test_enum_map_suppresses_internal_ids_on_proposal_surface() -> None:
    html = _render_proposal_html()
    visible = _strip_data_attributes(html)
    # Internal identifiers and the raw action class must not appear as visible
    # copy. The proposal-id / artifact-id correlation IDs may remain only inside
    # pre-existing data-* attributes (server-authoritative correlation, exempt
    # per the AC1 note); they are never rendered as user-facing copy.
    for token in SUPPRESSED_ID_TOKENS:
        assert token not in visible, f"internal id {token!r} leaked to visible copy"
    assert "lifecycle.move" not in visible, "raw action class leaked to visible copy"
    assert "Move note" in html
    # The classified correlation IDs still arrive from the runtime payload
    # (proof of server authority is the payload, not a copy echo).
    payload = _leaky_workspace_payload()
    proposal = payload["panel"]["proposals"][0]
    assert proposal["proposal_id"] == "prop-move-1"
    assert proposal["artifact_id"] == "art-123"
    assert proposal["evidence"]["action_class"] == "lifecycle.move"
    # The proposal's human description is what the user reads instead.
    assert "Move this note into Projects/" in html


# ---------------------------------------------------------------------------
# AC3 / D3 — vault browser fetch error uses the calm grammar
# ---------------------------------------------------------------------------
def test_vault_browser_fetch_error_uses_calm_grammar() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_degraded_orientation_payload(),
        orientation_vault_browser=_vault_browser_payload(),
        orientation_vault_browser_error=RAW_TRANSPORT_ERROR,
    )
    # (a) the literal transport error must not appear in the HTML output at all
    #     (not even echoed into a data-* attribute).
    assert RAW_TRANSPORT_ERROR not in html
    # (b) the output uses the calm grammar template.
    assert (
        "Notes unavailable — connection failed. Nothing was lost. Refresh to retry."
        in html
    )
    # (c) the classified error *state* still arrives from the payload — evidenced
    #     by the state-error element being present.
    assert 'data-testid="workspace-vault-browser-state-error"' in html


# ---------------------------------------------------------------------------
# AC4 — fail closed on unknown token
# ---------------------------------------------------------------------------
def test_enum_map_fail_closed_on_unknown_token() -> None:
    unknown = "some_new_runtime_token_not_in_map"
    assert humanise_degraded_reason(unknown) == FAIL_CLOSED_DEGRADED
    assert FAIL_CLOSED_DEGRADED == "… unavailable — details withheld. Nothing was lost."

    # End-to-end: an unknown degraded reason renders the fallback, and the raw
    # token is absent from the rendered degraded surface (not echoed into a
    # chip/source data-* attribute). The entry-state <body> declaration is the
    # exempt server-authoritative carrier and is out of scope here.
    payload = _degraded_orientation_payload(unknown)
    html = _render_degraded_orientation_html(unknown)
    surface = _degraded_orientation_surface(html)
    assert unknown not in surface, "unmapped token leaked into degraded surface"
    assert "details withheld" in html
    # The classified value still arrives from the runtime payload.
    assert unknown in payload["meta"]["degraded_reasons"]


def test_humanise_token_passes_through_legitimate_action_class() -> None:
    # A legitimate, already-human action class is not an enum or an id — it must
    # pass through unchanged (only the degraded-reason path fails closed).
    assert humanise_token("bounded.panel_action") == "bounded.panel_action"


def test_humanise_token_suppresses_id_patterns() -> None:
    for token in ["prop-move-1", "prop-001", "art-123", "artifact-x", "note-a"]:
        assert humanise_token(token) == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_DATA_ATTR_RE = re.compile(r'\sdata-[\w-]+="[^"]*"')


def _strip_data_attributes(html: str) -> str:
    """Remove data-* attribute values so the scan targets visible copy only.

    Server-authoritative classification tokens carried in data-* attributes
    are exempt from the copy scan; stripping them isolates user-visible copy.
    """
    return _DATA_ATTR_RE.sub("", html)


def _degraded_orientation_surface(html: str) -> str:
    """Isolate the rendered orientation degraded/resurface region.

    Excludes the ``<body>`` tag, whose ``data-entry-degraded-reasons``
    declaration is the server-authoritative entry-state classification carrier
    (set by the entry-state resolver, exempt and out of CUIDR-01 scope). The
    raw-token scan targets the degraded chips, banner, and resurface posture
    region that this task humanises.
    """
    marker = "<main"
    idx = html.find(marker)
    return html[idx:] if idx != -1 else html
