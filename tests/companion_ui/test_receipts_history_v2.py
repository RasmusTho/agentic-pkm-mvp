"""Receipts v2 — verb+object rows, vault-relative paths, run grouping,
integrity disclosure (#3363).

Companion to ``tests/companion_ui/test_receipts_history_surface.py``, which
pins the AC1-AC5 (#1794/#2246) shell/read-only/guard-posture contracts that
stay unchanged. These tests pin the additive Receipts v2 legibility layer on
top of ``companion_ui.workspace.receipts_history``:

- rows render grouped under run headers (label + relative time), most
  recent first within and across runs (audit §3.2, redesigns.html §2);
- no absolute filesystem path appears in the always-visible row text --
  the absolute path is reachable via the ``title`` hover attribute only;
- the receipt hash and absolute ISO timestamp sit inside a per-row
  ``integrity`` disclosure, never in the always-visible row text.

Every rendered value is still the runtime's own declared value (or its
documented fallback) -- Receipts v2 changes legibility, not authority.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from companion_ui.workspace.receipts_history import (
    RECEIPT_DISPLAY_VERB_FALLBACK,
    RECEIPT_RUN_LABEL_FALLBACK,
    receipts_history_fragment,
    receipts_history_view,
)

_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _receipt_row(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    """One runtime-produced receipt projection row (Receipts v2 shape)."""
    base: dict[str, Any] = {
        "receipt_id": f"receipt-{idx}",
        "trace_id": f"trace-{idx}",
        "action_id": f"action-{idx}",
        "action_type": "panel.action.logged",
        "artifact_uuid": f"uuid-{idx}",
        "artifact_path": f"Notes/note-{idx}.md",
        "path": f"Notes/note-{idx}.md",
        "requested_by": "panel",
        "approved_by": "user",
        "status": "success",
        "timestamp": f"2026-07-10T11:{idx:02d}:00Z",
        "state": "applied",
        "display_verb": "Appended to",
        "run_key": "run-1",
        "run_label": "Governed capture",
        "target_absolute": f"/Users/rasmus/vault/Notes/note-{idx}.md",
    }
    base.update(overrides)
    return base


def _browser_payload(notes_receipts: list[list[dict[str, Any]] | None]) -> dict[str, Any]:
    notes = []
    for idx, receipts in enumerate(notes_receipts, start=1):
        note: dict[str, Any] = {
            "note_path": f"Notes/note-{idx}.md",
            "title": f"Note {idx}",
            "uuid": f"uuid-{idx}",
        }
        if receipts is not None:
            note["receipts"] = receipts
        notes.append(note)
    return {"notes": notes, "read_only": True}


def _rows_html(fragment: str) -> list[str]:
    return re.findall(
        r'<li[^>]*data-testid="receipts-history-row"[^>]*>.*?</li>', fragment, re.S
    )


def _runs_html(fragment: str) -> list[str]:
    return re.findall(
        r'<li[^>]*data-testid="receipts-history-run"[^>]*>.*?</ol></li>', fragment, re.S
    )


# ---------------------------------------------------------------------------
# AC: History rows render grouped under run headers (label + relative time),
# verb + vault-relative target first, ordered most-recent-first within and
# across runs.
# ---------------------------------------------------------------------------


def test_rows_grouped_by_run() -> None:
    payload = _browser_payload(
        [
            [
                _receipt_row(
                    1,
                    timestamp="2026-07-10T11:58:00Z",
                    run_key="run-recent",
                    run_label="Governed capture",
                    display_verb="Appended to",
                ),
                _receipt_row(
                    2,
                    timestamp="2026-07-10T11:57:00Z",
                    run_key="run-recent",
                    run_label="Governed capture",
                    display_verb="Linked",
                ),
            ],
            [
                _receipt_row(
                    3,
                    timestamp="2026-07-10T11:46:00Z",
                    run_key="run-older",
                    run_label="Vault sync",
                    display_verb="Created",
                ),
            ],
        ]
    )
    view = receipts_history_view(payload, now=_NOW)
    assert [group["run_key"] for group in view["groups"]] == ["run-recent", "run-older"]
    recent_group = view["groups"][0]
    assert recent_group["run_label"] == "Governed capture"
    # Rows within the run stay most-recent-first (the runtime-declared order
    # by timestamp), matching the top-level rows order.
    assert [row["receipt_id"] for row in recent_group["rows"]] == [
        "receipt-1",
        "receipt-2",
    ]
    older_group = view["groups"][1]
    assert older_group["run_label"] == "Vault sync"
    assert [row["receipt_id"] for row in older_group["rows"]] == ["receipt-3"]

    fragment = receipts_history_fragment(payload, now=_NOW)
    runs = _runs_html(fragment)
    assert len(runs) == 2
    # The run header names the run and a relative time, e.g. "Governed
    # capture · 2 min ago" (redesigns.html §2 "Receipts v2" mockup).
    assert "Governed capture" in runs[0]
    assert "min ago" in runs[0] or "just now" in runs[0]
    assert "Vault sync" in runs[1]

    # verb + vault-relative target lead each row.
    rows = _rows_html(fragment)
    assert len(rows) == 3
    assert 'data-testid="receipts-history-verb"' in rows[0]
    assert "Appended to" in rows[0]
    assert "Notes/note-1.md" in rows[0]

    # Most-recent-first across runs too: run-recent (11:58) before
    # run-older (11:46).
    run_positions = [fragment.index('data-run-key="run-recent"'), fragment.index('data-run-key="run-older"')]
    assert run_positions == sorted(run_positions)


def test_grouping_falls_back_when_runtime_declares_no_run_key() -> None:
    """When the runtime record does not declare run_key/run_label, the row
    still renders -- honest fallbacks, never an invented run.
    """
    payload = _browser_payload(
        [[_receipt_row(1, run_key="", run_label="", display_verb="")]]
    )
    view = receipts_history_view(payload, now=_NOW)
    assert len(view["groups"]) == 1
    row = view["groups"][0]["rows"][0]
    assert row["verb"] == RECEIPT_DISPLAY_VERB_FALLBACK
    assert view["groups"][0]["run_label"] == RECEIPT_RUN_LABEL_FALLBACK
    # No declared run_key: falls back to trace_id so receipts genuinely from
    # the same trace still group; never a manufactured cross-receipt merge.
    assert row["run_key"] == "trace-1"


# ---------------------------------------------------------------------------
# AC: No absolute filesystem path appears in the always-visible text of a
# row; the absolute path is reachable via hover/disclosure.
# ---------------------------------------------------------------------------


def test_target_paths_vault_relative() -> None:
    absolute_path = "/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim/settings/workflow.md"
    payload = _browser_payload(
        [
            [
                _receipt_row(
                    1,
                    artifact_path="settings/workflow.md",
                    path="settings/workflow.md",
                    target_absolute=absolute_path,
                )
            ]
        ]
    )
    fragment = receipts_history_fragment(payload, now=_NOW)
    row = _rows_html(fragment)[0]

    # The vault-relative target is the visible text.
    target_span = re.search(
        r'<span class="receipts-history-target"[^>]*>([^<]*)</span>', row
    )
    assert target_span, "target span must render"
    assert target_span.group(1) == "settings/workflow.md"
    assert absolute_path not in target_span.group(1)

    # The absolute path is present only inside the title attribute (hover),
    # never as visible row text outside an attribute.
    assert f'title="{absolute_path}"' in row
    visible_text = re.sub(r'<[^>]*>', ' ', row)
    assert absolute_path not in visible_text


# ---------------------------------------------------------------------------
# AC: Receipt hash and absolute ISO timestamp are inside a per-row disclosure
# ("integrity"), not in the always-visible row text; guard-held note and
# read-only pill unchanged.
# ---------------------------------------------------------------------------


def test_hash_behind_integrity_disclosure() -> None:
    payload = _browser_payload(
        [
            [
                _receipt_row(
                    1,
                    receipt_id="9ee53fd2a8bb419baa80eac448b6fc5a",
                    timestamp="2026-07-07T16:22:13.674198Z",
                )
            ]
        ]
    )
    fragment = receipts_history_fragment(payload, now=_NOW)
    row = _rows_html(fragment)[0]

    # A <details> disclosure named "integrity" wraps the hash and the
    # absolute ISO timestamp.
    disclosure = re.search(
        r'<details[^>]*data-testid="receipts-history-integrity"[^>]*>.*?</details>',
        row,
        re.S,
    )
    assert disclosure, "the per-row integrity disclosure must render"
    disclosure_html = disclosure.group(0)
    assert "9ee53fd2a8bb419baa80eac448b6fc5a" in disclosure_html
    assert "2026-07-07T16:22:13.674198Z" in disclosure_html
    assert "integrity" in disclosure_html

    # The hash/timestamp are inside the disclosure, not duplicated as
    # always-visible *text* elsewhere in the row. The receipt id legitimately
    # remains as a data attribute (used by the client controller to focus a
    # targeted receipt, CUIDR-07) -- attributes are not rendered row text, so
    # strip all tags/attributes before checking for visible duplication.
    outside_disclosure = row[: disclosure.start()] + row[disclosure.end() :]
    outside_visible_text = re.sub(r"<[^>]*>", " ", outside_disclosure)
    assert "9ee53fd2a8bb419baa80eac448b6fc5a" not in outside_visible_text
    assert "2026-07-07T16:22:13.674198Z" not in outside_visible_text

    # Guard-held note and read-only semantics are unchanged by the v2
    # restructure.
    blocked_payload = _browser_payload(
        [[_receipt_row(2, status="blocked", state="blocked", display_verb="Blocked")]]
    )
    blocked_fragment = receipts_history_fragment(blocked_payload, now=_NOW)
    blocked_row = _rows_html(blocked_fragment)[0]
    assert 'data-guard-held="true"' in blocked_row
    assert 'data-testid="receipts-history-guard-note"' in blocked_row
    assert "boundary held" in blocked_row

    # No mutation affordance was introduced by the disclosure.
    assert "<button" not in fragment
    assert "<form" not in fragment
