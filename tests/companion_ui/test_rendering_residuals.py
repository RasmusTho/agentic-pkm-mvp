"""Companion-UI rendering residuals from the 2026-06-18 terminal review-thread audit.

Governing issue: #2195 (tracking audit #2148).

Two residuals pinned here, both asserted on the production render path
(``RealNoteWorkspaceDevPage.load`` -> ``render_fields`` -> ``render_index_html``
for the commitment surface, and ``_is_remote_page_origin`` for the page-origin
classifier):

AC1 — id-only commitments must render instead of being dropped. A commitment
that carries neither ``summary`` nor ``target_ref`` is still a real active
commitment the durable read returned; dropping it at normalization
(``real_note_workspace_dev_page._commitment_item_from_raw``) can collapse a
non-empty surface into a false ``empty`` "nothing here" state.

AC2 — a bracketed IPv6 loopback host (``[::1]`` / ``[::1]:8111``) must be
classified as local, not remote (``serve_dev_page._is_remote_page_origin``).
The production fix landed via sibling #2162; this asserts the behavior on the
production call path so the residual stays closed.
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import (
    _is_remote_page_origin,
    render_index_html,
)
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)

_NOTE_PATH = "Notes/commitments.md"


class _CommitmentsClient:
    """Workspace client whose ``runtime.commitments`` mirrors the slice-2
    ``CommitmentSurfaceState`` shape — the same payload contract the live
    workspace API serves."""

    def __init__(self, commitments: dict[str, Any] | None) -> None:
        self._commitments = commitments

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        assert url == "/api/companion/workspace"
        assert params == {"note_path": _NOTE_PATH}
        runtime: dict[str, Any] = {}
        if self._commitments is not None:
            runtime["commitments"] = self._commitments
        return {
            "artifact": {
                "artifact_id": "art-2195",
                "note_path": _NOTE_PATH,
                "title": "Commitments Note",
                "body": "# Commitments Note",
                "content_hash": "hash-residuals",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": runtime,
            "suggestions": {},
        }


def _render(commitments: dict[str, Any] | None) -> str:
    """Drive the full production render path the dev page uses in the browser."""
    page = RealNoteWorkspaceDevPage(_CommitmentsClient(commitments))  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path=_NOTE_PATH))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=_NOTE_PATH,
        fields=fields,
    )


def _commitments_section(html: str) -> str:
    """Isolate the commitments surface so assertions are scoped to it."""
    start = html.find('data-testid="commitments-mode"')
    assert start != -1, "commitments-mode section must be present in the render"
    open_tag = html.rfind("<section", 0, start)
    assert open_tag != -1, "commitments-mode must be a <section>"
    depth = 0
    for token in re.finditer(r"<section\b|</section>", html[open_tag:]):
        depth += 1 if token.group(0).startswith("<section") else -1
        if depth == 0:
            return html[open_tag : open_tag + token.end()]
    raise AssertionError("unbalanced commitments-mode <section>")


# --------------------------------------------------------------------------- #
# AC1 — id-only commitments render instead of being dropped.
# --------------------------------------------------------------------------- #


def test_id_only_commitment_renders_instead_of_false_empty() -> None:
    """A surface whose only active commitment carries neither ``summary`` nor
    ``target_ref`` must render that commitment (populated), not collapse into a
    false ``empty`` "No active commitments" state."""
    surface = {
        "next": [
            {
                "commitment_id": "c-id-only",
                "kind": "next_action",
                "state": "next",
                # No summary, no target_ref — id-only.
            }
        ],
        "waiting": [],
        "review_return": [],
        "read_only": True,
        "degraded": False,
        "as_of": "2026-06-18T20:00:00+00:00",
    }

    html = _render(surface)
    section = _commitments_section(html)

    # The surface must NOT collapse to the confident-empty state.
    assert 'data-commitment-state="empty"' not in section
    assert "No active commitments." not in section
    assert 'data-commitment-state="populated"' in section

    # The id-only commitment renders as a keyed read-only row.
    assert 'data-testid="commitment-item"' in section
    assert 'data-commitment-id="c-id-only"' in section
    assert 'data-commitment-family="next-action"' in section
    assert 'data-affordance-status="read-only"' in section

    # The keyed row is legible (its identifier is surfaced) rather than blank.
    assert 'data-testid="commitment-summary-fallback"' in section
    assert "c-id-only" in section

    # Still strictly read-only — no mutation affordance leaks in.
    lowered = section.lower()
    for token in ("<button", "<input", "<form", "data-intent"):
        assert token not in lowered, (
            f"id-only commitment row must stay read-only (found {token!r})"
        )


def test_id_only_commitment_does_not_mask_other_commitments() -> None:
    """A mix of an id-only commitment and a fully-populated one renders both;
    the id-only one neither vanishes nor displaces the populated row."""
    surface = {
        "next": [
            {"commitment_id": "c-bare", "kind": "next_action", "state": "next"},
            {
                "commitment_id": "c-full",
                "kind": "next_action",
                "state": "next",
                "summary": "Reply to Alice about the offer",
                "target_ref": "projects/hiring.md",
            },
        ],
        "waiting": [],
        "review_return": [],
        "read_only": True,
        "degraded": False,
    }

    section = _commitments_section(_render(surface))

    assert 'data-commitment-state="populated"' in section
    assert 'data-commitment-id="c-bare"' in section
    assert 'data-commitment-id="c-full"' in section
    assert "Reply to Alice about the offer" in section


def test_genuinely_empty_surface_still_reads_empty() -> None:
    """The fix must not regress the legitimate confident-empty state: a healthy
    read with no commitments at all still renders ``empty``."""
    surface = {
        "next": [],
        "waiting": [],
        "review_return": [],
        "read_only": True,
        "degraded": False,
        "as_of": "2026-06-18T20:00:00+00:00",
    }

    section = _commitments_section(_render(surface))
    assert 'data-commitment-state="empty"' in section
    assert "No active commitments." in section


# --------------------------------------------------------------------------- #
# AC2 — bracketed IPv6 loopback hosts are classified as local.
# --------------------------------------------------------------------------- #


def test_bracketed_ipv6_loopback_is_local() -> None:
    """``_is_remote_page_origin`` must treat a bracketed IPv6 loopback host as
    local, including when it carries a port — the production page-origin
    classifier the dev server consults."""
    assert _is_remote_page_origin("[::1]") is False
    assert _is_remote_page_origin("[::1]:8111") is False

    # Sibling local forms remain local (no regression).
    assert _is_remote_page_origin("127.0.0.1") is False
    assert _is_remote_page_origin("127.0.0.1:8111") is False
    assert _is_remote_page_origin("localhost") is False
    assert _is_remote_page_origin("localhost:8111") is False
    assert _is_remote_page_origin("") is False

    # Genuinely remote hosts (incl. a non-loopback bracketed IPv6) stay remote.
    assert _is_remote_page_origin("example.com") is True
    assert _is_remote_page_origin("example.com:443") is True
    assert _is_remote_page_origin("[2001:db8::1]:443") is True
