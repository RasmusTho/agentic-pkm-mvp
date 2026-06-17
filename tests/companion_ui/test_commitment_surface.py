"""Read-only commitment surface render in the Companion workspace shell.

Governing issue: #2075 (parent #1960) — Commitment Surfacing slice 3 (FINAL).
Spec: docs/COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI.md
Contract: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md
  (Next Action and Review Cycle are distinct semantic kinds; the layer is
  read/proposal-only in this surface — no mutation / state transition affordance).

These tests pin the human-facing render that consumes the slice-2 read-only
commitment field (``WorkspaceStateResponse.runtime.commitments`` —
``CommitmentSurfaceState`` with ``next`` / ``waiting`` / ``review_return``
buckets and ``read_only`` / ``degraded`` / ``degraded_reason`` markers). The
render flows through the same path as the sibling read-only surfaces
(``runtime.reorient`` / ``runtime.resurface``): the dev page parses the
workspace payload and ``render_index_html`` produces the HTML.

1. Active commitments render read-only — no mutation affordance.
2. Next-action (next/waiting) is visually distinguished from review-cycle
   (review_return) in the rendered output, not merely in the data.
3. When the field is absent or the API reports a degraded read, the surface
   degrades to not-shown / unavailable rather than a confident empty surface
   or a crash.
"""

from __future__ import annotations

import re
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

_NOTE_PATH = "Notes/commitments.md"


def _commitments_section(html: str) -> str:
    """Isolate the rendered commitments section so read-only assertions about
    "no mutation affordance" are scoped to this surface, not the whole page
    (the page legitimately contains buttons elsewhere).

    The populated surface contains nested ``<section>`` family groups, so this
    walks the tags to find the matching outer ``</section>`` rather than the
    first nested one.
    """
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


class _CommitmentsClient:
    """Returns a workspace payload whose ``runtime.commitments`` field mirrors
    the slice-2 ``CommitmentSurfaceState`` shape."""

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
                "artifact_id": "art-2075",
                "note_path": _NOTE_PATH,
                "title": "Commitments Note",
                "body": "# Commitments Note",
                "content_hash": "hash-commitments",
            },
            "canvas": {"session_state": "idle", "can_edit_body": False},
            "panel": {"state": "idle", "proposal_count": 0},
            "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
            "runtime": runtime,
            "suggestions": {},
        }


def _render(commitments: dict[str, Any] | None) -> str:
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


def _active_surface() -> dict[str, Any]:
    """A populated, non-degraded commitment surface spanning all three buckets."""
    return {
        "next": [
            {
                "commitment_id": "c-next",
                "kind": "next_action",
                "state": "next",
                "summary": "Reply to Alice about the offer",
                "target_ref": "projects/hiring.md",
                "source_goal": "Close the hire",
            }
        ],
        "waiting": [
            {
                "commitment_id": "c-waiting",
                "kind": "waiting",
                "state": "waiting",
                "summary": "Vendor to send revised quote",
                "target_ref": "projects/vendor.md",
                "source_goal": None,
                "waiting_on": "Vendor (Acme) reply",
                "waiting_since": "2026-06-10",
            }
        ],
        "review_return": [
            {
                "commitment_id": "c-review",
                "kind": "review_return",
                "state": "open",
                "summary": "Re-read the architecture RFC before sign-off",
                "target_ref": "docs/rfc.md",
                "source_goal": None,
                "review_cadence": "weekly",
                "last_reviewed_relative": "3d ago",
            }
        ],
        "read_only": True,
        "authority_role": "derived",
        "source": "vault.commitment_artefacts",
        "degraded": False,
        "degraded_reason": None,
        "as_of": "2026-06-17T20:00:00+00:00",
    }


