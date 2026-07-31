"""Playwright browser tests: the served ``/cockpit`` surface proves red-not-calm
when a source dies, dates true emptiness, renders the locked join contract when
populated, and stays keyboard-reachable (#4448,
docs/BUILDEROPS_COCKPIT/INDUCED_FAILURE_JOURNEYS.md).

``tests/builderops/test_cockpit_registry.py`` unit-proves the join
(``build_registry``) in isolation. Nothing there asserts the *rendered
surface* — a regression in ``cockpit.js`` could show ``0`` over a refused
claim and every unit test would stay green. These journeys drive the actual
production route (``app.api.routes.cockpit.registry``, the same coroutine
``GET /api/cockpit/registry`` calls) against a dead / empty / seeded
dispatcher store and assert the rendered DOM text, never implementation
internals.

Serving approach: this repo's established browser-runtime pattern is a plain
``http.server.HTTPServer`` over deterministic, fully offline content — no live
vault, no live GitHub, no real network. The cockpit surface differs from the
workspace-shell tests in one respect: its payload is not a pure render
function, it is a live read-time join over a SQLite store. So this harness
serves the real, unmodified ``cockpit.html``/``cockpit.js``/``cockpit.css``/
``colors_and_type.css`` files from disk, and answers
``GET /api/cockpit/registry`` by invoking the actual production endpoint
coroutine (``app.api.routes.cockpit.registry``) with ``DISPATCHER_DB_PATH`` /
``COCKPIT_DEPLOY_RECEIPT_DIR`` pointed at the test fixture — the same env-var
contract the deployed API reads at request time (``app/dispatcher/config.py``,
``app/api/routes/cockpit.py``). This exercises the production endpoint and the
production join code (``build_registry``) without booting the full
``app.api.app`` FastAPI application (dozens of optional routers with their own
heavy imports) inside a browser-runtime test — staying inside the established
deterministic-offline convention this lane already relies on.

Guard: Playwright + Chromium must be available, else the module is skipped
(not failed). Set COMPANION_UI_BROWSER_TESTS=1 to enable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Iterator
from urllib.parse import urlparse

import pytest

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 to run Playwright browser-runtime tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
except ImportError:
    pytest.skip(
        "playwright package not installed — skipping browser tests.",
        allow_module_level=True,
    )

from app.api.routes.cockpit import registry as _cockpit_registry_endpoint
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore

from tests.companion_ui.browser_runtime_harness import install_offline_esm_routes

pytestmark = pytest.mark.browser_runtime

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATIC_DIR = _REPO_ROOT / "app" / "web" / "static"
_REPO = "RasmusTho/agentic-pkm-mvp"

_COCKPIT_HTML = (_STATIC_DIR / "cockpit.html").read_bytes()
_COCKPIT_JS = (_STATIC_DIR / "cockpit.js").read_bytes()
_COCKPIT_CSS = (_STATIC_DIR / "cockpit.css").read_bytes()
_COLORS_CSS = (_STATIC_DIR / "colors_and_type.css").read_bytes()


# ---------------------------------------------------------------------------
# Fixture stores
# ---------------------------------------------------------------------------


def _dead_store_path(tmp_path: Path) -> Path:
    """A store path whose parent directory does not exist: unreadable, never
    silently created (mirrors tests/builderops/test_cockpit_registry.py
    ``test_refused_emptiness_on_dead_source``)."""
    return tmp_path / "nowhere" / "dispatcher.sqlite3"


def _empty_store(tmp_path: Path) -> Path:
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    return db_path


def _seeded_store(tmp_path: Path) -> Path:
    """A store with one item in each band, a verification run with a receipt,
    and an out-link URL on the delivered item."""
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def _record(**overrides: object) -> TaskRecord:
        fields: dict[str, object] = {
            "repo": _REPO,
            "source_anchor_refs": [],
            "created_at": now,
            "updated_at": now,
            "priority": "med",
        }
        fields.update(overrides)
        return TaskRecord(**fields)  # type: ignore[arg-type]

    store.upsert_task(
        _record(
            task_id="task-working-1",
            issue_number=9001,
            title="Working thread",
            status="in_progress",
            claimed_by="agent-sonnet",
            linked_pr="9101",
        )
    )
    store.upsert_task(
        _record(
            task_id="task-done-1",
            issue_number=9002,
            title="Delivered thread",
            status="completed",
            sync_state={
                "labels": ["type:task"],
                "url": f"https://github.com/{_REPO}/issues/9002",
            },
        )
    )
    store.upsert_task(
        _record(
            task_id="task-flawed-1",
            issue_number=9003,
            title="Flawed thread",
            status="blocked",
            blocked_reason="upstream contract gap",
        )
    )
    store.upsert_task(
        _record(
            task_id="task-forgotten-1",
            issue_number=9004,
            title="Forgotten thread",
            status="ready",
        )
    )
    store.upsert_task(
        _record(
            task_id="task-needs-you-1",
            issue_number=9005,
            title="Needs a human",
            status="blocked",
            sync_state={"labels": ["agent:needs-human"]},
        )
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO verification_runs (run_id, idempotency_key,"
            " contract_version, repository, pr_number, head_sha,"
            " current_head_sha, verified_head_sha, stage, request_json,"
            " status, terminal_receipt_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-9101",
                "idem-9101",
                "v1",
                _REPO,
                9101,
                "b" * 40,
                "b" * 40,
                "b" * 40,
                "verify",
                "{}",
                "completed",
                json.dumps({"outcome": "merged"}),
                now,
                now,
            ),
        )
    return db_path


def _deploy_receipts(tmp_path: Path) -> Path:
    receipt_dir = tmp_path / "deploys"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for channel in ("dev", "test", "prod"):
        (receipt_dir / f"{channel}-latest.json").write_text(
            json.dumps(
                {"channel": channel, "sha": "c" * 40, "recorded_at": recorded_at}
            ),
            encoding="utf-8",
        )
    return receipt_dir


# ---------------------------------------------------------------------------
# Harness: serve the real static cockpit surface; answer the registry route
# by invoking the actual production endpoint against the given fixture paths.
# ---------------------------------------------------------------------------


@contextmanager
def _serve_cockpit(*, db_path: Path, deploy_receipt_dir: Path) -> Iterator[str]:
    env_before = {
        key: os.environ.get(key)
        for key in ("DISPATCHER_DB_PATH", "COCKPIT_DEPLOY_RECEIPT_DIR")
    }
    os.environ["DISPATCHER_DB_PATH"] = str(db_path)
    os.environ["COCKPIT_DEPLOY_RECEIPT_DIR"] = str(deploy_receipt_dir)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/cockpit":
                self._send(200, "text/html; charset=utf-8", _COCKPIT_HTML)
            elif parsed.path == "/static/cockpit.js":
                self._send(200, "text/javascript; charset=utf-8", _COCKPIT_JS)
            elif parsed.path == "/static/cockpit.css":
                self._send(200, "text/css; charset=utf-8", _COCKPIT_CSS)
            elif parsed.path == "/static/colors_and_type.css":
                self._send(200, "text/css; charset=utf-8", _COLORS_CSS)
            elif parsed.path == "/api/cockpit/registry":
                # The real production route coroutine: app.api.routes.cockpit
                # ::registry -> app.dispatcher.config::load_paths (reads
                # DISPATCHER_DB_PATH) -> app.builderops.cockpit_registry
                # ::build_registry. Not a hand-written fake payload.
                payload = asyncio.run(_cockpit_registry_endpoint())
                body = json.dumps(payload).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/cockpit"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _open_page(playwright, url: str):
    """Launch Chromium with offline-routed fonts/ESM (repo convention: no
    real network calls in a deterministic browser test) and load *url*."""
    browser = playwright.chromium.launch()
    context = browser.new_context()
    install_offline_esm_routes(context)
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("#bands .band", timeout=5000)
    return browser, page


# ---------------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------------


def test_dead_source_renders_refusal_not_calm(tmp_path: Path) -> None:
    db_path = _dead_store_path(tmp_path)
    deploy_dir = tmp_path / "deploys"

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector("#claim.bad", timeout=5000)
                claim_text = page.locator("#claim-text").inner_text()
                assert "cannot say what is in motion" in claim_text
                assert "dispatcher store" in claim_text

                # Red-not-calm: every band refuses the count; none shows 0.
                counts = page.locator(".band-count").all_inner_texts()
                assert len(counts) == 5
                assert all(count.strip() == "cannot be counted" for count in counts)

                body_text = page.locator("body").inner_text()
                assert "0 threads" not in body_text

                dead_pill = page.locator(".src.dead")
                assert dead_pill.count() >= 1
                assert "dispatcher-store" in dead_pill.first.inner_text()
            finally:
                browser.close()

    # The refusal must never have created the missing store as a side effect.
    assert not db_path.exists()


def test_true_emptiness_is_dated_claim(tmp_path: Path) -> None:
    db_path = _empty_store(tmp_path)
    deploy_dir = tmp_path / "deploys"  # no receipts recorded: structural absence

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                claim_text = page.locator("#claim-text").inner_text()
                assert claim_text.startswith("0 threads in motion as of ")
                # Neither the "bad" (refused) nor "warn" (degraded) claim state.
                assert page.locator("#claim").get_attribute("class") == "claim"

                assert page.locator(".src.dead").count() == 0
                pill_texts = " ".join(page.locator(".src").all_inner_texts())
                assert "dispatcher-store" in pill_texts
                assert "verification-runs" in pill_texts

                # Bands present at zero: counted, not refused.
                counts = page.locator(".band-count").all_inner_texts()
                assert len(counts) == 5
                assert all(count.strip() == "0" for count in counts)
            finally:
                browser.close()


def test_populated_bands_spine_freshness(tmp_path: Path) -> None:
    db_path = _seeded_store(tmp_path)
    deploy_dir = _deploy_receipts(tmp_path)

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector(".card", timeout=5000)

                # Locked band order, in locked document order.
                questions = page.locator(".band-q").all_inner_texts()
                assert questions == [
                    "What are we working on?",
                    "What is done?",
                    "What has flaws?",
                    "What is forgotten?",
                    "Needs you",
                ]

                # Evidence spine per card: 8 locked rungs (RUNG_ORDER).
                first_card = page.locator(".card").first
                assert first_card.locator(".spine b").count() == 8
                first_card.locator("summary").click()
                page.wait_for_selector(".card[open]", timeout=5000)
                assert first_card.locator(".rungs li").count() == 8

                # Per-source freshness pills for every source the join reads.
                pill_texts = " ".join(page.locator(".src").all_inner_texts())
                for name in ("dispatcher-store", "verification-runs", "deploy-receipts"):
                    assert name in pill_texts
                assert page.locator(".src.dead").count() == 0

                # Out-link on the delivered card carries the authority URL.
                done_card = page.locator(".card.card-done").first
                done_card.locator("summary").click()
                page.wait_for_selector(".card.card-done[open]", timeout=5000)
                out_link = done_card.locator("a.btn-out")
                assert out_link.count() == 1
                assert (
                    out_link.get_attribute("href")
                    == f"https://github.com/{_REPO}/issues/9002"
                )
            finally:
                browser.close()


def test_keyboard_reachability_and_focus(tmp_path: Path) -> None:
    db_path = _seeded_store(tmp_path)
    deploy_dir = _deploy_receipts(tmp_path)

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector(".card", timeout=5000)

                # Cards are reachable in the page's natural Tab order: no
                # explicit focus() call, just repeated Tab presses from a
                # blurred document.
                page.evaluate(
                    "document.activeElement && document.activeElement.blur()"
                )
                found = False
                for _ in range(40):
                    page.keyboard.press("Tab")
                    is_card_summary = page.evaluate(
                        "(() => {"
                        "const el = document.activeElement;"
                        "return !!(el && el.tagName === 'SUMMARY'"
                        " && el.closest('details.card'));"
                        "})()"
                    )
                    if is_card_summary:
                        found = True
                        break
                assert found, "no card summary reached by natural Tab order"

                # Visible focus ring (cockpit.css .card>summary:focus-visible).
                outline_style = page.evaluate(
                    "getComputedStyle(document.activeElement).outlineStyle"
                )
                outline_width = page.evaluate(
                    "getComputedStyle(document.activeElement).outlineWidth"
                )
                assert outline_style == "solid"
                assert outline_width != "0px"

                # Expandable via keyboard: Enter toggles the native <details>.
                was_open = page.evaluate(
                    "document.activeElement.closest('details.card').hasAttribute('open')"
                )
                assert was_open is False
                page.keyboard.press("Enter")
                page.wait_for_function(
                    "document.activeElement.closest('details.card')"
                    ".hasAttribute('open')",
                    timeout=5000,
                )
            finally:
                browser.close()
