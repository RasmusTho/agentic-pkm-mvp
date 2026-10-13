from __future__ import annotations

from datetime import date
from html import escape
from http.server import HTTPServer
from pathlib import Path
import re
import threading
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

import httpx
import pytest

from app.briefing.compose import (
    BriefingNote,
    BriefingReadError,
    BriefingSection,
    CommitmentBriefingItem,
    MomentBriefingItem,
)
from app.briefing.surface import collect_day_start_briefing
from app.vault.manager import VaultContext
from companion_ui.workspace.day_start_card import render_day_start_card_html
from companion_ui.workspace.serve_dev_page import make_handler


TODAY = date(2026, 7, 11)


def _context(tmp_path: Path) -> VaultContext:
    vault = tmp_path / "vault"
    vault.mkdir()
    return VaultContext(status="selected", active_vault_path=str(vault))


def _full_projection() -> dict[str, object]:
    return {
        "state": "full",
        "date": TODAY.isoformat(),
        "preview": "Reply to Anna",
        "degraded_sections": [],
        "read_only": True,
        "reason": None,
        "sections": [
            {
                "name": "commitments",
                "status": "available",
                "reason": None,
                "items": [
                    {
                        "summary": "Reply to Anna",
                        "artifact_path": "_system/commitments/c-1.md",
                        "target_ref": "Projects/Launch.md",
                    }
                ],
            },
            {
                "name": "moments",
                "status": "available",
                "reason": None,
                "items": [
                    {
                        "title": "Review launch decision",
                        "artifact_path": "_system/moments/m-1.md",
                        "surfaced_refs": [
                            {"ref": "Decisions/Launch.md", "why": "due today"}
                        ],
                    }
                ],
            },
        ],
    }


def test_day_start_card_renders_todays_briefing() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=True)

    assert 'data-testid="day-start-card"' in html
    assert 'data-briefing-state="full"' in html
    assert TODAY.isoformat() in html
    assert "Reply to Anna" in html
    assert 'data-testid="day-start-listen"' not in html
    assert 'data-testid="briefing-listen"' in html
    assert 'data-testid="day-start-read"' in html
    assert "Projects/Launch.md" in html
    assert "Decisions/Launch.md" in html


def test_day_start_card_has_no_text_input_affordances() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=True).lower()

    assert "<input" not in html
    assert "<textarea" not in html
    assert "contenteditable" not in html
    assert 'type="text"' not in html


def test_calendar_episode_provenance_is_preserved_read_only() -> None:
    projection = _full_projection()
    projection["sections"] = [{
        "name": "calendar_episodes", "status": "available", "items": [
            {"source": "calendar", "title": "Synthetic meeting", "provenance_ref": 'calendar:uid<&:etag"'},
            {"source": "episode", "title": "Synthetic episode", "provenance_ref": "ep-00000000-0000-4000-8000-000000000001"},
            {"source": "episode", "title": "Malformed reference", "provenance_ref": '<script>alert(1)</script>'},
        ],
    }]
    rendered = render_day_start_card_html(projection)
    assert 'data-read-only="true"' in rendered
    assert 'calendar:uid&lt;&amp;:etag&quot;' in rendered
    assert 'note_path=episodes%2Fep-00000000-0000-4000-8000-000000000001.md' in rendered
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in rendered
    assert '<script>alert(1)</script>' not in rendered
    assert 'source recorded in briefing' not in rendered
    assert '<input' not in rendered and '<textarea' not in rendered


@pytest.mark.parametrize(("episode_id", "supported"), [
    ("ep-abcdef12-3456-7890-abcd-ef1234567890", True),
    ("ep-ABCDEF12-3456-7890-ABCD-EF1234567890", True),
    ("ep-AbCdEf12-3456-7890-aBcD-Ef1234567890", True),
    ("ep-abcd", False),
    ("EP-ABCDEF12-3456-7890-ABCD-EF1234567890", False),
    ("ep-ABCDEF12-3456-7890-ABCD-EF1234567890\n", False),
    ("ep-ABCDEF12-3456-7890-ABCD-EF123456789G", False),
    ("ep-../../private<script>", False),
])
def test_episode_provenance_link_matches_canonical_schema(episode_id: str, supported: bool) -> None:
    from app.episodes.notes import render_episode_note
    from app.episodes.schema import validate_episode_note_fields
    fields = {"episode_id": episode_id, "scope": "synthetic", "title": "Synthetic episode",
              "time": {"start": "2026-10-13T08:00:00Z", "closed": False}, "segmentation": "proposed"}
    if supported:
        validate_episode_note_fields(fields)
        assert episode_id in render_episode_note(fields)  # Actual schema-valid producer preserves case.
    projection = _full_projection()
    projection["sections"] = [{"name": "calendar_episodes", "status": "available",
                               "items": [{"source": "episode", "title": "Synthetic", "provenance_ref": episode_id}]}]
    rendered = render_day_start_card_html(projection)
    href = "note_path=" + quote("episodes/" + episode_id + ".md", safe="")
    if supported:
        assert href in rendered
    else:
        assert '<a href=' not in rendered and href not in rendered
        assert escape(episode_id) in rendered
    assert 'data-read-only="true"' in rendered and '<input' not in rendered