def test_commitments_render_read_only() -> None:
    """AC1: active commitments render from the workspace-state API field, with an
    explicit read-only marker and no mutation affordance."""
    html = _render(_active_surface())

    # The surface is present and rendered from the runtime field.
    assert 'data-testid="commitments-mode"' in html
    assert 'data-capability="commitments"' in html

    section = _commitments_section(html)

    # Explicit read-only marker (mirrors the sibling read-only surfaces).
    assert 'data-affordance-status="read-only"' in section
    assert 'data-read-only="true"' in section

    # The actual commitment content is rendered (read-only projection).
    assert "Reply to Alice about the offer" in section
    assert "Vendor to send revised quote" in section
    assert "Re-read the architecture RFC before sign-off" in section
    assert 'data-testid="commitment-item"' in section

    # Read-only: NO mutation / state-transition affordance whatsoever in this
    # surface. No buttons, no form controls, no transition intents.
    lowered = section.lower()
    for token in ("<button", "<input", "<form", "data-intent", "aria-disabled"):
        assert token not in lowered, (
            f"commitment surface must be strictly read-only (found {token!r})"
        )
    for verb in ("complete", "transition", "close commitment", "mark done", "dismiss"):
        assert verb not in lowered, (
            f"commitment surface must expose no mutation affordance (found {verb!r})"
        )


def test_next_action_distinguished_from_review_cycle() -> None:
    """AC2: next-action (next/waiting) and review-cycle (review_return) are
    visually distinguished in the rendered surface — distinct grouping + label +
    marker observable in the HTML, not only in the data."""
    html = _render(_active_surface())
    section = _commitments_section(html)

    # Two distinct family groups exist as separate regions in the render.
    assert 'data-commitment-family="next-action"' in section
    assert 'data-commitment-family="review-cycle"' in section
    assert 'data-testid="commitment-group-next-action"' in section
    assert 'data-testid="commitment-group-review-cycle"' in section

    # Each group carries an observable human label distinguishing the families.
    assert "Next" in section
    assert "Review" in section

    # The distinction is per-item too: a next_action item and a review_return
    # item carry different family markers in the rendered output.
    next_item = re.search(
        r'<[^>]*data-testid="commitment-item"[^>]*data-commitment-id="c-next"[^>]*>',
        section,
    )
    review_item = re.search(
        r'<[^>]*data-testid="commitment-item"[^>]*data-commitment-id="c-review"[^>]*>',
        section,
    )
    assert next_item is not None, "next_action item must render with its id marker"
    assert review_item is not None, "review_return item must render with its id marker"
    assert 'data-commitment-family="next-action"' in next_item.group(0)
    assert 'data-commitment-family="review-cycle"' in review_item.group(0)

    # The next-action group must appear before the review-cycle group: "what is
    # mine to do next" precedes "what returns to me for review".
    assert section.index(
        'data-testid="commitment-group-next-action"'
    ) < section.index('data-testid="commitment-group-review-cycle"')


def test_degraded_or_absent_commitments_render_safely() -> None:
    """AC3: when the field is absent or the API reports a degraded read, the UI
    degrades to not-shown / unavailable rather than a confident empty surface or
    a crash."""

    # (a) Degraded read: the durable source failed. The surface must say so —
    # unavailable, with the reason — never "you have zero commitments".
    degraded_html = _render(
        {
            "next": [],
            "waiting": [],
            "review_return": [],
            "read_only": True,
            "authority_role": "derived",
            "source": "vault.commitment_artefacts",
            "degraded": True,
            "degraded_reason": "durable_read_failed",
        }
    )
    degraded_section = _commitments_section(degraded_html)
    assert 'data-commitment-state="degraded"' in degraded_section
    assert 'data-affordance-status="unavailable"' in degraded_section
    assert "durable_read_failed" in degraded_section
    assert "unavailable" in degraded_section.lower()
    # Must NOT claim a confident empty surface when degraded.
    assert "no commitments" not in degraded_section.lower()
    assert "you're all caught up" not in degraded_section.lower()

    # (b) Absent field: an older payload with no ``commitments`` at all. The
    # surface must degrade to not-shown, not crash and not imply zero commitments.
    absent_html = _render(None)
    absent_section = _commitments_section(absent_html)
    assert 'data-commitment-state="not-shown"' in absent_section
    assert 'data-affordance-status="unavailable"' in absent_section
    assert "no commitments" not in absent_section.lower()

    # (c) Genuinely empty but healthy read: this is the ONE case where a
    # confident "nothing here" is legitimate, and it must be distinct from the
    # degraded/absent states above.
    empty_html = _render(
        {
            "next": [],
            "waiting": [],
            "review_return": [],
            "read_only": True,
            "authority_role": "derived",
            "source": "vault.commitment_artefacts",
            "degraded": False,
            "degraded_reason": None,
        }
    )
    empty_section = _commitments_section(empty_html)
    assert 'data-commitment-state="empty"' in empty_section
    assert 'data-affordance-status="read-only"' in empty_section
    # The healthy-empty state is NOT the degraded/not-shown state.
    assert 'data-commitment-state="degraded"' not in empty_section
    assert 'data-commitment-state="not-shown"' not in empty_section


