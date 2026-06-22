"""Render every Companion UI surface to a standalone HTML file for design review.

Reuses the proven fixture builders in tests/companion_ui/test_entry_state_gallery.py
so the screens we screenshot are byte-identical to what render_index_html emits in
the dev/prod gateway. Pure render — no runtime, no network (fonts load from CDN when
online, else fall back to system fonts).

Run:  .venv/bin/python <this file>
Emits: ../screens/<id>.html  (one file per surface)
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path("/Users/rasmusthornberg/code/agentic-pkm-mvp")
SCREENS = Path(__file__).resolve().parent.parent / "screens"
SCREENS.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "companion-ui" / "companion-app"))

# Load the fixture module exactly as pytest would (register in sys.modules so its
# frozen dataclasses resolve their own __module__).
_spec = importlib.util.spec_from_file_location(
    "gallery", str(ROOT / "tests/companion_ui/test_entry_state_gallery.py")
)
g = importlib.util.module_from_spec(_spec)
sys.modules["gallery"] = g
_spec.loader.exec_module(g)

from companion_ui.workspace.serve_dev_page import render_index_html  # noqa: E402

API = "http://127.0.0.1:18001"


def render_orientation(orientation):
    return render_index_html(
        api_base_url=API,
        orientation=orientation,
        orientation_vault_browser=g._vault_browser_payload(),
    )


def render_workspace(**overrides):
    fields = g._workspace_fields(**overrides)
    return render_index_html(api_base_url=API, note_path=str(fields["note_path"]), fields=fields)


# ---------------------------------------------------------------------------
# The surface list. (id, title, html)
# ---------------------------------------------------------------------------
SCREENS_TO_RENDER = []


def add(screen_id, html):
    SCREENS_TO_RENDER.append((screen_id, html))


op = g._orientation_payload
GAP = {
    "no_mist": timedelta(seconds=30),
    "thread_fade": timedelta(minutes=5),
    "soft_mist": timedelta(hours=1),
    "full_mist": timedelta(days=1),
    "long_mist": timedelta(days=7),
    "cold": timedelta(days=21),
}

# --- Entry / orientation states --------------------------------------------
add("entry_01_first_contact", render_orientation(op(leave_status="absent")))
add("entry_02_cold_21d", render_orientation(op(gap=GAP["cold"])))
add("entry_03_no_mist", render_orientation(op(gap=GAP["no_mist"])))
add("entry_04_thread_fade", render_orientation(op(gap=GAP["thread_fade"])))
add("entry_05_soft_mist", render_orientation(op(gap=GAP["soft_mist"])))
add("entry_06_full_mist", render_orientation(op(gap=GAP["full_mist"], trajectory_state="warm")))
add(
    "entry_07_long_mist",
    render_orientation(op(gap=GAP["long_mist"], trajectory_state="dormant")),
)
add(
    "entry_08_degraded_full_mist",
    render_orientation(
        op(gap=GAP["full_mist"], degraded_reasons=["resurfacing_source_unavailable"])
    ),
)
add(
    "entry_09_stale_leave_point",
    render_orientation(op(leave_status="stale", gap=GAP["full_mist"])),
)
add("entry_10_no_vault", g._render_no_vault())

# Vault selection picker (no_vault → Option-2 picker, #2309)
add(
    "entry_11_vault_picker",
    render_index_html(
        api_base_url=API,
        vault_selection_required={
            "reason": "no_vault_bound",
            "message": "No vault is selected. Open a vault to continue.",
            "requested_note_path": "Notes/resume.md",
            "configured_vault_root": "/Users/you/iCloud/Niflheim",
        },
    ),
)

# --- Shell / workspace states ----------------------------------------------
add("shell_01_active_anchor", render_workspace())
add(
    "shell_02_staged_suggestion",
    render_workspace(
        suggestion_state="staged_body",
        suggestion_cards=[
            {
                "data_variant": "body",
                "data_suggestion_id": "sugg-1",
                "title": "Staged body suggestion",
                "preview_text": "Proposed paragraph text the agent drafted for review.",
                "available_intents": ["suggestion.apply", "suggestion.discard"],
            }
        ],
        suggested_insertions=[
            {
                "data_suggestion_id": "sugg-1",
                "data_state": "staged",
                "label": "suggested",
                "proposed_text": "Proposed paragraph text the agent drafted for review.",
                "is_visible": True,
            }
        ],
    ),
)
add(
    "shell_03_panel_proposals",
    render_workspace(
        panel_state="proposals-staged",
        panel_proposal_count=2,
        panel_proposals=[
            g._panel_proposal("prop-move-1", description="Move note to Projects/"),
            g._panel_proposal("prop-tag-2", description="Add status tag: evergreen"),
        ],
    ),
)
add(
    "shell_04_governed_receipt",
    render_workspace(
        governance_receipts=[g._governance_receipt(1)],
        panel_state="proposals-staged",
        panel_proposal_count=1,
        panel_proposals=[g._panel_proposal("prop-move-1", description="Move note to Projects/")],
        panel_last_response={
            "status": "executed",
            "proposal_id": "prop-move-1",
            "receipt": {
                "outcome": "success",
                "message": "moved via governed path",
                "timestamp": "2026-06-10T11:00:00Z",
            },
        },
    ),
)
add(
    "shell_05_panel_blocked",
    render_workspace(
        guard_writeguard_status="blocked",
        panel_state="proposals-staged",
        panel_proposal_count=1,
        panel_proposals=[g._panel_proposal("prop-cross-1", description="Cross-note proposal")],
    ),
)

# Shell variant used as the host page for overlay screenshots (rich state so the
# overlays open against a realistic backdrop).
add(
    "shell_overlay_host",
    render_workspace(
        panel_state="proposals-staged",
        panel_proposal_count=2,
        panel_proposals=[
            g._panel_proposal("prop-move-1", description="Move note to Projects/"),
            g._panel_proposal("prop-tag-2", description="Add status tag: evergreen"),
        ],
        governance_receipts=[g._governance_receipt(1)],
    ),
)


def main():
    for screen_id, html in SCREENS_TO_RENDER:
        out = SCREENS / f"{screen_id}.html"
        out.write_text(html, encoding="utf-8")
    print(f"wrote {len(SCREENS_TO_RENDER)} screens to {SCREENS}")
    for screen_id, _ in SCREENS_TO_RENDER:
        print("  ", screen_id)


if __name__ == "__main__":
    main()