@pytest.mark.parametrize("receipt", ["_system/receipts/decisions/decisions-202610.jsonl",
                                     "vault://_system/receipts/decisions/decisions-202610.jsonl",
                                     '_system/receipts/decisions/decisions-202610<&".jsonl'])
def test_receipt_ledger_provenance_is_escaped_inert_and_read_only(receipt: str) -> None:
    projection = _full_projection()
    projection["sections"] = [{"name": "decision_receipts", "status": "available",
                               "items": [{"key": "Synthetic review", "receipt_path": receipt}]}]
    rendered = render_day_start_card_html(projection)
    assert f'<span data-source-ref="true">{escape(receipt)}</span>' in rendered
    assert '<a href=' not in rendered and 'note_path=' not in rendered
    assert 'data-read-only="true"' in rendered
    assert '<input' not in rendered and '<textarea' not in rendered


@pytest.mark.parametrize(("target", "note_path"), [
    ("vault://Notes/Synthetic.md", "Notes/Synthetic.md"),
    ("vault://Notes/Plan%20%26%20review.md", "Notes/Plan & review.md"),
    ("vault://Notes/Åtgärd <draft>.md", "Notes/Åtgärd <draft>.md"),
    ("vault:///etc/passwd", None),
    ("vault://Notes/../private.md", None),
    ("vault://Notes/%2e%2e/private.md", None),
    ("vault://%2f%2fexternal.example/Note.md", None),
    ("vault://javascript:alert(1)", None),
    ("vault:Notes/Synthetic.md", None),
    ("javascript:alert(1)", None),
    ("data:text/html,<script>alert(1)</script>", None),
])
def test_canonical_vault_provenance_uses_existing_note_route(
    target: str, note_path: str | None,
) -> None:
    projection = _full_projection()
    projection["sections"][0]["items"][0]["target_ref"] = target
    rendered = render_day_start_card_html(projection)
    label = escape(target)
    if note_path is None:
        assert f'<span data-blocked-ref="true">{label}</span>' in rendered
    else:
        assert f'<a href="/?note_path={quote(note_path, safe="")}">{label}</a>' in rendered
        assert f'<span data-blocked-ref="true">{label}</span>' not in rendered
    assert 'data-read-only="true"' in rendered
    assert "<input" not in rendered and "<textarea" not in rendered
    assert "<script>alert(1)</script>" not in rendered


def test_missing_todays_briefing_shows_pending_state_not_blank(tmp_path: Path) -> None:
    with patch("app.briefing.surface.load_briefing", return_value=None):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    html = render_day_start_card_html(projection)

    assert projection["state"] == "pending"
    assert 'data-briefing-state="pending"' in html
    assert "isn't ready yet" in html
    assert "2026-07-10" not in html


def test_degraded_briefing_distinguished_from_pending_and_full(tmp_path: Path) -> None:
    note = BriefingNote(
        briefing_date=TODAY,
        degraded_sections=("decision_receipts",),
        sections={
            "commitments": BriefingSection(
                status="available",
                items=(
                    CommitmentBriefingItem(
                        commitment_id="c-1",
                        commitment_kind="next_action",
                        state="open",
                        summary="Reply to Anna",
                        artifact_path="_system/commitments/c-1.md",
                    ),
                ),
            ),
            "moments": BriefingSection(
                status="available",
                items=(
                    MomentBriefingItem(
                        moment_id="m-1",
                        title="Review launch",
                        need_basis="deadline",
                        urgency_band="today",
                        artifact_path="_system/moments/m-1.md",
                        surfaced_refs=({"ref": "Projects/Launch.md", "why": "today"},),
                    ),
                ),
            ),
            "decision_receipts": BriefingSection(
                status="degraded", items=(), reason="source_read_failed"
            ),
        },
    )
    with patch("app.briefing.surface.load_briefing", return_value=note):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    degraded = render_day_start_card_html(projection)
    pending = render_day_start_card_html({"state": "pending", "date": TODAY.isoformat()})
    full = render_day_start_card_html(_full_projection())

    assert 'data-briefing-state="degraded"' in degraded
    assert 'data-testid="day-start-degraded"' in degraded
    assert "decision receipts unavailable" in degraded
    assert 'data-testid="day-start-degraded"' not in pending
    assert 'data-testid="day-start-degraded"' not in full


