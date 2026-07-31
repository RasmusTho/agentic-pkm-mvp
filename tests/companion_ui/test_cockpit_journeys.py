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
from app.builderops import cockpit_github_plane
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


def _write_docs_fixture_with_proven_edges(docs_root: Path, *, epic_issue: int, child_issue: int) -> None:
    """A spec dir giving one thread a *proven* capability and epic rung, so
    the graph lens's "middle-only solid" rule can be proven to key off the
    rung's fixed name/position (MIDDLE_RUNGS) rather than off its class —
    without this, capability/epic never leave class="absent" in a fixture,
    and a regression that solidified any class="proven" rung (not just the
    machine-keyed middle four) would pass unnoticed (#4453 review)."""
    docs_root.mkdir(parents=True, exist_ok=True)
    (docs_root / "capabilities.yaml").write_text(
        "capabilities:\n"
        "  - id: cap-graph-fixture\n"
        "    stable_key: ckm-capability-9301\n"
        "    name: Graph Fixture Capability\n"
        "    definition: test fixture capability\n"
        "    parent: null\n"
        "    boundary_ref: GRAPH\n"
        '    seed_source: "test fixture"\n',
        encoding="utf-8",
    )
    (docs_root / "matrix.md").write_text(
        "State: test fixture traceability matrix.\n\n# Fixture Traceability Matrix\n",
        encoding="utf-8",
    )
    spec_dir = docs_root / "GRAPH_FIXTURE"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "PARENT_FEATURE_ISSUE.md").write_text(
        f"---\nname: Graph Fixture\ngithub_issue: {epic_issue}\n---\n\n# Graph Fixture\n",
        encoding="utf-8",
    )
    (spec_dir / "CHILD_TASK.md").write_text(
        "---\n"
        "name: Full Chain Thread\n"
        "task_id: GRAPH-01\n"
        f"github_issue: {child_issue}\n"
        "parent_capability: Graph Fixture Capability\n"
        "---\n\n# Full Chain Thread\n",
        encoding="utf-8",
    )


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


def _many_working_store(tmp_path: Path, count: int = 7) -> Path:
    """*count* fresh in-progress threads, all in the working band, none with a
    PR or verification run. Exercises the many-at-once row-form fallback
    (#4453 AC4) and the one-question lens's counted deferral (AC3) without
    needing the docs or GitHub planes configured."""
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for i in range(count):
        store.upsert_task(
            TaskRecord(
                task_id=f"task-many-{i}",
                repo=_REPO,
                issue_number=9200 + i,
                title=f"Working thread {i}",
                status="in_progress",
                source_anchor_refs=[],
                created_at=now,
                updated_at=now,
                priority="med",
            )
        )
    return db_path


