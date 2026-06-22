"""Tests for Resurface mode rendering in the Companion workspace shell (#1142)."""

from __future__ import annotations

from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)


class _FakeClient:
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/resurface.md"}
        return {
            "artifact": {
                "artifact_id": "art-1142",
                "note_path": "Notes/resurface.md",
                "title": "Resurface Note",
                "body": "# Resurface Note",
                "content_hash": "hash-resurface",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {
                "resurface": {
                    "candidates": [
                        {
                            "candidate_id": "resurface-1",
                            "label": "Queued runtime work remains unresolved",
                            "why_now": (
                                "Derived relevance changed because the worker queue "
                                "has unresolved pending items."
                            ),
                            "relation_to_active_artifact": (
                                "Evaluated while Notes/resurface.md is active."
                            ),
                            "source_link": "status.worker_queue",
                            "signal_labels": ["worker_queue_pending=2"],
                        }
                    ]
                }
            },
            "suggestions": {},
        }


def _render_resurface() -> str:
    page = RealNoteWorkspaceDevPage(_FakeClient())  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/resurface.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/resurface.md",
        fields=fields,
    )


def test_why_now_explanation() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-candidate"' in html
    assert 'data-testid="resurface-candidate-label"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-runtime-backed="true"' in html
    assert 'data-testid="resurface-why-now"' in html
    assert "Derived relevance changed" in html
    assert "should act now" not in html.lower()
    assert "urgent" not in html.lower()


def test_dismiss_snooze_pin() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-action-dismiss"' in html
    assert 'data-testid="resurface-action-snooze"' in html
    assert 'data-testid="resurface-action-pin"' in html
    assert 'data-intent="resurface.dismiss"' in html
    assert 'data-intent="resurface.snooze"' in html
    assert 'data-intent="resurface.pin"' in html


def test_resurface_actions_marked_read_only_or_unavailable_without_persistence() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-affordance-status="read-only"' in html
    assert 'data-testid="resurface-action-dismiss"' in html
    assert 'data-testid="resurface-action-snooze"' in html
    assert 'data-testid="resurface-action-pin"' in html
    assert html.count('data-affordance-status="unavailable"') >= 3
    assert html.count('data-runtime-backed="false"') >= 3
    assert html.count('data-persistence-backed="false"') >= 3
    assert "Dismiss unavailable" in html
    assert "Snooze unavailable" in html
    assert "Pin unavailable" in html
    assert "no persistence" in html


def test_relation_to_active_artifact() -> None:
    html = _render_resurface()

    assert 'data-testid="resurface-relation"' in html
    assert "Evaluated while Notes/resurface.md is active." in html
    assert 'data-testid="resurface-source-link"' in html
    assert "status.worker_queue" in html


def test_workspace_resurface_source_link_uses_logical_identifier(
    monkeypatch,
    tmp_path,
) -> None:
    from app.api.routes import companion
    from app.resurfacing.runtime import (
        ResurfacingCandidate,
        ResurfacingEvaluation,
        ResurfacingSignal,
        ResurfacingWhyNow,
    )

    note = tmp_path / "Notes" / "resurface.md"
    note.parent.mkdir()
    note.write_text("---\nuuid: note-1142\n---\n# Resurface Note\n", encoding="utf-8")

    monkeypatch.setattr(companion, "_active_companion_vault_root", lambda **_: tmp_path)
    monkeypatch.setattr(
        companion,
        "evaluate_resurfacing_candidates",
        lambda *, signals=None: ResurfacingEvaluation(
            generated_at="2026-05-21T00:00:00Z",
            status_summary="resurfacing_candidates=1",
            candidates=[
                ResurfacingCandidate(
                    candidate_id="resurface-worker-queue",
                    label="Queued runtime work remains unresolved",
                    why_now=ResurfacingWhyNow(
                        explanation="Worker queue has unresolved pending items.",
                        signals=[
                            ResurfacingSignal(
                                name="worker_queue_pending",
                                value=2,
                                source="postgresql://user:secret@example/app",
                            )
                        ],
                    ),
                )
            ],
        ),
    )

    response = companion.read_companion_workspace(note_path="Notes/resurface.md")

    candidate = response.runtime.resurface["candidates"][0]
    assert candidate["source_link"] == "status.worker_queue"
    assert "secret" not in str(candidate)


