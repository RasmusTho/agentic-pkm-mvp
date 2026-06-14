from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _orientation_payload() -> dict[str, Any]:
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
            "captured_at": _iso(_AS_OF - timedelta(hours=5)),
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

    m = re.search(r"function entryDismiss\(control\) \{(.*?)\n\s*\}", html, re.S)
    assert m, "entry.dismiss handler must render"
    body = m.group(1)
    assert "card.remove()" in body
    assert "document.body.dataset.entryState = 'shell_active'" in body
    assert "data-entry-state', 'shell_active'" in body