def test_day_start_card_is_read_only() -> None:
    html = render_day_start_card_html(_full_projection(), tts_available=False)

    assert 'data-authority="read-only-projection"' in html
    assert 'data-read-only="true"' in html
    for forbidden in (
        "/transition",
        "/complete",
        "/delete",
        "noteEditor.save",
        "commitment.apply",
        "method=\"post\"",
    ):
        assert forbidden not in html


def test_unreadable_briefing_is_not_reported_as_pending(tmp_path: Path) -> None:
    with patch(
        "app.briefing.surface.load_briefing",
        side_effect=BriefingReadError("bad schema"),
    ):
        projection = collect_day_start_briefing(
            vault_context=_context(tmp_path), for_date=TODAY
        )
    html = render_day_start_card_html(projection)

    assert projection["state"] == "unreadable"
    assert 'data-briefing-state="unreadable"' in html
    assert "cannot be read" in html
    assert "isn't ready yet" not in html


class _DayStartServerClient:
    def __init__(self, *, post_result: object = None, post_error: Exception | None = None) -> None:
        self.post_result = post_result
        self.post_error = post_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        if self.post_error is not None:
            raise self.post_error
        return self.post_result if isinstance(self.post_result, dict) else {}

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url == "/api/companion/briefing/today":
            return {
                "state": "pending",
                "date": TODAY.isoformat(),
                "preview": "",
                "degraded_sections": [],
                "sections": [],
                "read_only": True,
                "reason": "not_yet_generated",
                "tts_available": False,
            }
        if url == "/api/companion/orientation":
            return {}
        if url == "/api/health":
            return {}
        if url == "/api/companion/vault-browser":
            return {"notes": [], "read_only": True}
        if url == "/api/companion/workspace":
            note_path = str(params.get("note_path") or "")
            return {
                "artifact": {
                    "note_path": note_path,
                    "title": "Launch",
                    "artifact_id": "launch",
                    "artifact_kind": "human_note",
                    "content_hash": "sha256-launch",
                    "body": "# Launch",
                    "identity_source": "frontmatter.uuid",
                    "identity_state": "resolved",
                    "companion_of": None,
                    "owns_identity": True,
                },
                "canvas": {"session_state": "idle"},
                "panel": {"state": "idle", "proposal_count": 0},
                "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
                "runtime": {},
                "suggestions": {},
            }
        return {}


def _serve(client: _DayStartServerClient) -> tuple[HTTPServer, str]:
    server = HTTPServer(
        ("127.0.0.1", 0),
        make_handler(client=client, api_base_url="http://127.0.0.1:18001"),  # type: ignore[arg-type]
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.mark.parametrize(
    ("post_result", "post_error"),
    [({}, None), (None, RuntimeError("generation failed"))],
)
def test_handler_falls_back_to_read_projection_when_first_contact_has_no_briefing(
    post_result: object, post_error: Exception | None
) -> None:
    client = _DayStartServerClient(post_result=post_result, post_error=post_error)
    server, base_url = _serve(client)
    try:
        response = httpx.get(base_url + "/", timeout=5)
    finally:
        server.shutdown()

    assert response.status_code == 200
    assert response.text.count('data-testid="day-start-card"') == 1
    assert 'data-briefing-state="pending"' in response.text
    assert ("/api/companion/briefing/today", {}) in client.get_calls


def test_vault_provenance_link_opens_workspace_note_route() -> None:
    projection = _full_projection()
    client = _DayStartServerClient(
        post_result={"briefing": {**projection, "tts_available": False}}
    )
    server, base_url = _serve(client)
    try:
        landing = httpx.get(base_url + "/", timeout=5)
        match = re.search(
            r'href="(/\?note_path=Projects%2FLaunch\.md)"', landing.text
        )
        assert match is not None
        opened = httpx.get(base_url + match.group(1), timeout=5)
    finally:
        server.shutdown()

    assert opened.status_code == 200
    assert "Unknown Companion UI route" not in opened.text
    assert (
        "/api/companion/workspace",
        {"note_path": "Projects/Launch.md"},
    ) in client.get_calls