def _graph_lens_store(tmp_path: Path) -> Path:
    """One thread with a full CI-forced chain (slice/PR/sha/receipt all
    proven) and one thread with no PR at all (those same rungs absent). The
    docs-plane fixture (wired in by the test itself, see
    ``_write_docs_fixture_with_proven_edges``) gives ``task-graph-full`` a
    genuinely *proven* capability rung and a *proven* epic rung — the graph
    lens must still never draw those solid, proving the "only slice/PR/sha/
    receipt are ever solid" rule is keyed by the rung's fixed name/position,
    not by its class (#4453 AC2; a class-keyed regression would pass
    unnoticed if capability/epic stayed ``absent`` in every fixture)."""
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    store.upsert_task(
        TaskRecord(
            task_id="task-graph-full",
            repo=_REPO,
            issue_number=9301,
            title="Full chain thread",
            status="in_progress",
            claimed_by="agent-sonnet",
            linked_pr="9401",
            source_anchor_refs=[],
            created_at=now,
            updated_at=now,
            priority="med",
        )
    )
    store.upsert_task(
        TaskRecord(
            task_id="task-graph-nopr",
            repo=_REPO,
            issue_number=9302,
            title="No-PR thread",
            status="in_progress",
            source_anchor_refs=[],
            created_at=now,
            updated_at=now,
            priority="med",
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
                "run-9401",
                "idem-9401",
                "v1",
                _REPO,
                9401,
                "d" * 40,
                "d" * 40,
                "d" * 40,
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
def _serve_cockpit(
    *,
    db_path: Path,
    deploy_receipt_dir: Path,
    docs_root: Path | None = None,
    capabilities_yaml_path: Path | None = None,
    matrix_path: Path | None = None,
    github_repo: str | None = None,
) -> Iterator[str]:
    env_keys = [
        "DISPATCHER_DB_PATH",
        "COCKPIT_DEPLOY_RECEIPT_DIR",
        "COCKPIT_DOCS_ROOT",
        "COCKPIT_CAPABILITIES_YAML",
        "COCKPIT_TRACEABILITY_MATRIX",
        # Held explicitly so an ambient COCKPIT_GITHUB_REPO on the runner
        # cannot leak the opt-in live plane — and its network call — into a
        # journey that never asked for it. Unset unless a test opts in.
        "COCKPIT_GITHUB_REPO",
    ]
    env_before = {key: os.environ.get(key) for key in env_keys}
    os.environ["DISPATCHER_DB_PATH"] = str(db_path)
    os.environ["COCKPIT_DEPLOY_RECEIPT_DIR"] = str(deploy_receipt_dir)
    if github_repo is None:
        os.environ.pop("COCKPIT_GITHUB_REPO", None)
    else:
        os.environ["COCKPIT_GITHUB_REPO"] = github_repo
    if docs_root is not None:
        os.environ["COCKPIT_DOCS_ROOT"] = str(docs_root)
    if capabilities_yaml_path is not None:
        os.environ["COCKPIT_CAPABILITIES_YAML"] = str(capabilities_yaml_path)
    if matrix_path is not None:
        os.environ["COCKPIT_TRACEABILITY_MATRIX"] = str(matrix_path)

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
                # Never the "bad" (refused) claim state. This harness never
                # configures COCKPIT_GITHUB_REPO (deliberately offline, no
                # real network per this module's docstring), so the separate,
                # opt-in github-live plane (BOPS-COCKPIT-03, #4450) always
                # reads "unavailable" here — a clean refusal of a source
                # nobody asked for, not a degradation of the dispatcher-owned
                # claim this test is actually about. Since EXT-8 (#4481) that
                # opted-out plane no longer ambers the banner either, so
                # "warn" is asserted too: without it, the false-positive amber
                # would mask a real regression in this computation.
                claim_classes = (page.locator("#claim").get_attribute("class") or "").split()
                assert "bad" not in claim_classes
                assert "warn" not in claim_classes

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


def test_unconfigured_source_pill_is_not_dead(tmp_path: Path) -> None:
    """EXT-8 (#4481): a plane nobody turned on renders calm, and says why.

    `github-live` is opt-in and no deployment sets COCKPIT_GITHUB_REPO, so the
    unconfigured read is the permanent steady state on every deployed cockpit
    — it must not wear the treatment reserved for a source that broke.
    """
    db_path = _empty_store(tmp_path)
    deploy_dir = tmp_path / "deploys"

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                github_pill = page.locator(".src", has_text="github-live")
                assert github_pill.count() == 1
                classes = (github_pill.first.get_attribute("class") or "").split()
                assert "off" in classes
                assert "dead" not in classes

                # It still names itself, in words, rather than going silent.
                pill_text = github_pill.first.inner_text()
                assert "not enabled" in pill_text
                assert "COCKPIT_GITHUB_REPO" in pill_text

                # Nothing else regressed into the dead treatment.
                assert page.locator(".src.dead").count() == 0
            finally:
                browser.close()


def test_claim_banner_ignores_unconfigured_optional_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The banner ambers for real failures only — never for an opted-out plane.

    Three states, one computation: opted-out stays calm, a required source
    that dies ambers, and an *optional* source that was configured and then
    failed ambers too. Without the middle and last cases this test would pass
    on a client that simply never ambers.
    """
    deploy_dir = tmp_path / "deploys"

    # (1) Opted out: unavailable, but nobody asked for it. Calm.
    with _serve_cockpit(
        db_path=_empty_store(tmp_path / "calm"), deploy_receipt_dir=deploy_dir
    ) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                classes = (page.locator("#claim").get_attribute("class") or "").split()
                assert "warn" not in classes
                assert "bad" not in classes
            finally:
                browser.close()

    # (2) A required source that dies still ambers. A malformed deploy receipt
    # is a read failure of a source the surface always reads — unlike a missing
    # receipt, which is structural absence and stays "empty".
    broken_deploys = tmp_path / "broken-deploys"
    broken_deploys.mkdir()
    (broken_deploys / "dev-latest.json").write_text("{not json", encoding="utf-8")

    with _serve_cockpit(
        db_path=_empty_store(tmp_path / "amber"), deploy_receipt_dir=broken_deploys
    ) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                classes = (page.locator("#claim").get_attribute("class") or "").split()
                assert "warn" in classes
                dead_names = {
                    text.split("\n", 1)[0]
                    for text in page.locator(".src.dead").all_inner_texts()
                }
                assert "deploy-receipts" in dead_names
            finally:
                browser.close()

    # (3) An *optional* plane that was configured and then failed is a real
    # outage on a host that did opt in — still amber, still the dead pill.
    # The failure is injected at the `gh` subprocess boundary so the whole
    # production reader path runs with no network (module docstring rule).
    def _refuse(args: list[str]):
        raise cockpit_github_plane.GithubReadError("simulated read failure")

    monkeypatch.setattr(cockpit_github_plane, "_run_gh", _refuse)

    with _serve_cockpit(
        db_path=_empty_store(tmp_path / "configured"),
        deploy_receipt_dir=deploy_dir,
        github_repo=_REPO,
    ) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                classes = (page.locator("#claim").get_attribute("class") or "").split()
                assert "warn" in classes
                github_pill = page.locator(".src", has_text="github-live")
                github_classes = (
                    github_pill.first.get_attribute("class") or ""
                ).split()
                assert "dead" in github_classes
                assert "off" not in github_classes
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
                # github-live is a separate, opt-in plane (BOPS-COCKPIT-03,
                # #4450): unconfigured by default in this offline harness (no
                # COCKPIT_GITHUB_REPO, no real network), so it alone reads
                # "unavailable" here — and since EXT-8 (#4481) it renders as
                # opted-out rather than dead, and leaves the banner calm. See
                # the identical accounting in test_true_emptiness_is_dated_claim.
                assert page.locator(".src.dead").count() == 0
                claim_classes = (page.locator("#claim").get_attribute("class") or "").split()
                assert "warn" not in claim_classes

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


# ---------------------------------------------------------------------------
# Surface lenses (#4453, BOPS-COCKPIT-06): graph and one-question lenses,
# many-at-once scaling, and narrow/200%/print states over the SAME payload
# the bands lens already renders. No new fetch, no payload change.
# ---------------------------------------------------------------------------


def test_lenses_project_same_data(tmp_path: Path) -> None:
    db_path = _seeded_store(tmp_path)
    deploy_dir = _deploy_receipts(tmp_path)

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector(".card", timeout=5000)

                # Bands lens is the default: its pane is the one actually
                # rendered; the other two exist in the DOM but stay hidden.
                assert page.locator("#lens-bands").is_checked()
                assert page.locator("#lens-bands-pane").is_visible()
                assert not page.locator("#lens-graph-pane").is_visible()
                assert not page.locator("#lens-question-pane").is_visible()

                bands_titles = {
                    text.strip()
                    for text in page.locator("#lens-bands-pane .card h3").all_inner_texts()
                }
                assert "Working thread" in bands_titles

                requests: list[str] = []
                page.on("request", lambda req: requests.append(req.url))

                # Graph lens: same payload, re-projected, no new fetch.
                page.locator("#lens-graph").check()
                page.wait_for_selector("#lens-graph-pane .node", timeout=5000)
                assert page.locator("#lens-graph-pane").is_visible()
                assert not page.locator("#lens-bands-pane").is_visible()
                graph_text = page.locator("#lens-graph-pane").inner_text()
                for title in bands_titles:
                    assert title in graph_text

                # One-question lens: same payload again.
                page.locator("#lens-question").check()
                page.wait_for_selector("#lens-question-pane .focus", timeout=5000)
                assert page.locator("#lens-question-pane").is_visible()
                assert not page.locator("#lens-graph-pane").is_visible()

                # Back to bands — lens choice is projection only, reversible.
                page.locator("#lens-bands").check()
                assert page.locator("#lens-bands-pane").is_visible()

                registry_hits = [u for u in requests if "/api/cockpit/registry" in u]
                assert registry_hits == [], (
                    "switching lenses must never re-fetch the registry:"
                    f" saw {registry_hits}"
                )
            finally:
                browser.close()


def test_graph_lens_solid_spine_is_machine_keyed(tmp_path: Path) -> None:
    db_path = _graph_lens_store(tmp_path)
    deploy_dir = tmp_path / "deploys"
    docs_root = tmp_path / "docs"
    _write_docs_fixture_with_proven_edges(docs_root, epic_issue=9300, child_issue=9301)

    with _serve_cockpit(
        db_path=db_path,
        deploy_receipt_dir=deploy_dir,
        docs_root=docs_root,
        capabilities_yaml_path=docs_root / "capabilities.yaml",
        matrix_path=docs_root / "matrix.md",
    ) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.locator("#lens-graph").check()
                page.wait_for_selector("#lens-graph-pane .node", timeout=5000)

                def node_classes(rung: str, thread_id: str) -> str:
                    node = page.locator(
                        f'.graf-col[data-rung="{rung}"] .node[data-thread="{thread_id}"]'
                    )
                    assert node.count() == 1, f"expected one node for {rung}/{thread_id}"
                    return node.get_attribute("class") or ""

                # The full-chain thread: slice -> PR -> sha -> receipt are all
                # proven and CI-forced. That is the only stretch the graph
                # lens ever draws solid ("node-p").
                for rung in ("slice", "pr", "ci_sha", "receipt"):
                    classes = node_classes(rung, "task-graph-full")
                    assert "node-p" in classes, f"{rung} should be solid: {classes}"

                # Everything left of slice, and "tried", is never solid, even
                # though this same thread's middle rungs are fully proven.
                for rung in ("intention", "capability", "epic", "tried"):
                    classes = node_classes(rung, "task-graph-full")
                    assert "node-p" not in classes, f"{rung} must not be solid: {classes}"
                # intention and tried are unconditionally absent in v1 (no
                # docs-plane state can change that) — deterministically dashed.
                assert "node-abs" in node_classes("intention", "task-graph-full")
                assert "node-abs" in node_classes("tried", "task-graph-full")
                # capability and epic are NOT absent here — the docs fixture
                # gives both a genuinely proven/derived class — yet they still
                # must not render solid. This is the discriminating case: it
                # proves the solid-spine rule is keyed by rung name/position
                # (MIDDLE_RUNGS), not by rung class, which a fixture where
                # capability/epic stay "absent" cannot distinguish.
                capability_classes = node_classes("capability", "task-graph-full")
                assert "node-abs" not in capability_classes, (
                    "fixture setup failed: capability should be proven, not absent"
                )
                epic_classes = node_classes("epic", "task-graph-full")
                assert "node-abs" not in epic_classes, (
                    "fixture setup failed: epic should be proven, not absent"
                )

                # The no-PR thread: pr/ci_sha/receipt are genuinely absent
                # (no PR was ever linked) — never solid either.
                for rung in ("pr", "ci_sha", "receipt"):
                    classes = node_classes(rung, "task-graph-nopr")
                    assert "node-p" not in classes, f"{rung} must not be solid: {classes}"
                    assert "node-abs" in classes

                # Its slice rung is still proven (it has an issue_number) —
                # confirms absence is per-rung, not a whole-thread veto.
                assert "node-p" in node_classes("slice", "task-graph-nopr")
            finally:
                browser.close()


def test_one_question_lens_counted_deferral(tmp_path: Path) -> None:
    db_path = _many_working_store(tmp_path, count=7)
    deploy_dir = tmp_path / "deploys"

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.locator("#lens-question").check()
                page.wait_for_selector("#f1", timeout=5000)

                assert page.locator("#f1").is_visible()
                assert not page.locator("#f2").is_visible()

                # The question and its claim answer both use the display
                # serif face (never the UI sans face a plain label would use).
                claim_font = page.locator("#f1 .a").evaluate(
                    "el => getComputedStyle(el).fontFamily"
                )
                question_font = page.locator("#f1 .q").evaluate(
                    "el => getComputedStyle(el).fontFamily"
                )
                assert claim_font == question_font

                rows = page.locator("#f1 .focus-list li")
                assert rows.count() == 5, "one-question lens must cap at 5 rows"

                deferral = page.locator('#f1 label[for="lens-bands"]')
                assert deferral.count() == 1, "overflow must be an explicit counted link"
                assert "2 more in the register" in deferral.inner_text()

                # The deferral switches to the bands lens — a counted
                # redirect into the full register, never a silent drop.
                deferral.click()
                page.wait_for_selector("#lens-bands-pane .band", timeout=5000)
                assert page.locator("#lens-bands").is_checked()
                assert page.locator("#lens-bands-pane").is_visible()
            finally:
                browser.close()


def test_many_at_once_no_hiding(tmp_path: Path) -> None:
    db_path = _many_working_store(tmp_path, count=8)
    deploy_dir = tmp_path / "deploys"

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector("#lens-bands-pane .band", timeout=5000)

                working_band = page.locator("#lens-bands-pane .band").first
                assert "8" in working_band.locator(".band-count").inner_text()

                full_cards = working_band.locator(".card")
                assert full_cards.count() == 5, "at most 5 cards render in full form"

                rows = working_band.locator(".thread-row")
                assert rows.count() == 3, "the remaining 3 must fall to row form"

                # Row form still carries the same 8-rung evidence spine.
                for i in range(rows.count()):
                    assert rows.nth(i).locator(".spine b").count() == 8

                # Nothing is hidden: all 8 threads are on the surface — 5 as
                # cards, 3 as rows — never a "+N more" silence.
                body_text = page.locator("#lens-bands-pane").inner_text()
                for i in range(8):
                    assert f"Working thread {i}" in body_text
            finally:
                browser.close()


def test_narrow_zoom_and_print_states(tmp_path: Path) -> None:
    db_path = _seeded_store(tmp_path)
    deploy_dir = _deploy_receipts(tmp_path)

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector(".card", timeout=5000)

                # Narrow width (roughly what 200% zoom at a normal desktop
                # width leaves as the effective viewport): no page-level
                # horizontal scroll, and the switcher wraps instead of
                # forcing overflow.
                page.set_viewport_size({"width": 400, "height": 900})
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth"
                    " - document.documentElement.clientWidth"
                )
                assert overflow <= 1, f"page-level horizontal scroll: {overflow}px"

                sw_wrap = page.locator(".sw-row").first.evaluate(
                    "el => getComputedStyle(el).flexWrap"
                )
                assert sw_wrap == "wrap"

                # Print: switcher and action buttons hidden, card bodies
                # forced open, and the printable units never split across a
                # page break.
                page.emulate_media(media="print")
                sw_display = page.locator(".sw").evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert sw_display == "none"

                out_display = page.locator(".out").first.evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert out_display == "none"

                closed_card = page.locator(".card:not([open])").first
                body_display = closed_card.locator(".body").evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert body_display != "none", "print must force details open"

                for selector in (".band", ".card", ".tier"):
                    break_style = page.locator(selector).first.evaluate(
                        "el => getComputedStyle(el).breakInside"
                    )
                    assert break_style in ("avoid-page", "avoid"), (
                        f"{selector} must not split across a page break:"
                        f" {break_style}"
                    )

                # Print must still project only the currently-selected lens
                # (AC1: "lens choice changes projection", including in print)
                # — the default bands lens stays visible; the graph and
                # one-question panes, never selected here, must not also
                # render (#4453 review: a prior !important print rule forced
                # all three panes and all four question screens open at once).
                bands_display = page.locator("#lens-bands-pane").evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert bands_display == "block"
                graph_display = page.locator("#lens-graph-pane").evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert graph_display == "none", "unselected graph pane must stay hidden in print"
                question_display = page.locator("#lens-question-pane").evaluate(
                    "el => getComputedStyle(el).display"
                )
                assert question_display == "none", (
                    "unselected one-question pane must stay hidden in print"
                )
            finally:
                browser.close()


def test_print_hides_overflow_deferral_link(tmp_path: Path) -> None:
    """The one-question lens's "+N more in the register" deferral is a real
    clickable control (same family as the switcher and out-links), so print
    must hide it too — it is not a printable claim (#4453 review: it lived
    outside the .focus-nav wrapper the print rule actually hides, so it
    stayed visible whenever a band's overflow made it render at all)."""
    db_path = _many_working_store(tmp_path, count=7)
    deploy_dir = tmp_path / "deploys"

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.locator("#lens-question").check()
                page.wait_for_selector("#f1", timeout=5000)
                deferral = page.locator('#f1 label[for="lens-bands"]')
                assert deferral.count() == 1, "overflow must be present for this fixture"

                page.emulate_media(media="print")
                # The deferral is hidden via its .focus-nav *ancestor*'s
                # display:none, not its own — getComputedStyle on the
                # element itself would still report its own inline-flex
                # regardless of an ancestor hiding it, so actual rendered
                # visibility (which does account for ancestors) is the
                # correct check here.
                assert not deferral.is_visible(), (
                    "the overflow deferral link must be hidden in print"
                )
            finally:
                browser.close()


def test_flaws_band_header_renders_not_evaluated_and_unread(tmp_path: Path) -> None:
    """The flaws band's own header (app/builderops/cockpit_chain.py
    ::flaws_band_header) names which flaw predicates this render could not
    evaluate because their required source wasn't fresh (``not_evaluated``),
    and which flaw types v1 never reads at all (``unread``) — distinct from
    and more specific than the capability-wide ``#unread-planes`` list, which
    names planes the whole surface never reads, not individual flaw
    predicates. #4479: the payload already carried this data; cockpit.js
    never rendered it."""
    db_path = _seeded_store(tmp_path)
    deploy_dir = _deploy_receipts(tmp_path)

    with _serve_cockpit(db_path=db_path, deploy_receipt_dir=deploy_dir) as url:
        with sync_playwright() as playwright:
            browser, page = _open_page(playwright, url)
            try:
                page.wait_for_selector(".card", timeout=5000)

                flawed_band = page.locator("section.band").filter(
                    has_text="What has flaws?"
                )
                assert flawed_band.count() == 1

                # github-live is unconfigured in this offline harness (no
                # COCKPIT_GITHUB_REPO), so every predicate requiring it is
                # not evaluated on this render — named, not silently skipped.
                not_evaluated = flawed_band.locator(".flaws-not-evaluated")
                assert not_evaluated.count() == 1
                not_evaluated_text = not_evaluated.inner_text()
                assert "pr_ci_red_on_head_sha" in not_evaluated_text
                assert "github-live" in not_evaluated_text

                # The fixed unread set (planes v1 never reads at all).
                unread = flawed_band.locator(".flaws-unread")
                assert unread.count() == 1
                unread_text = unread.inner_text()
                assert "unpushed_local_worktree" in unread_text
                assert "git working trees" in unread_text

                # Distinct from the coarser capability-wide list, not a copy.
                top_unread = page.locator("#unread-planes").inner_text()
                assert "git" in top_unread
                assert unread_text != top_unread
            finally:
                browser.close()