def test_commitment_visual_fidelity_markers() -> None:
    """Full-fidelity render: per-item kind marker + kind tag, the within-Next
    waiting-vs-next_action distinction, server-provided provenance lines
    (depends-on / cadence), group count chips, and the freshness footer.

    These pin the design's three redundant family signals (grouping + label +
    styling) plus the provenance lines — all read-only, all driven by
    server-declared data (no fabricated values)."""
    html = _render(_active_surface())
    section = _commitments_section(html)

    # Per-item kind marker drives the waiting-vs-next_action styling distinction.
    next_item = re.search(
        r'<[^>]*data-testid="commitment-item"[^>]*data-commitment-id="c-next"[^>]*>',
        section,
    )
    waiting_item = re.search(
        r'<[^>]*data-testid="commitment-item"[^>]*data-commitment-id="c-waiting"[^>]*>',
        section,
    )
    assert next_item is not None and waiting_item is not None
    assert 'data-commitment-kind="next_action"' in next_item.group(0)
    assert 'data-commitment-kind="waiting"' in waiting_item.group(0)
    # Styling signal: distinct kind classes (warm next vs dashed-amber waiting).
    assert "k-next" in next_item.group(0)
    assert "k-wait" in waiting_item.group(0)

    # Explicit-label signal: a kind tag echoing the API kind verbatim.
    assert 'data-testid="commitment-kind-tag"' in section
    assert "next_action" in section and "review_return" in section

    # Server-provided provenance lines (rendered only because the data is present).
    assert "depends on:" in section
    assert "Vendor (Acme) reply" in section
    assert "cadence:" in section
    assert "last 3d ago" in section

    # Group count chips and the freshness footer.
    assert 'data-testid="commitment-group-count-next-action"' in section
    assert 'data-testid="commitment-group-count-review-cycle"' in section
    assert 'data-testid="commitments-as-of"' in section
    assert "commitments ok" in section

    # Still strictly read-only — the richer render adds no mutation affordance.
    lowered = section.lower()
    for token in ("<button", "<input", "<form", "data-intent", "aria-disabled"):
        assert token not in lowered


def test_empty_surface_is_affirmative_not_degraded() -> None:
    """The healthy-empty state is an affirmative '0 active' with the green dot and
    an 'commitments ok' footer — confidently distinct from the amber degraded
    state, and it must not borrow degraded/absent vocabulary."""
    empty_html = _render(
        {
            "next": [],
            "waiting": [],
            "review_return": [],
            "read_only": True,
            "authority_role": "derived",
            "source": "vault.commitment_artefacts",
            "degraded": False,
            "degraded_reason": None,
            "as_of": "2026-06-17T20:00:00+00:00",
        }
    )
    section = _commitments_section(empty_html)
    assert 'data-commitment-state="empty"' in section
    assert "commitments-empty-dot" in section
    assert "0 active" in section
    assert "commitments ok" in section
    # Never the unavailable/degraded vocabulary.
    assert "unavailable" not in section.lower()
