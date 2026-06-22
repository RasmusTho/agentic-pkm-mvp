"""Screenshot every rendered Companion UI surface with Playwright (Chromium).

Loads each standalone screen from ../screens, captures the base state, then drives
the overlay host page through every shipped drawer/modal and captures each open
state. Also captures the two most layout-sensitive surfaces at a narrow width.

Run:  .venv/bin/python <this file>
Emits: ../img/<id>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
SCREENS = BASE / "screens"
IMG = BASE / "img"
IMG.mkdir(exist_ok=True)

DESKTOP = {"width": 1440, "height": 900}
NARROW = {"width": 430, "height": 932}

# Base full-page captures (desktop).
BASE_SHOTS = [
    "entry_01_first_contact",
    "entry_02_cold_21d",
    "entry_03_no_mist",
    "entry_04_thread_fade",
    "entry_05_soft_mist",
    "entry_06_full_mist",
    "entry_07_long_mist",
    "entry_08_degraded_full_mist",
    "entry_09_stale_leave_point",
    "entry_10_no_vault",
    "entry_11_vault_picker",
    "shell_01_active_anchor",
    "shell_02_staged_suggestion",
    "shell_03_panel_proposals",
    "shell_04_governed_receipt",
    "shell_05_panel_blocked",
]

# Overlays driven open on the overlay-host shell page via the page's own
# overlayHost.mount() API (the topbar triggers overflow off-screen at 1440 —
# itself a finding — so we open through the canonical JS path instead of a click).
# (img_id, overlay_occupant_id)
OVERLAYS = [
    ("overlay_01_command_palette", "cmd"),
    ("overlay_02_capture_modal", "capture"),
    ("overlay_03_memory_review", "memory"),
    ("overlay_04_settings_drawer", "settings"),
    ("overlay_05_vault_browser", "vault"),
    ("overlay_06_receipts_history", "receipts"),
    ("overlay_07_system_map", "map"),
]

# Narrow / responsive captures.
NARROW_SHOTS = ["shell_01_active_anchor", "entry_07_long_mist"]


def file_url(screen_id: str) -> str:
    return (SCREENS / f"{screen_id}.html").resolve().as_uri()


def main() -> int:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # --- base full-page desktop shots ---
        ctx = browser.new_context(viewport=DESKTOP, device_scale_factor=2)
        page = ctx.new_page()
        for sid in BASE_SHOTS:
            page.goto(file_url(sid), wait_until="networkidle")
            page.wait_for_timeout(450)
            page.screenshot(path=str(IMG / f"{sid}.png"), full_page=True)
            results.append(sid)
        ctx.close()

        # --- overlay shots: mount each occupant via the page's overlayHost API ---
        for img_id, occupant in OVERLAYS:
            ctx = browser.new_context(viewport=DESKTOP, device_scale_factor=2)
            page = ctx.new_page()
            page.goto(file_url("shell_overlay_host"), wait_until="networkidle")
            page.wait_for_timeout(500)
            opened = page.evaluate(
                """(id) => {
                    if (!window.overlayHost || !window.overlayHost.mount) return 'no-host';
                    window.overlayHost.mount(id);
                    const host = document.querySelector('[data-region=\"overlay-host\"]');
                    return host ? host.getAttribute('data-overlay-open') : 'no-host-el';
                }""",
                occupant,
            )
            if opened != occupant:
                print(f"  !! {img_id}: overlay-open={opened!r} (wanted {occupant})", file=sys.stderr)
            page.wait_for_timeout(700)
            page.screenshot(path=str(IMG / f"{img_id}.png"), full_page=False)
            results.append(img_id)
            ctx.close()

        # --- guidance layer: flip the shell root attribute the toggle controls ---
        ctx = browser.new_context(viewport=DESKTOP, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(file_url("shell_overlay_host"), wait_until="networkidle")
        page.wait_for_timeout(400)
        page.evaluate(
            """() => {
                const t = document.querySelector('[data-intent=\"guidance.toggle\"]');
                if (t) { t.click(); return; }
                const root = document.querySelector('[data-entry-state]');
                if (root) root.setAttribute('data-guidance', 'on');
            }"""
        )
        page.wait_for_timeout(500)
        page.screenshot(path=str(IMG / "overlay_08_guidance_layer.png"), full_page=True)
        results.append("overlay_08_guidance_layer")
        ctx.close()

        # --- narrow / responsive ---
        for sid in NARROW_SHOTS:
            ctx = browser.new_context(viewport=NARROW, device_scale_factor=2)
            page = ctx.new_page()
            page.goto(file_url(sid), wait_until="networkidle")
            page.wait_for_timeout(450)
            page.screenshot(path=str(IMG / f"narrow_{sid}.png"), full_page=True)
            results.append(f"narrow_{sid}")
            ctx.close()

        browser.close()

    print(f"captured {len(results)} screenshots to {IMG}")
    for r in results:
        print("  ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