class _EmptyResurfaceClient:
    def __init__(self, *, degraded: bool = False) -> None:
        self.degraded = degraded

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": "Notes/resurface.md"}
        return {
            "artifact": {
                "artifact_id": "art-1186",
                "note_path": "Notes/resurface.md",
                "title": "Resurface Note",
                "body": "# Resurface Note",
                "content_hash": "hash-resurface-empty",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {
                "canvas_enabled": True,
                "writeguard_status": "ok",
                "degraded": self.degraded,
            },
            "runtime": {"resurface": {"candidates": []}},
            "suggestions": {},
        }


def _render_empty_resurface(*, degraded: bool = False) -> str:
    page = RealNoteWorkspaceDevPage(_EmptyResurfaceClient(degraded=degraded))  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/resurface.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/resurface.md",
        fields=fields,
    )


def test_resurface_empty_state_is_visible() -> None:
    html = _render_empty_resurface()

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-empty-state"' in html
    assert 'data-affordance-status="read-only"' in html
    assert "No Resurface candidates are available" in html
    assert "Nothing needs action" in html


def test_resurface_degraded_state_is_visible() -> None:
    html = _render_empty_resurface(degraded=True)

    assert 'data-testid="resurface-mode"' in html
    assert 'data-testid="resurface-degraded-state"' in html
    assert 'data-affordance-status="unavailable"' in html
    assert "runtime reported degraded guard state" in html


def _resurface_section(html: str) -> str:
    """Isolate the resurface-mode <section> so assertions about the surface are
    scoped to it, not the whole page (other surfaces legitimately use the same
    affordance attribute values)."""
    start = html.find('data-testid="resurface-mode"')
    assert start != -1, "resurface-mode must be present"
    open_tag = html.rfind("<section", 0, start)
    assert open_tag != -1, "resurface-mode must be a <section>"
    end = html.find("</section>", start)
    assert end != -1, "resurface-mode <section> must close"
    return html[open_tag : end + len("</section>")]


def test_resurface_css_hook_present_on_populated_rail() -> None:
    """The visual treatment is keyed off these classes/affordance hooks; pin them
    so a regression that drops the styling class is caught (#2: the surface
    previously shipped with zero CSS)."""
    section = _resurface_section(_render_resurface())
    assert 'class="resurface-mode"' in section
    assert 'data-affordance-status="read-only"' in section
    # The why-now relation marker and the source pointer are styled via these classes.
    assert 'class="resurface-why"' in section
    assert 'class="resurface-source"' in section


def test_resurface_empty_and_degraded_are_distinguishable() -> None:
    """Empty (healthy / green) and degraded (amber / "can't say") must never
    collapse into one visual. The CSS keys the two treatments off distinct
    testids plus the section affordance status, so pin that they stay distinct."""
    empty = _resurface_section(_render_empty_resurface())
    degraded = _resurface_section(_render_empty_resurface(degraded=True))

    assert 'data-testid="resurface-empty-state"' in empty
    assert 'data-testid="resurface-degraded-state"' not in empty
    assert 'data-affordance-status="read-only"' in empty
    # Healthy-empty must NOT carry the unavailable hook the degraded CSS paints amber.
    assert 'data-affordance-status="unavailable"' not in empty

    assert 'data-testid="resurface-degraded-state"' in degraded
    assert 'data-testid="resurface-empty-state"' not in degraded
    assert 'data-affordance-status="unavailable"' in degraded


def test_resurface_visual_pass_enables_no_action() -> None:
    """The CSS pass must not enable any disabled action. Every resurface intent
    button stays disabled (the hover-active CSS is gated behind
    :not([disabled])), and nothing claims write-back persistence."""
    section = _resurface_section(_render_resurface())
    for intent in ("dismiss", "snooze", "pin"):
        assert f'data-testid="resurface-action-{intent}"' in section
    # All three action buttons are unavailable + aria-disabled; none enabled.
    assert section.count('data-affordance-status="unavailable"') >= 3
    assert 'aria-disabled="true"' in section


# --- "A scarce glance, not a feed" handoff deltas (pinned / withheld / scarce) -


