from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _orientation_payload(*, gap: timedelta = timedelta(hours=5)) -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-orientation-1",
            "freshness": "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": [],
        },
        "leave_point": {
            "status": "present",
            "artifact_ref": {
                "artifact_uuid": "art-resume",
                "logical_ref": "Notes/resume.md",
                "title": "Resume plan",
            },
            "captured_at": _iso(_AS_OF - gap),
            "last_session_id": None,
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        },
        "open_loops": [{"label": "Review the next step"}],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "gov", "label": "governance"},
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


def test_start_fresh_dismisses_orienting_card_and_opens_shell() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
    )

    assert 'data-entry-state="orienting"' in html
    assert 'data-testid="reentry-card"' in html
    assert 'data-intent="entry.dismiss"' in html
    assert 'onclick="entryDismiss(this)"' in html

    m = re.search(r"function entryDismiss\(control\) \{(.*?)\n  \}\n  </script>", html, re.S)
    assert m, "entry.dismiss handler must render"
    body = m.group(1)
    assert "card.remove()" in body
    assert "[data-region=delta-strip], [data-region=whisper-column]" in body
    assert "siblingCues[i].remove()" in body
    assert "document.body.dataset.entryState = 'shell_active'" in body
    assert "data-entry-state', 'shell_active'" in body


def test_gap_over_seven_days_resolves_cold_start() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(gap=timedelta(days=8)),
    )

    assert 'data-entry-state="cold_start"' in html
    assert 'data-region="cold-start-threshold"' in html
    assert 'data-region="reentry-card"' not in html
    assert 'data-reentry-shape="long_mist"' not in html


def _cold_orientation_payload() -> dict[str, Any]:
    """A cold_start payload — first contact, no leave point to resume."""
    payload = _orientation_payload()
    payload["leave_point"] = {"status": "absent"}
    payload["open_loops"] = []
    return payload


def _cold_start_action_row(html: str) -> str:
    m = re.search(
        r'<p data-region="cold-start-verbs"[^>]*>(.*?)</p>',
        html,
        re.S,
    )
    assert m, "cold_start must render the entry-screen action row"
    return m.group(0)


# ---------------------------------------------------------------------------
# D2 (#2448): the cold_start / no_vault entry-screen action row is a set of
# ranked, on-palette affordances — one primary, the rest secondary — not inline
# browser-blue underlined links; only the affordance treatment changed there.
# #2562 (Ask 2.2): the capture verb ("Jot something down") was dropped from the
# verb row so capture is a single affordance (the inline capture line). The
# verb row now carries the two navigation verbs: Find a note (primary) and See
# the map (secondary).
# ---------------------------------------------------------------------------


def test_entry_actions_ranked() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_cold_orientation_payload(),
    )
    assert 'data-entry-state="cold_start"' in html

    row = _cold_start_action_row(html)

    # Exactly one primary affordance and one secondary affordance — ranked,
    # not equal inline links. The capture verb is no longer in this row (#2562).
    primary = re.findall(r'class="[^"]*\bbtn--primary\b[^"]*"', row)
    secondary = re.findall(r'class="[^"]*\bbtn--secondary\b[^"]*"', row)
    assert len(primary) == 1, f"action row must carry exactly one primary affordance: {row}"
    assert len(secondary) == 1, f"action row must carry exactly one secondary affordance: {row}"

    # The affordances are on-palette buttons, not inline browser-blue links.
    assert "<a href" not in row and "<a data-intent" not in row, (
        f"entry-screen actions must be ranked buttons, not <a href> links: {row}"
    )

    # The verb row carries the two navigation verbs; the capture verb is gone.
    assert "Find a note" in row
    assert "See the map" in row
    assert "Jot something down" not in row

    # The navigation intents are preserved; capture.open is no longer a verb
    # (it moved to the single inline capture line — #2562).
    assert 'data-intent="vault.open"' in row
    assert 'data-intent="map.open"' in row
    assert 'data-intent="capture.open"' not in row
