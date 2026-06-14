"""Memory candidate review drawer — right-drawer review UI (#1793, SEP-09b).

The only admissible place where candidate → memory promotion is decided, and
it decides nothing itself (`docs/SYSTEM_ENTRY_POINT/MEMORY_REVIEW_DRAWER.md`
issue (b); `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Intent vocabulary
``memory.*``, §Surface composition, §Design-vs-owner-doc correction — memory
review outcomes; `docs/adr/ADR-0009-orientation-memory-candidate-intent.md`):

- a right drawer mounted on the shared overlay host (``memory.open``),
  reached from the topbar and from the re-entry card's unresolved-inspect
  affordance, dismissing back to the document anchor (no route reset);
- renders the "Unreviewed memory is not semantic authority" callout and the
  pending candidates with why-now, provenance, and the server-declared
  authority posture;
- four actions: Accept / Reject / Revise (governed — routed through the
  #1792 decision endpoints; runtime outcome AND runtime receipt rendered)
  and Defer (non-terminal — no receipt exists, none is invented);
- the UI never classifies candidate-worthiness locally and never renders a
  candidate as accepted memory before the runtime says so: a refusal (409)
  renders calm with the candidate still pending.

Like ``test_overlay_host.py``, the pure projections in
``memory_review_drawer.py`` are the contract the in-page controller mirrors;
tests assert both.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pytest

from companion_ui.workspace.memory_review_drawer import (
    GOVERNED_REVIEW_ACTIONS,
    MEMORY_REVIEW_CALLOUT,
    MEMORY_REVIEW_FRAGMENT_ROUTE,
    MEMORY_REVIEW_QUEUE_ENDPOINT,
    NON_TERMINAL_REVIEW_ACTIONS,
    REVIEW_ACTION_INTENTS,
    REVIEW_ACTIONS,
    decision_endpoint_path,
    decision_outcome_view,
    memory_review_drawer_markup,
    memory_review_queue_fragment,
    memory_review_unavailable_fragment,
)
from companion_ui.workspace.overlay_host import (
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    OverlayHostState,
    dismiss,
    mount,
)
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html

# ---------------------------------------------------------------------------
# Fixtures (workspace fields mirror test_overlay_host; orientation payload
# mirrors test_reentry_orientation_treatment; queue/decision payloads mirror
# the #1792 runtime projections in app/api/routes/companion.py)
# ---------------------------------------------------------------------------


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
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
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _render_workspace(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _orientation_payload(
    *, pending_candidates: int = 2, captured_at: str | None = "2026-06-09T12:00:00Z"
) -> dict[str, Any]:
    """Orientation snapshot resolving to a full-mist re-entry card by default."""
    leave_point = None
    if captured_at is not None:
        leave_point = {
            "status": "present",
            "artifact_ref": {
                "artifact_id": "art-resume",
                "note_path": "Notes/resume.md",
                "title": "Resume plan",
            },
            "label": "Resume the runtime API contract",
            "captured_at": captured_at,
            "last_session_id": "session-123",
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        }
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-10T12:00:00Z",
            "trace_id": "trace-orientation-1",
            "freshness": "fresh",
            "stale_after": "2026-06-10T12:05:00Z",
            "degraded_reasons": [],
            "caps": {
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "mutation_intents": 0,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": leave_point,
        "open_loops": [
            {
                "id": "loop-1",
                "label": "Open loop label 1",
                "status": "open",
                "handoff_hint": "panel",
                "artifact_ref": {
                    "artifact_id": "art-loop-1",
                    "note_path": "Notes/loop-1.md",
                    "title": "Loop 1",
                },
                "authority_role": "derived",
                "source_ref": {"kind": "runtime_signal", "ref": "orientation.signals"},
            }
        ],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "memory": {
            "pending_candidate_count": pending_candidates,
            "source_ref": {
                "kind": "agent_memory.review_queue",
                "ref": "agent_memory.review_queue",
                "label": "memory candidate review queue",
            },
        },
        "governance": {
            "pending_proposal_count": 1,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "logged",
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "orientation.signals"},
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "healthy",
            "degraded": False,
            "reasons": [],
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "mutation_intents": [],
    }


def _render_orientation(orientation: dict[str, Any]) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        orientation=orientation,
    )


def _candidate(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate_id": f"cand-{idx}",
        "title": f"Candidate title {idx}",
        "why_now": (
            f"Awaiting explicit review: inferred preference candidate "
            f"from agent:companion-{idx}. {MEMORY_REVIEW_CALLOUT}"
        ),
        "proposed_memory_type": "preference",
        "inferred": True,
        "source_refs": [f"Notes/source-{idx}.md"],
        "derived_from": f"session-{idx}",
        "generated_by": f"agent:companion-{idx}",
        "revision_of": None,
        "authority_posture": {
            "authority": "non_authoritative",
            "authority_role": "candidate",
            "review_posture": "pending_review",
            "semantic_authority": False,
        },
    }
    base.update(overrides)
    return base


def _queue_payload(candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = candidates if candidates is not None else [_candidate(1), _candidate(2)]
    return {
        "source": "agent_memory.review_queue",
        "review_callout": MEMORY_REVIEW_CALLOUT,
        "pending_count": len(items),
        "candidates": items,
        "source_ref": {
            "kind": "agent_memory.review_queue",
            "ref": "agent_memory.review_queue",
            "label": "memory candidate review queue",
        },
    }


def _receipt(outcome: str = "promoted", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "receipt_id": "promo-receipt-1",
        "kind": "agent_memory.review_decision",
        "source": "agent_memory.promotion",
        "outcome": outcome,
        "candidate_id": "cand-1",
        "decided_by": "companion-ui:reviewer",
        "decided_at": "2026-06-10T12:00:00Z",
        "decision_notes": None,
        "revision_of": None,
        "recorded_at": "2026-06-10T12:00:01Z",
    }
    base.update(overrides)
    return base


def _decision_payload(status: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": status,
        "candidate_id": "cand-1",
        "candidate_pending": status == "deferred",
        "receipt": None if status == "deferred" else _receipt(),
        "revision_candidate_id": None,
        "detail": None,
    }
    base.update(overrides)
    return base


def _drawer(html: str) -> str:
    m = re.search(
        r'<aside[^>]*data-testid="memory-review-drawer".*?</aside>', html, re.S
    )
    assert m, "memory review drawer must render"
    return m.group(0)


def _drawer_script(html: str) -> str:
    m = re.search(
        r"/\* memory-review-drawer-controller \*/(.*?)"
        r"/\* /memory-review-drawer-controller \*/",
        html,
        re.S,
    )
    assert m, "memory review drawer controller script must render"
    return m.group(1)


def _host_script(html: str) -> str:
    m = re.search(
        r"/\* overlay-host-controller \*/(.*?)/\* /overlay-host-controller \*/",
        html,
        re.S,
    )
    assert m, "overlay-host controller script must render"
    return m.group(1)


def _reentry_card(html: str) -> str:
    m = re.search(r'<section[^>]*data-region="reentry-card".*?</section>', html, re.S)
    assert m, "re-entry card must render"
    return m.group(0)


class _FakeClient:
    """Minimal WorkspaceHttpClient stand-in recording proxy calls."""

    def __init__(
        self,
        get_responses: dict[str, Any] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.get_responses = get_responses or {}
        self.get_error = get_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if self.get_error:
            raise self.get_error
        return self.get_responses.get(url, {})


def _drive_get(handler_cls: type, path: str) -> bytes:
    instance = handler_cls.__new__(handler_cls)
    instance.path = path
    instance.headers = {}
    chunks: list[bytes] = []
    instance.wfile = io.BytesIO()
    instance.wfile.write = chunks.append  # type: ignore[method-assign]
    instance.send_response = lambda *_: None  # type: ignore[method-assign]
    instance.send_header = lambda *_: None  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.do_GET()
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# AC1: the drawer renders candidates with the not-semantic-authority callout
# and the four actions; Accept/Reject/Revise surface the runtime outcome and
# receipt
# ---------------------------------------------------------------------------


def test_drawer_renders_candidates_and_governed_review_outcomes() -> None:
    # The declared action vocabulary is exactly the spec's four memory-review
    # intents: three governed review outcomes plus the one non-terminal defer.
    assert REVIEW_ACTIONS == ("accept", "reject", "revise", "defer")
    assert GOVERNED_REVIEW_ACTIONS == ("accept", "reject", "revise")
    assert NON_TERMINAL_REVIEW_ACTIONS == ("defer",)
    assert REVIEW_ACTION_INTENTS == {
        "accept": "memory.accept",
        "reject": "memory.reject",
        "revise": "memory.revise",
        "defer": "memory.defer",
    }

    # Drawer shell: right-drawer overlay occupant with the normative callout.
    markup = memory_review_drawer_markup()
    assert MEMORY_REVIEW_CALLOUT in markup
    assert 'data-testid="memory-review-callout"' in markup
    assert 'data-overlay-id="memory"' in markup
    assert 'data-drawer-side="right"' in markup
    assert 'data-authority="proposal"' in markup

    # Queue fragment: pending candidates with why-now, provenance, the
    # server-declared authority tag, and the four actions per candidate.
    payload = _queue_payload()
    fragment = memory_review_queue_fragment(payload)
    rows = re.findall(r'data-testid="memory-review-candidate"', fragment)
    assert len(rows) == 2
    assert 'data-pending-count="2"' in fragment
    for candidate in payload["candidates"]:
        assert f'data-candidate-id="{candidate["candidate_id"]}"' in fragment
        assert candidate["title"] in fragment
        assert candidate["why_now"] in fragment  # rendered verbatim
        assert candidate["source_refs"][0] in fragment
        assert candidate["generated_by"] in fragment
    assert 'data-testid="memory-candidate-why-now"' in fragment
    assert 'data-testid="memory-candidate-provenance"' in fragment
    assert 'data-testid="memory-candidate-authority-tag"' in fragment
    for action in REVIEW_ACTIONS:
        buttons = re.findall(
            rf'<button[^>]*data-testid="memory-action-{action}"[^>]*>', fragment
        )
        assert len(buttons) == 2, f"every candidate row offers {action}"
        for button in buttons:
            assert f'data-intent="{REVIEW_ACTION_INTENTS[action]}"' in button
            governed = "true" if action in GOVERNED_REVIEW_ACTIONS else "false"
            assert f'data-governed="{governed}"' in button
    defer_button = re.search(
        r'<button[^>]*data-testid="memory-action-defer"[^>]*>', fragment
    )
    assert defer_button and 'data-non-terminal="true"' in defer_button.group(0)
    # Empty queue renders a calm empty state, never an invented candidate.
    empty = memory_review_queue_fragment(_queue_payload(candidates=[]))
    assert 'data-testid="memory-review-empty"' in empty
    assert 'data-testid="memory-review-candidate"' not in empty
    # Unreachable runtime renders a calm unavailable state.
    unavailable = memory_review_unavailable_fragment("connection refused")
    assert 'data-testid="memory-review-unavailable"' in unavailable

    # Governed outcomes: the rendered outcome and receipt are the runtime's.
    accepted = decision_outcome_view(
        action="accept", status_code=200, payload=_decision_payload("accepted")
    )
    assert accepted["kind"] == "governed_outcome"
    assert accepted["status"] == "accepted"
    assert accepted["candidate_pending"] is False
    assert accepted["receipt"] == _receipt()  # verbatim runtime projection

    rejected = decision_outcome_view(
        action="reject",
        status_code=200,
        payload=_decision_payload("rejected", receipt=_receipt(outcome="rejected")),
    )
    assert rejected["status"] == "rejected"
    assert rejected["receipt"]["outcome"] == "rejected"
    assert rejected["receipt"]["receipt_id"] == "promo-receipt-1"

    revised = decision_outcome_view(
        action="revise",
        status_code=200,
        payload=_decision_payload(
            "revised",
            receipt=_receipt(outcome="revised"),
            revision_candidate_id="cand-1-rev",
        ),
    )
    assert revised["status"] == "revised"
    assert revised["receipt"]["outcome"] == "revised"
    assert revised["revision_candidate_id"] == "cand-1-rev"

    # A governed refusal (409 — e.g. accept dry-run refused) renders calm:
    # the candidate is still pending and no receipt exists.
    refused = decision_outcome_view(
        action="accept",
        status_code=409,
        payload={
            "detail": {
                "error": "promotion_refused",
                "message": "semantic memory requires stricter evidence",
            }
        },
    )
    assert refused["kind"] == "refused"
    assert refused["candidate_pending"] is True
    assert refused["receipt"] is None
    assert "semantic memory requires stricter evidence" in refused["message"]

    # Defer is non-terminal: pending, no receipt (AC for the runtime half;
    # the UI renders exactly that).
    deferred = decision_outcome_view(
        action="defer", status_code=200, payload=_decision_payload("deferred")
    )
    assert deferred["kind"] == "deferred"
    assert deferred["candidate_pending"] is True
    assert deferred["receipt"] is None

    # Rendered shell: the drawer is a shipped occupant of the overlay host,
    # reachable from the topbar, and the controller routes decisions through
    # the #1792 endpoints (same-origin proxy).
    assert "memory" in SHIPPED_OVERLAY_OCCUPANTS
    assert "memory" in SHIPPED_TOPBAR_SURFACES
    html = _render_workspace()
    drawer = _drawer(html)
    assert MEMORY_REVIEW_CALLOUT in drawer
    icon = re.search(
        r'<button[^>]*data-testid="workspace-surface-icon-memory"[^>]*>', html
    )
    assert icon, "topbar must render the memory surface icon"
    assert 'data-intent="memory.open"' in icon.group(0)
    assert "overlayHost.mount('memory')" in icon.group(0)
    assert "register('memory'" in _drawer_script(html)
    script = _drawer_script(html)
    assert MEMORY_REVIEW_FRAGMENT_ROUTE in script
    assert "/api/companion/memory/review-queue/" in script
    assert "/decision" in script
    assert decision_endpoint_path("cand 1") == (
        "/api/companion/memory/review-queue/cand%201/decision"
    )

    # Proxy wiring: the page server serves the queue fragment same-origin and
    # admits the decision POST path.
    client = _FakeClient(get_responses={MEMORY_REVIEW_QUEUE_ENDPOINT: payload})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")
    body = _drive_get(handler_cls, MEMORY_REVIEW_FRAGMENT_ROUTE).decode("utf-8")
    assert client.get_calls == [(MEMORY_REVIEW_QUEUE_ENDPOINT, {})]
    assert 'data-testid="memory-review-candidate"' in body
    instance = handler_cls.__new__(handler_cls)
    assert instance._post_path_allowed(
        "/api/companion/memory/review-queue/cand-1/decision"
    )
    assert not instance._post_path_allowed("/api/companion/memory/review-queue")


# ---------------------------------------------------------------------------
# AC2: the UI never classifies candidate-worthiness locally and never renders
# a candidate as accepted memory before the runtime says so
# ---------------------------------------------------------------------------


def test_no_local_classification_or_premature_promotion() -> None:
    # The rendered outcome comes from the runtime payload's declared status,
    # never from the action the UI requested.
    crossed = decision_outcome_view(
        action="accept",
        status_code=200,
        payload=_decision_payload("rejected", receipt=_receipt(outcome="rejected")),
    )
    assert crossed["status"] == "rejected"

    # A refusal is never rendered as acceptance: pending, receipt-free, calm.
    refused = decision_outcome_view(
        action="accept",
        status_code=409,
        payload={"detail": {"error": "promotion_refused", "message": "refused"}},
    )
    assert refused["kind"] == "refused"
    assert refused["status"] == "pending"
    assert refused["candidate_pending"] is True
    assert refused["receipt"] is None

    # No declared outcome -> nothing is invented; the candidate stays pending.
    unconfirmed = decision_outcome_view(action="accept", status_code=200, payload={})
    assert unconfirmed["kind"] == "unconfirmed"
    assert unconfirmed["candidate_pending"] is True
    assert unconfirmed["receipt"] is None

    # Unreachable runtime -> no decision was recorded, none is rendered.
    unavailable = decision_outcome_view(action="reject", status_code=0, payload={})
    assert unavailable["kind"] == "unavailable"
    assert unavailable["candidate_pending"] is True
    assert unavailable["receipt"] is None

    # Defer never carries a receipt — even a malformed payload that smuggles
    # one in is not rendered (no receipt invented, none echoed).
    deferred = decision_outcome_view(
        action="defer",
        status_code=200,
        payload=_decision_payload("deferred", receipt=_receipt()),
    )
    assert deferred["receipt"] is None
    assert deferred["candidate_pending"] is True

    # Undeclared actions are rejected, not improvised.
    with pytest.raises(ValueError):
        decision_outcome_view(action="promote", status_code=200, payload={})

    # The queue fragment renders the server-declared posture verbatim and
    # marks every candidate pending and non-authoritative; it never renders
    # acceptance language.
    custom = _candidate(
        1,
        authority_posture={
            "authority": "non_authoritative",
            "authority_role": "candidate",
            "review_posture": "custom-declared-posture",
            "semantic_authority": False,
        },
    )
    fragment = memory_review_queue_fragment(_queue_payload(candidates=[custom]))
    assert "custom-declared-posture" in fragment  # rendered as supplied
    row = re.search(
        r'<article[^>]*data-testid="memory-review-candidate"[^>]*>', fragment
    )
    assert row
    assert 'data-review-state="pending"' in row.group(0)
    assert 'data-authority="non_authoritative"' in row.group(0)
    assert 'data-semantic-authority="false"' in row.group(0)
    assert 'data-inferred="true"' in row.group(0)  # declared, not re-derived
    assert "accepted" not in fragment
    assert "promoted" not in fragment

    # The controller mirrors the pure projection: the decided-outcome
    # vocabulary is declared on the drawer (from the runtime contract), never
    # hardcoded in the script — the script carries no outcome literals and no
    # local classification heuristics.
    html = _render_workspace()
    drawer = _drawer(html)
    assert 'data-decided-statuses="accepted rejected revised"' in drawer
    script = _drawer_script(html)
    assert "data-decided-statuses" in script
    for forbidden in (
        "'accepted'",
        '"accepted"',
        "'promoted'",
        '"promoted"',
        "'rejected'",
        '"rejected"',
        "'revised'",
        '"revised"',
        "confidence",
        "classif",
        "Math.random",
    ):
        assert forbidden not in script, (
            f"drawer controller must not locally produce {forbidden}"
        )
    # The receipt section renders only runtime-supplied receipt fields.
    assert "payload.receipt" in script
    assert "memory-outcome-receipt" in script


# ---------------------------------------------------------------------------
# AC3: the drawer is reachable from the re-entry inspect affordance and
# dismisses to the anchor
# ---------------------------------------------------------------------------


def test_reachable_from_reentry_and_dismisses_to_anchor() -> None:
    # Pure host model: memory is a shipped occupant; mount + dismiss restores
    # the exact anchor context — no route reset, no data loss.
    before = OverlayHostState(
        anchor_note_path="Notes/note.md",
        route="/?note_path=Notes%2Fnote.md",
        scroll_owner="note-body",
        rail_state="open",
        staged_suggestion_ids=("s-1",),
        open_loop_count=3,
    )
    mounted = mount(before, "memory")
    assert mounted.stack == ("memory",)
    assert dismiss(mounted) == before

    # Orientation surface (full mist): the re-entry card's unresolved-inspect
    # affordance emits memory.open and mounts the drawer on the host.
    html = _render_orientation(_orientation_payload(pending_candidates=2))
    card = _reentry_card(html)
    inspect = re.search(r'<a[^>]*data-testid="reentry-inspect"[^>]*>', card)
    assert inspect, "the re-entry card must keep its inspect affordance"
    assert 'data-intent="memory.open"' in inspect.group(0)
    assert "overlayHost.mount('memory')" in inspect.group(0)
    # Graceful no-JS fallback still routes to the open-loops section.
    assert 'href="#workspace-orientation-open-loops"' in inspect.group(0)
    # Pending memory candidates surface as a count, never an enumeration.
    assert "2 memory candidates" in card

    # The drawer and the host substrate are present on the orientation
    # surface, so inspect opens the drawer in place over the entry substrate.
    assert 'data-testid="memory-review-drawer"' in html
    assert 'data-region="overlay-host"' in html
    assert "register('memory'" in _drawer_script(html)
    assert "Escape" in _host_script(html)  # Esc -> overlay.dismiss (host-owned)

    # No card, no affordance, no drawer: shapes without the re-entry card do
    # not grow a dead memory affordance on the orientation surface.
    cold = _render_orientation(_orientation_payload(captured_at=None))
    assert 'data-region="reentry-card"' not in cold
    assert 'data-testid="memory-review-drawer"' not in cold

    # Workspace shell: dismissal routes through the host back to the anchor.
    workspace = _render_workspace()
    drawer = _drawer(workspace)
    close = re.search(r'<button[^>]*data-testid="memory-review-close"[^>]*>', drawer)
    assert close, "the drawer must offer an explicit dismiss-to-anchor control"
    assert 'data-intent="overlay.dismiss"' in close.group(0)
    assert "overlayHost.dismiss()" in close.group(0)

    # The controller never navigates: dismissal is host bookkeeping only.
    script = _drawer_script(workspace)
    for forbidden in (
        "location.href",
        "location.assign",
        "location.reload",
        "history.pushState",
        "window.open",
        "form.submit",
    ):
        assert forbidden not in script, f"drawer must not call {forbidden}"
    # One Esc owner: the host, not the drawer.
    assert "Escape" not in script


def test_unresolved_link_stays_on_open_loops_when_memory_queue_empty() -> None:
    html = _render_orientation(_orientation_payload(pending_candidates=0))
    card = _reentry_card(html)
    inspect = re.search(r'<a[^>]*data-testid="reentry-inspect"[^>]*>', card)

    assert inspect, "the re-entry card must keep its inspect affordance"
    inspect_link = inspect.group(0)
    assert 'data-intent="open_loops.inspect"' in inspect_link
    assert 'href="#workspace-orientation-open-loops"' in inspect_link
    assert "overlayHost.mount('memory')" not in inspect_link
    assert "return false" not in inspect_link
    assert "1 open loops" in card
    assert "1 staged" in card
    assert "0 memory candidates" in card


def test_unresolved_link_opens_memory_drawer_when_candidates_pending() -> None:
    html = _render_orientation(_orientation_payload(pending_candidates=2))
    card = _reentry_card(html)
    inspect = re.search(r'<a[^>]*data-testid="reentry-inspect"[^>]*>', card)

    assert inspect, "the re-entry card must keep its inspect affordance"
    inspect_link = inspect.group(0)
    assert 'data-intent="memory.open"' in inspect_link
    assert 'href="#workspace-orientation-open-loops"' in inspect_link
    assert "overlayHost.mount('memory')" in inspect_link
    assert "return false" in inspect_link
    assert "2 memory candidates" in card