class _ResurfacePayloadClient:
    """Renders an arbitrary resurface payload through the real pipeline so the
    pinned / scarce-count / withheld branches can be exercised end to end."""

    def __init__(self, resurface: dict[str, Any]) -> None:
        self.resurface = resurface

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        return {
            "artifact": {
                "artifact_id": "art-scarce",
                "note_path": "Notes/resurface.md",
                "title": "Resurface Note",
                "body": "# Resurface Note",
                "content_hash": "hash-resurface-scarce",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": {"resurface": self.resurface},
            "suggestions": {},
        }


def _candidate(candidate_id: str, label: str, *, pinned: bool = False) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "label": label,
        "why_now": "Derived relevance changed for this artifact.",
        "relation_to_active_artifact": "Evaluated while Notes/resurface.md is active.",
        "source_link": f"status.{candidate_id}",
        "signal_labels": [f"{candidate_id}=1"],
        "pinned": pinned,
    }


def _render_resurface_payload(resurface: dict[str, Any]) -> str:
    page = RealNoteWorkspaceDevPage(_ResurfacePayloadClient(resurface))  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/resurface.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/resurface.md",
        fields=fields,
    )


def test_resurface_populated_title_word_is_ambient() -> None:
    """A calm word ("ambient") sits where a count would go — never a number."""
    section = _resurface_section(_render_resurface())
    assert ">ambient<" in section
    assert "low-pressure" not in section


def test_resurface_pinned_sorts_first_and_is_marked() -> None:
    """Pinned cards sort to the top and carry the visual hook; the rest keep
    server order. Pin remains a read-only sort signal — no action is enabled."""
    section = _resurface_section(
        _render_resurface_payload(
            {
                "candidates": [
                    _candidate("alpha", "Alpha unpinned"),
                    _candidate("beta", "Beta pinned", pinned=True),
                ]
            }
        )
    )
    assert 'data-pinned="true"' in section
    # The pinned card (beta) renders before the unpinned one (alpha).
    assert section.find("Beta pinned") < section.find("Alpha unpinned")
    # No action is enabled by pinning.
    assert 'aria-disabled="true"' in section


def test_resurface_unpinned_set_has_no_pinned_hook() -> None:
    section = _resurface_section(
        _render_resurface_payload({"candidates": [_candidate("alpha", "Alpha")]})
    )
    assert 'data-pinned="true"' not in section


def test_resurface_scarce_cap_holds_back_without_a_count() -> None:
    """The set caps to the server-declared scarce count, and the overflow is
    signalled by the withheld line — with no number or badge anywhere."""
    section = _resurface_section(
        _render_resurface_payload(
            {
                "candidates": [
                    _candidate("a", "Card A"),
                    _candidate("b", "Card B"),
                    _candidate("c", "Card C"),
                ],
                "scarce_count": 2,
            }
        )
    )
    # Capped to 2 — the third card is held back, not paginated.
    assert section.count('data-testid="resurface-candidate"') == 2
    assert "Card C" not in section
    assert 'data-testid="resurface-withheld"' in section
    assert "held below the line" in section
    # No count/badge of any kind in the withheld signal.
    withheld_start = section.find('data-testid="resurface-withheld"')
    withheld = section[withheld_start : section.find("</div>", withheld_start)]
    assert not any(ch.isdigit() for ch in withheld)


def test_resurface_withheld_line_single_card_phrasing() -> None:
    """When the server says more was held but only one card surfaces, the line
    reads as a calm "nothing else rose to a glance today"."""
    section = _resurface_section(
        _render_resurface_payload(
            {"candidates": [_candidate("a", "Card A")], "more_held_back": True}
        )
    )
    assert 'data-testid="resurface-withheld"' in section
    assert "nothing else rose to a glance today" in section


def test_resurface_no_withheld_line_when_nothing_held() -> None:
    section = _resurface_section(
        _render_resurface_payload({"candidates": [_candidate("a", "Card A")]})
    )
    assert 'data-testid="resurface-withheld"' not in section


def test_resurface_empty_is_affirmative_and_settled() -> None:
    """Empty-healthy reads as intentional calm ("at rest", green dot, affirmative
    lead + sub-line), never a dashboard waiting to be filled."""
    section = _resurface_section(_render_empty_resurface())
    assert ">at rest<" in section
    assert "Nothing is asking for your attention." in section
    assert "quiet period, not an empty shelf" in section
    # No urgency vocabulary leaks into the settled state.
    assert "urgent" not in section.lower()
    assert 'data-persistence-backed="true"' not in section
