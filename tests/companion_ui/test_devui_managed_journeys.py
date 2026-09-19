"""Actual standalone listener journeys; only external source/transport faults are fixtures."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from tests.builderops.test_devui_runtime import (
    MANAGED_SUBJECT,
    _package_managed_shell,
    managed_sources,  # noqa: F401 - source-bound pytest fixture
)

if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
    pytest.skip(
        "Set COMPANION_UI_BROWSER_TESTS=1 for managed browser proof", allow_module_level=True
    )

from playwright.sync_api import sync_playwright
import uvicorn
from app.builderops.devui_runtime import production_app
from app.builderops.devui_sources import package_candidate

pytestmark = pytest.mark.browser_runtime
ORIGIN = "http://127.0.0.1:8113"
FOCUS = "/devui/focus?subject=github%3Aexample%2Ffixture%23501"
EXPECTED_DISCLOSURE_SUMMARIES = {
    "overview": [
        "Inspect trust frame",
        "Inspect subject source details",
        "Inspect evidence details",
        "Inspect evidence details",
        "Inspect evidence details",
        "Inspect evidence details",
    ],
    "focus": ["Inspect source and technical details"] * 10,
}
EXPECTED_OVERVIEW_EVIDENCE_IDENTITIES = [
    {
        "source_type": "builderops_cockpit_working_projection",
        "source_id": "cockpit:working:github:example/fixture#501",
    },
    {"source_type": "docs-frontmatter", "source_id": "capability:fixture"},
    {
        "source_type": "dispatcher-store",
        "source_id": "dispatcher:github:example/fixture#501",
    },
    {
        "source_type": "builderops_mirror",
        "source_id": "mirror:github:example/fixture#501",
    },
]
EXPECTED_FOCUS_ENTRY_IDENTITIES = {
    "focus-owner-intent": [
        {
            "key": "summary",
            "value": "Declared Context:\nFixture owner intent.\n\nDeclared Scope:\nFixture source scope.",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501",
        }
    ],
    "focus-governing-sources": [
        {
            "key": "claim_id",
            "value": "governing-subject",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501",
        },
        {
            "key": "claim_id",
            "value": "issue-declaration:source-anchors:r1-1e08b386e6ca3ff9",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501#source-anchors",
        },
        {
            "key": "claim_id",
            "value": "issue-declaration:source-docs:r1-6119125eb82ddba1",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501#source-docs",
        },
    ],
    "focus-evidence": [
        {
            "key": "claim_id",
            "value": "subject-read",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501",
        },
        {
            "key": "claim_id",
            "value": "issue-declaration:acceptance-criteria:r1-56e00693da9440a2",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501#acceptance-criteria",
        },
    ],
    "focus-receipts": [],
    "focus-risks": [],
    "focus-next-step": [{"key": "legality", "value": "unavailable", "source_id": None, "locator": None}],
    "focus-execution": [],
    "focus-conversation": [{"key": "availability", "value": "unsupported", "source_id": None, "locator": None}],
    "focus-limitations": [
        {
            "key": "kind",
            "value": "criterion_results_unassessed",
            "source_id": "example/fixture#501",
            "locator": "https://github.com/Example/Fixture/issues/501#acceptance-criteria",
        },
        {"key": "kind", "value": "owner_facts_unavailable", "source_id": None, "locator": None},
    ],
}


@contextmanager
def _server(source, monkeypatch):
    source.environment["DEVUI_REPOSITORY"] = "Example/Fixture"
    source.gh_mode.write_text("canonical_case")
    _package_managed_shell(source.root)
    manifest = json.loads((source.root / "manifest.json").read_text())
    package_candidate(
        source.root,
        repository=source.environment["DEVUI_REPOSITORY"],
        source_sha=source.environment["DEVUI_SOURCE_SHA"],
        capabilities=manifest["capabilities"],
        matrix=manifest["matrix"],
    )
    for key, value in source.environment.items():
        monkeypatch.setenv(key, value)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 8113))
    server = uvicorn.Server(
        uvicorn.Config(
            production_app(), log_level="critical", proxy_headers=False, access_log=False
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started
        yield
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


@contextmanager
def _browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        )
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        external, requests, errors, console = [], [], [], []
        context.route(
            "**/*",
            lambda route: (external.append(route.request.url), route.abort())
            if not route.request.url.startswith(ORIGIN + "/")
            else route.continue_(),
        )
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on("request", lambda r: requests.append((r.method, r.url)))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        try:
            yield page, context, browser, external, requests, errors, console
        finally:
            context.close()
            browser.close()


def _loaded(page, surface):
    page.locator(f'[data-testid="{surface}-load-state"][data-state="loaded"]').wait_for()


def _no_persistence(page, context):
    assert context.cookies() == []
    assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
    assert page.evaluate("indexedDB.databases()") == []
    assert page.evaluate("caches.keys()") == []
    assert page.evaluate("navigator.serviceWorker.getRegistrations().then(x => x.length)") == 0


def _assert_focus_technical_axis_disclosure(page):
    axis_names = {"availability", "freshness", "coverage", "completeness", "cardinality", "linkage"}
    for testid in ("focus-governing-sources", "focus-evidence"):
        section = page.locator(f'[data-testid="{testid}"]')
        entries = section.locator(':scope > div > .focus-entry').all()
        assert entries
        for entry in entries:
            details = entry.locator(':scope > details.technical-disclosure')
            assert details.count() == 1
            assert not details.evaluate("element => element.open")
            axis_rows = details.locator("ul.rungs > li").evaluate_all(
                """items => items
                    .map(item => [item.querySelector(':scope > b')?.textContent,
                                  item.querySelector(':scope > code')?.textContent])
                    .filter(([key]) => ['availability', 'freshness', 'coverage', 'completeness', 'cardinality', 'linkage'].includes(key))"""
            )
            assert axis_rows
            owner_text = entry.locator(':scope > .owner-summary').inner_text().lower()
            assert all(axis not in owner_text for axis in axis_names)
            details.locator("summary").click()
            assert details.evaluate("element => element.open")
            expanded_rows = details.locator("ul.rungs > li").all()
            assert all(row.is_visible() for row in expanded_rows)
            expanded_axis_rows = details.locator("ul.rungs > li").evaluate_all(
                """items => items
                    .map(item => [item.querySelector(':scope > b')?.textContent,
                                  item.querySelector(':scope > code')?.textContent])
                    .filter(([key]) => ['availability', 'freshness', 'coverage', 'completeness', 'cardinality', 'linkage'].includes(key))"""
            )
            assert expanded_axis_rows == axis_rows
            details.locator("summary").click()

    conversation = page.locator('[data-testid="focus-conversation"]')
    assert "unsupported" in conversation.inner_text().lower()
    assert "not delivered" in conversation.inner_text().lower()
    next_step = page.locator('[data-testid="focus-next-step"]')
    assert "unavailable" in next_step.inner_text().lower()
    assert "infer" in next_step.inner_text().lower()
    limitation_text = page.locator('[data-testid="focus-limitations"]').inner_text().lower()
    assert any(token in limitation_text for token in ("acceptance", "unassessed", "owner outcome"))


def _capture(page, name):
    folder = os.environ.get("DEVUI_MANAGED_EVIDENCE_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / (name + ".png")), full_page=True)
        (path / (name + ".aria.txt")).write_text(page.locator("body").aria_snapshot())


def _keyboard_navigation(
    page,
    surface,
    *,
    navigate=True,
    expected_provider_identity: list[dict[str, object]] | None = None,
    expected_evidence_identity: list[dict[str, object]] | None = None,
):
    """Prove the finite fixture-bound disclosure inventory plus route link."""
    destination = FOCUS if surface == "overview" else "/devui/overview"
    name = "Open Focus" if surface == "overview" else "Return to Overview"
    link = page.get_by_role("link", name=name)
    assert link.count() == 1
    assert link.get_attribute("href") == destination
    expected_summaries = EXPECTED_DISCLOSURE_SUMMARIES[surface]
    assert page.locator("details.technical-disclosure > summary").all_text_contents() == expected_summaries, (
        "Only the admitted navigation and disclosures are keyboard interactive"
    )
    provider_identity = None
    if surface == "overview":
        if expected_evidence_identity is None:
            expected_evidence_identity = EXPECTED_OVERVIEW_EVIDENCE_IDENTITIES
        provider_inventory = page.evaluate(
            """({providerIdentity, expectedEvidenceIdentity}) => {
                const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
                const frame = document.querySelector('[data-testid="overview-trust-frame"]');
                const details = trust && trust.querySelector(':scope > details.technical-disclosure');
                const providers = details
                    ? Array.from(details.querySelectorAll(':scope > section.provider-state'))
                    : [];
                const identity = providers.map(section => ({
                    role: section.dataset.providerRole,
                    rows: Array.from(section.querySelectorAll(':scope > ul.rungs > li')).map(row => [
                        row.querySelector(':scope > b')?.textContent,
                        row.querySelector(':scope > code')?.textContent,
                    ]),
                }));
                const evidenceIdentity = entry => {
                    const details = entry.querySelector(':scope > details.technical-disclosure');
                    if (!details || entry.children.length !== 2 ||
                        !entry.children[0].classList.contains('owner-summary') ||
                        entry.children[1] !== details || details.children.length !== 3 ||
                        !details.children[0].matches('summary') ||
                        !details.children[1].classList.contains('matrix') ||
                        !details.children[2].matches('ul.rungs')) return null;
                    const row = Array.from(details.querySelectorAll(':scope > ul.rungs > li'))
                        .find(item => item.querySelector(':scope > b')?.textContent === 'source_ref');
                    if (!row) return null;
                    try {
                        const source = JSON.parse(row.querySelector(':scope > code')?.textContent);
                        return {source_type: source.source_type, source_id: source.source_id};
                    } catch (_) { return null; }
                };
                const evidence = body => body
                    ? Array.from(body.querySelectorAll(':scope > .evidence-entry'))
                        .map(evidenceIdentity)
                    : [];
                const checks = {
                    trust_parent: Boolean(frame && trust && details && frame.children.length === 2 &&
                        frame.children[0].matches('h2') && frame.children[1] === trust && trust.parentElement === frame &&
                        trust.children.length === 2 &&
                        trust.children[0].classList.contains('owner-summary') && trust.children[1] === details &&
                        details.children.length === providers.length + 1 && providers.length > 0 &&
                        details.children[0].matches('summary') &&
                        Array.from(details.children).slice(1).every(child => child.matches('section.provider-state'))),
                    provider_identity: providerIdentity === null ||
                        JSON.stringify(identity) === JSON.stringify(providerIdentity),
                    evidence_identity: expectedEvidenceIdentity === null ||
                        JSON.stringify(evidence(document.querySelector('[data-testid="overview-now"] > article.card > .body'))) ===
                        JSON.stringify(expectedEvidenceIdentity),
                    matrix_parent: Array.from(document.querySelectorAll('[data-testid="overview-trust-matrix"] .matrix'))
                        .every(matrix => matrix.parentElement === details),
                };
                return {ok: Object.values(checks).every(Boolean), checks, identity};
            }""",
            {
                "providerIdentity": expected_provider_identity,
                "expectedEvidenceIdentity": expected_evidence_identity,
            },
        )
        assert provider_inventory["ok"], (
            "Only the admitted navigation and disclosures are keyboard interactive: "
            + repr(provider_inventory["checks"])
        )
        provider_identity = provider_inventory["identity"]
        assert page.evaluate(
            """() => {
                const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
                const trustSummary = trust && trust.querySelector(':scope > details.technical-disclosure');
                const card = document.querySelector('[data-testid="overview-now"] > article.card');
                const body = card && card.querySelector(':scope > .body');
                const subject = body && body.querySelector(':scope > details.technical-disclosure');
                const evidence = body && body.querySelector(':scope > .evidence-entry');
                const evidenceDetails = evidence && evidence.querySelector(':scope > details.technical-disclosure');
                const link = card && card.querySelector(':scope > a[data-testid="overview-focus-link"]');
                const controlChildren = body
                    ? Array.from(body.children).filter(child =>
                        child.matches('details.technical-disclosure,.evidence-entry'))
                    : [];
                const rowShape = details => details && Array.from(details.children).map(child =>
                    child.matches('summary') ? 'summary' :
                    child.classList.contains('matrix') ? 'matrix' :
                    child.matches('ul.rungs') ? 'rungs' : child.tagName.toLowerCase());
                const rowValue = (details, key) => {
                    const row = details && Array.from(details.querySelectorAll(':scope > ul.rungs > li'))
                        .find(item => item.querySelector(':scope > b')?.textContent === key);
                    return row ? row.querySelector(':scope > code')?.textContent : null;
                };
                return Boolean(trust && trustSummary && trustSummary.children.length >= 2 &&
                    trustSummary.children[0].matches('summary') &&
                    Array.from(trustSummary.children).slice(1).every(child => child.matches('section.provider-state')) &&
                    trust.children.length === 2 && trust.children[0].classList.contains('owner-summary') &&
                    trust.children[1] === trustSummary &&
                    card && body && subject && evidence && evidenceDetails && link) &&
                    card.children[2] === body && card.lastElementChild === link &&
                    link.parentElement === card && link.matches('a[data-testid="overview-focus-link"]') &&
                    controlChildren.length === 5 && controlChildren[0] === subject &&
                    controlChildren.slice(1).every(child => child.classList.contains('evidence-entry')) &&
                    controlChildren[1] === evidence && evidence.parentElement === body &&
                    body.firstElementChild?.classList.contains('owner-summary') &&
                    Array.from(body.children).indexOf(body.firstElementChild) < Array.from(body.children).indexOf(subject) &&
                    Array.from(evidence.children).length === 2 && evidence.children[0].classList.contains('owner-summary') &&
                    evidence.children[1] === evidenceDetails && rowShape(subject).join(',') === 'summary,rungs' &&
                    rowShape(evidenceDetails).join(',') === 'summary,matrix,rungs' &&
                    rowValue(subject, 'source_id') === 'github:example/fixture#501' &&
                    (() => { try { return JSON.parse(rowValue(evidenceDetails, 'source_ref')).source_id === 'cockpit:working:github:example/fixture#501'; } catch (_) { return false; } })();
            }"""
        ), "Only the admitted navigation and disclosures are keyboard interactive"
    else:
        expected_entries = [
            {"section": testid, "entries": identities}
            for testid, identities in EXPECTED_FOCUS_ENTRY_IDENTITIES.items()
        ]
        actual_entries = page.evaluate(
            """sectionSpecs => sectionSpecs.map(({section, entries}) => {
                const root = document.querySelector(`[data-testid="${section}"]`);
                const content = root && root.querySelector(':scope > div');
                if (!root || !content || root.children.length !== 2 || root.children[0].tagName !== 'H2') {
                    return {section, invalid: 'section-shape'};
                }
                if (entries.length === 0) {
                    return {
                        section,
                        entries: content.children.length === 1 && content.children[0].classList.contains('empty') ? [] : null,
                    };
                }
                const actual = Array.from(content.children).map(entry => {
                    if (!entry.classList.contains('focus-entry') || entry.children.length !== 2 ||
                        !entry.children[0].classList.contains('owner-summary') ||
                        !entry.children[1].matches('details.technical-disclosure')) {
                        return {invalid: 'entry-shape'};
                    }
                    const details = entry.children[1];
                    if (details.children.length !== 2 || !details.children[0].matches('summary') ||
                        !details.children[1].matches('ul.rungs')) {
                        return {invalid: 'details-shape'};
                    }
                    const rows = {};
                    Array.from(details.querySelectorAll(':scope > ul.rungs > li')).forEach(row => {
                        const key = row.querySelector(':scope > b')?.textContent;
                        const value = row.querySelector(':scope > code')?.textContent;
                        if (key) rows[key] = value;
                    });
                    const key = ['claim_id', 'kind', 'summary', 'legality', 'availability']
                        .find(candidate => Object.prototype.hasOwnProperty.call(rows, candidate));
                    let source = null;
                    if (rows.source_ref) {
                        try { source = JSON.parse(rows.source_ref); } catch (_) { return {invalid: 'source-ref'}; }
                    }
                    return {
                        key,
                        value: key ? rows[key] : null,
                        source_id: source?.source_id ?? null,
                        locator: source?.locator ?? null,
                    };
                });
                return {section, entries: actual};
            })""",
            expected_entries,
        )
        assert actual_entries == expected_entries, "Only the admitted navigation and disclosures are keyboard interactive"
    assert page.evaluate(
        """inventory => {
            const identity = entry => {
                const details = entry.querySelector(':scope > details.technical-disclosure');
                if (!details || details.children.length !== 2 || !details.children[0].matches('summary') ||
                    !details.children[1].matches('ul.rungs')) return null;
                const rows = {};
                Array.from(details.querySelectorAll(':scope > ul.rungs > li')).forEach(row => {
                    const key = row.querySelector(':scope > b')?.textContent;
                    const value = row.querySelector(':scope > code')?.textContent;
                    if (key) rows[key] = value;
                });
                const key = ['claim_id', 'kind', 'summary', 'legality', 'availability']
                    .find(candidate => Object.prototype.hasOwnProperty.call(rows, candidate));
                let source = null;
                if (rows.source_ref) {
                    try { source = JSON.parse(rows.source_ref); } catch (_) { return null; }
                }
                return {
                    key,
                    value: key ? rows[key] : null,
                    source_id: source?.source_id ?? null,
                    locator: source?.locator ?? null,
                };
            };
            const expectedEntry = (section, spec) => {
                const root = document.querySelector(`[data-testid="${section}"]`);
                const content = root && root.querySelector(':scope > div');
                if (!content) return null;
                return Array.from(content.children).find(entry =>
                    JSON.stringify(identity(entry)) === JSON.stringify(spec)
                );
            };
            const expected = inventory.surface === 'overview'
                ? (() => {
                    const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
                    const card = document.querySelector('[data-testid="overview-now"] > article.card');
                    const body = card && card.querySelector(':scope > .body');
                    const evidenceSummaries = body
                        ? Array.from(body.querySelectorAll(':scope > .evidence-entry > details.technical-disclosure > summary'))
                        : [];
                    return [
                        trust && trust.querySelector(':scope > details.technical-disclosure > summary'),
                        body && body.querySelector(':scope > details.technical-disclosure > summary'),
                        ...evidenceSummaries,
                        card && card.querySelector(':scope > a[data-testid="overview-focus-link"]'),
                    ];
                })()
                : [
                    document.querySelector('[data-testid="overview-return"]'),
                    ...inventory.sections.flatMap(({section, entries}) => entries.map(spec => {
                        const entry = expectedEntry(section, spec);
                        return entry && entry.querySelector(':scope > details.technical-disclosure > summary');
                    })),
                ];
            if (expected.some(element => !element)) return false;
            const visible = element => element.getClientRects().length &&
                getComputedStyle(element).visibility !== 'hidden' && !element.closest('[inert]');
            const interactiveRoles = new Set([
                'button', 'checkbox', 'combobox', 'gridcell', 'link', 'listbox', 'menuitem',
                'menuitemcheckbox', 'menuitemradio', 'option', 'radio', 'scrollbar', 'searchbox',
                'slider', 'spinbutton', 'switch', 'tab', 'textbox', 'treeitem'
            ]);
            const interactive = element => visible(element) && (
                element.tabIndex >= 0 || element.isContentEditable ||
                element.matches('a[href],area[href],button,input,select,textarea,summary,audio[controls],video[controls]') ||
                interactiveRoles.has(element.getAttribute('role'))
            );
            const actual = Array.from(document.querySelectorAll('*')).filter(interactive);
            if (inventory.surface === 'focus') {
                const shell = document.querySelector('[data-testid="devui-focus"]');
                const claim = shell && shell.querySelector(':scope > .claim');
                const grid = shell && shell.querySelector(':scope > .focus-grid');
                const returnLink = document.querySelector('[data-testid="overview-return"]');
                if (!shell || !claim || !grid || !returnLink || returnLink.parentElement !== claim ||
                    claim.lastElementChild !== returnLink ||
                    Array.from(shell.children).indexOf(claim) >= Array.from(shell.children).indexOf(grid)) return false;
            }
            return actual.length === expected.length && actual.every((element, index) => element === expected[index]) &&
                expected.every(summary => !summary.matches('summary') ||
                    (summary.dataset.testid === 'devui-technical-disclosure' &&
                     summary.parentElement.firstElementChild === summary));
        }""",
        {
            "surface": surface,
            "sections": [
                {"section": testid, "entries": identities}
                for testid, identities in EXPECTED_FOCUS_ENTRY_IDENTITIES.items()
            ],
        },
    ), "Only the admitted navigation and disclosures are keyboard interactive"
    assert page.evaluate(
        """() => Array.from(document.querySelectorAll('details.technical-disclosure > summary')).every(summary =>
            !summary.isContentEditable && !summary.hasAttribute('role') &&
            !summary.hasAttribute('tabindex') &&
            !summary.querySelector('button,a,input,textarea,select,[tabindex],[contenteditable]'))"""
    ), "Only the admitted navigation and disclosures are keyboard interactive"
    assert page.evaluate(
        """expected => Array.from(document.querySelectorAll('*')).filter(el =>
            (el.tabIndex >= 0 || el.isContentEditable) &&
            !el.matches(':disabled') && !el.closest('[inert]') &&
            el.getClientRects().length && getComputedStyle(el).visibility === 'visible'
        ).every(el => el === expected || el.matches('details.technical-disclosure > summary'))""",
        link.element_handle(),
    ), "Only the admitted navigation and disclosures are keyboard interactive"
    page.bring_to_front()
    summaries = page.locator("details.technical-disclosure > summary").all()
    for summary in summaries:
        summary.focus()
        assert summary.evaluate("el => document.activeElement === el")
        page.keyboard.press("Enter")
        assert summary.evaluate("el => el.parentElement.open") is True
        page.keyboard.press("Space")
        assert summary.evaluate("el => el.parentElement.open") is False
    page.mouse.click(2, 2)
    assert page.evaluate("document.activeElement === document.body"), "Browser did not reset focus to body"
    expected_focus = [link]
    if surface == "overview":
        card = page.locator('[data-testid="overview-now"] > article.card')
        expected_focus = [
            page.locator('[data-testid="overview-trust-matrix"] details.technical-disclosure > summary'),
            card.locator(':scope > .body > details.technical-disclosure > summary'),
            *card.locator(':scope > .body > .evidence-entry > details.technical-disclosure > summary').all(),
            card.locator(':scope > a[data-testid="overview-focus-link"]'),
        ]
    else:
        expected_focus = [page.locator('[data-testid="overview-return"]')]
        for testid, identities in EXPECTED_FOCUS_ENTRY_IDENTITIES.items():
            section = page.locator(f'[data-testid="{testid}"]')
            expected_focus.extend(
                section.locator(':scope > div > .focus-entry > details.technical-disclosure > summary').all()
            )
    for expected in expected_focus:
        page.keyboard.press("Tab")
        assert page.evaluate(
            """expected => document.activeElement === expected""", expected.element_handle()
        ), "Unexpected keyboard focus outside admitted navigation and disclosures"
    if navigate:
        link.focus()
        assert page.evaluate("expected => document.activeElement === expected", link.element_handle())
        page.keyboard.press("Enter")
        page.wait_for_url(ORIGIN + destination)
        _loaded(page, "focus" if surface == "overview" else "overview")
    return provider_identity


@pytest.mark.parametrize("surface,path", [("overview", "/devui/overview"), ("focus", FOCUS)])
@pytest.mark.parametrize(
    "action",
    [
        "button",
        "link",
        "tabindex",
        "editable",
        "disclosure",
        "disclosure_misplaced",
        "body_after_focus",
        "summary_editable",
        "trust_additional",
        "trust_substituted",
        "trust_moved",
        "trust_duplicated",
        "trust_editable",
        "trust_lookalike",
        "trust_provider_substituted",
        "trust_provider_reversed",
        "trust_provider_dropped",
        "trust_matrix_moved",
        "evidence_after_body",
        "navigation_nested_in_evidence",
        "governing_entries_swapped",
        "details_before_owner_summary",
        "details_before_focus_entry",
        "details_prepended_into_other_entry",
        "return_outside_claim",
    ],
)
def test_managed_keyboard_proof_rejects_unexpected_interactive_action(
    managed_sources, monkeypatch, surface, path, action  # noqa: F811 - imported pytest fixture
):
    with (
        _server(managed_sources, monkeypatch),
        _browser() as (page, context, _browser_instance, external, requests, errors, console),
    ):
        page.goto(ORIGIN + path)
        _loaded(page, surface)
        expected_provider_identity = _keyboard_navigation(page, surface, navigate=False)
        # Fault injection into the actual production-served DOM, not a substitute page.
        page.evaluate("""kind => {
            const card = document.querySelector('[data-testid="overview-now"] > article.card');
            const focusSection = document.querySelector('[data-testid="focus-governing-sources"] > div');
            if (kind === 'disclosure_misplaced') {
                const details = Array.from(document.querySelectorAll('details.technical-disclosure'));
                details.forEach(item => document.querySelector('main').append(item));
                return;
            }
            if (kind === 'body_after_focus') {
                const card = document.querySelector('[data-testid="overview-now"] article');
                if (card) {
                    card.append(card.querySelector('.body'));
                } else {
                    const grid = document.querySelector('.focus-grid');
                    document.querySelector('[data-testid="overview-return"]').closest('.claim').before(grid);
                }
                return;
            }
            if (kind === 'evidence_after_body') {
                if (card) {
                    const evidence = card.querySelector(':scope > .body > .evidence-entry');
                    card.insertBefore(evidence, card.querySelector(':scope > a[data-testid="overview-focus-link"]'));
                } else {
                    const first = focusSection.querySelector(':scope > .focus-entry');
                    focusSection.append(first);
                }
                return;
            }
            if (kind === 'navigation_nested_in_evidence') {
                if (card) {
                    const evidence = card.querySelector(':scope > .body > .evidence-entry');
                    evidence.append(card.querySelector(':scope > a[data-testid="overview-focus-link"]'));
                } else {
                    const entry = focusSection.querySelector(':scope > .focus-entry');
                    entry.append(document.querySelector('[data-testid="overview-return"]'));
                }
                return;
            }
            if (kind === 'governing_entries_swapped') {
                if (focusSection) {
                    const entries = focusSection.querySelectorAll(':scope > .focus-entry');
                    focusSection.insertBefore(entries[1], entries[0]);
                } else if (card) {
                    const body = card.querySelector(':scope > .body');
                    const subject = body.querySelector(':scope > details.technical-disclosure');
                    const evidence = body.querySelector(':scope > .evidence-entry');
                    body.insertBefore(evidence, subject);
                }
                return;
            }
            if (kind === 'details_before_owner_summary') {
                if (focusSection) {
                    const entry = focusSection.querySelector(':scope > .focus-entry');
                    entry.insertBefore(entry.querySelector(':scope > details.technical-disclosure'), entry.firstElementChild);
                } else if (card) {
                    const body = card.querySelector(':scope > .body');
                    body.insertBefore(body.querySelector(':scope > details.technical-disclosure'), body.firstElementChild);
                }
                return;
            }
            if (kind === 'details_before_focus_entry') {
                if (focusSection) {
                    const entry = focusSection.querySelector(':scope > .focus-entry');
                    focusSection.insertBefore(entry.querySelector(':scope > details.technical-disclosure'), entry);
                } else if (card) {
                    const body = card.querySelector(':scope > .body');
                    body.insertBefore(body.querySelector(':scope > details.technical-disclosure'), body.firstElementChild);
                }
                return;
            }
            if (kind === 'details_prepended_into_other_entry') {
                if (focusSection) {
                    const entries = focusSection.querySelectorAll(':scope > .focus-entry');
                    entries[1].prepend(entries[0].querySelector(':scope > details.technical-disclosure'));
                } else if (card) {
                    const body = card.querySelector(':scope > .body');
                    const subject = body.querySelector(':scope > details.technical-disclosure');
                    body.querySelector(':scope > .evidence-entry').prepend(subject);
                }
                return;
            }
            if (kind === 'return_outside_claim') {
                if (focusSection) {
                    const returnLink = document.querySelector('[data-testid="overview-return"]');
                    const claim = returnLink && returnLink.closest('.claim');
                    if (returnLink && claim) claim.parentElement.insertBefore(returnLink, claim);
                } else if (card) {
                    const link = card.querySelector(':scope > a[data-testid="overview-focus-link"]');
                    if (link) card.parentElement.insertBefore(link, card);
                }
                return;
            }
            if (kind === 'summary_editable') {
                const target = card
                    ? card.querySelector(':scope > .body > details.technical-disclosure > summary')
                    : document.querySelector('[data-testid="focus-governing-sources"] details.technical-disclosure > summary');
                if (target) target.contentEditable = 'true';
                return;
            }
            if (kind.startsWith('trust_')) {
                const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
                const details = trust && trust.querySelector(':scope > details.technical-disclosure');
                if (!trust || !details) {
                    const existing = document.querySelector('details.technical-disclosure');
                    if (kind === 'trust_editable' && existing) {
                        existing.querySelector(':scope > summary').contentEditable = 'true';
                    } else if (kind === 'trust_moved' && existing) {
                        document.querySelector('main').append(existing);
                    } else {
                        const unexpected = document.createElement('details');
                        unexpected.className = 'technical-disclosure';
                        const summary = document.createElement('summary');
                        summary.textContent = 'Unexpected trust control';
                        unexpected.append(summary, document.createElement('p'));
                        document.querySelector('main').append(unexpected);
                    }
                    return;
                }
                if (kind === 'trust_additional') {
                    trust.append(details.cloneNode(true));
                } else if (kind === 'trust_substituted') {
                    const replacement = document.createElement('details');
                    replacement.className = 'technical-disclosure';
                    const summary = document.createElement('summary');
                    summary.textContent = 'Inspect trust frame';
                    replacement.append(summary, document.createElement('p'));
                    trust.replaceChild(replacement, details);
                } else if (kind === 'trust_moved') {
                    document.querySelector('main').append(details);
                } else if (kind === 'trust_duplicated') {
                    trust.append(details.cloneNode(true));
                } else if (kind === 'trust_editable') {
                    details.querySelector(':scope > summary').contentEditable = 'true';
                } else if (kind === 'trust_lookalike') {
                    const lookalike = document.createElement('div');
                    lookalike.className = 'technical-disclosure';
                    lookalike.textContent = 'Inspect trust frame';
                    trust.append(lookalike);
                } else if (kind === 'trust_provider_substituted') {
                    const providers = details.querySelectorAll(':scope > section.provider-state');
                    if (providers[0]) {
                        const replacement = providers[0].cloneNode(true);
                        replacement.dataset.providerRole = 'substituted-provider';
                        const row = Array.from(replacement.querySelectorAll(':scope > ul.rungs > li'))
                            .find(item => item.querySelector(':scope > b')?.textContent === 'provider');
                        if (row) row.querySelector(':scope > code').textContent = 'substituted_provider';
                        details.replaceChild(replacement, providers[0]);
                    }
                } else if (kind === 'trust_provider_reversed') {
                    const providers = details.querySelectorAll(':scope > section.provider-state');
                    if (providers.length > 1) details.insertBefore(providers[1], providers[0]);
                } else if (kind === 'trust_provider_dropped') {
                    const providers = details.querySelectorAll(':scope > section.provider-state');
                    if (providers.length > 1) providers[providers.length - 1].remove();
                } else if (kind === 'trust_matrix_moved') {
                    const frame = document.querySelector('[data-testid="overview-trust-frame"]');
                    frame.before(trust);
                }
                return;
            }
            const el = document.createElement(kind === 'disclosure' ? 'details' :
                kind === 'button' ? 'button' : kind === 'link' ? 'a' : 'div');
            el.textContent = 'Unexpected action';
            if (kind === 'disclosure') {
                el.className = 'technical-disclosure';
                const summary = document.createElement('summary');
                summary.textContent = 'Unreviewed injected disclosure';
                el.replaceChildren(summary, document.createElement('p'));
            }
            if (kind === 'link') el.href = '/unexpected-action';
            if (kind === 'tabindex') { el.tabIndex = 0; el.setAttribute('role', 'button'); }
            if (kind === 'editable') el.contentEditable = 'true';
            document.querySelector('main').append(el);
        }""", action)
        with pytest.raises(AssertionError, match="Only the admitted navigation"):
            _keyboard_navigation(
                page,
                surface,
                navigate=False,
                expected_provider_identity=expected_provider_identity,
            )
        assert page.url == ORIGIN + path
        assert all(method == "GET" for method, _ in requests)
        assert not external and not errors and not console
        _no_persistence(page, context)


def test_standalone_overview_focus_return_preserves_subject_and_candidate(
    managed_sources,  # noqa: F811 - imported pytest fixture
    monkeypatch
):
    source = managed_sources
    row = source.tasks[0]
    stamp = row["updated_at"]
    row["state"] = row["payload"]["status"] = "claimed"
    row["payload"]["sync_state"] = {
        "labels": ["agent:blocked", "action:wait-dependency"],
        "state": "open",
        "last_pull_at": "2026-08-01T11:58:00+00:00",
        "comments": [
            {
                "body": "\n".join(
                    [
                        "receipt: blocker_action.v1",
                        "action: action:wait-dependency",
                        "owner: builder",
                        "next_action: inspect dependency 900",
                        "unblocks_when: dependency 900 is delivered",
                        "dependency_refs: []",
                        "review_at: null",
                        "last_verified_at: 2026-08-01T11:58:00Z",
                    ]
                )
            }
        ],
    }
    row["lease"] = {
        "repository": "example/fixture",
        "resource_id": "task-1",
        "holder": "fixture-registered-holder",
        "fencing_token": 1,
        "expires_at": "2099-09-13T10:00:00+00:00",
        "lease_kind": "task",
        "updated_at": stamp,
    }
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, _browser_instance, external, requests, errors, console),
    ):
        first = page.goto(ORIGIN + "/devui/overview")
        _loaded(page, "overview")
        overview_reads = len(source.calls)
        overview_text = page.locator('[data-testid="overview-now"]').inner_text()
        assert "Explicit docs-linked capability" in overview_text
        assert "fixture-registered-holder" in overview_text
        assert "claimed" in overview_text.lower()
        assert "inspect dependency 900" in overview_text
        assert "does not authorize execution" in overview_text
        assert "unknown" in overview_text.lower()
        link = page.get_by_role("link", name="Open Focus")
        assert link.get_attribute("href") == FOCUS
        with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as read:
            link.click()
        _loaded(page, "focus")
        payload = read.value.json()
        focus_text = page.locator('[data-testid="devui-focus"]').inner_text()
        assert "Fixture owner intent." in focus_text
        assert "Fixture source scope." in focus_text
        assert "Preserve fixture declarations." in focus_text
        assert "tests/fixture.py::test_declaration" in focus_text
        assert payload["subject"]["stable_id"] == MANAGED_SUBJECT
        assert payload["subject"]["authority_ref"]["locator"] == "https://github.com/Example/Fixture/issues/501"
        assert (
            page.locator('[data-testid="focus-subject"]').get_attribute("data-subject")
            == MANAGED_SUBJECT
        )
        assert (
            page.locator('[data-testid="devui-focus"]').get_attribute("data-server-state")
            == payload["state"]
        )
        assert (
            source.calls and len(source.calls) == overview_reads
        ), "Focus must not read or join root providers"
        for key in (
            "x-pkm-runtime-git-sha",
            "x-devui-image-digest",
            "x-devui-config-fingerprint",
            "x-devui-asset-inventory",
        ):
            assert first.headers[key] == read.value.headers[key]
        assert payload["receipts"] == payload["execution_observations"] == []
        _capture(page, "managed-focus")
        row["payload"]["issue_number"] = 502
        row["payload"]["title"] = "Unlinked fixture work"
        with page.expect_response(ORIGIN + "/api/devui/overview") as returned:
            page.get_by_role("link", name="Return to Overview").click()
        _loaded(page, "overview")
        returned_text = page.locator('[data-testid="overview-now"]').inner_text()
        assert "Unlinked fixture work" in returned_text
        assert "Explicit docs-linked capability" not in returned_text
        assert "Capability is unknown" in returned_text
        assert "fixture-registered-holder" in returned_text
        assert "claimed" in returned_text.lower()
        assert "inspect dependency 900" in returned_text
        assert "does not authorize execution" in returned_text
        returned_candidate = returned.value.json()["now"][0]
        returned_capability = next(
            entry
            for entry in returned_candidate["evidence"]
            if entry["source_ref"]["source_type"] == "docs-frontmatter"
        )
        assert returned_candidate["reason"] == "claimed · claimed by fixture-registered-holder"
        assert returned_capability["claim"] is None
        assert returned_capability["freshness"] == "fresh"
        assert returned_capability["linkage"] == "unlinked"
        assert any(
            "Capability is unknown" in limitation
            for limitation in returned_candidate["limitations"]
        )
        assert len(source.calls) > overview_reads
        for path in source.root.rglob("*"):
            if path.is_file():
                os.utime(path, (1, 1))
        page.reload()
        _loaded(page, "overview")
        withdrawn_text = page.locator('[data-testid="overview-now"]').inner_text()
        assert "Unlinked fixture work" in withdrawn_text
        assert "Explicit docs-linked capability" not in withdrawn_text
        assert "unknown" in withdrawn_text.lower()
        assert "fixture-registered-holder" in withdrawn_text
        assert "claimed" in withdrawn_text.lower()
        assert "does not authorize execution" in withdrawn_text
        assert sum(url == ORIGIN + "/api/devui/overview" for _, url in requests) == 3
        assert all(method == "GET" for method, _ in requests)
        assert not external and not errors and not console
        _no_persistence(page, context)


def test_managed_journey_hostile_accessibility_and_no_effect_matrix(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    source = managed_sources
    source.tasks[0]["payload"]["title"] = "<img src=x onerror=alert(1)> Managed work"
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, browser, external, requests, errors, console),
    ):
        for surface, path in (("overview", "/devui/overview"), ("focus", FOCUS)):
            response = page.goto(ORIGIN + path)
            _loaded(page, surface)
            assert response.headers["cache-control"] == "no-store"
            assert "default-src 'none'" in response.headers["content-security-policy"]
            assert page.locator("img").count() == 0
            assert "<img" in page.locator("body").inner_text()
            if surface == "overview":
                assert "Explicit docs-linked capability" in page.locator('[data-testid="overview-now"]').inner_text()
            assert page.get_by_role("main").get_attribute("aria-labelledby") == surface + "-heading"
            assert page.get_by_role("heading", level=1).count() == 1
            if surface == "focus":
                _assert_focus_technical_axis_disclosure(page)
            _keyboard_navigation(page, surface)
            page.goto(ORIGIN + path)
            _loaded(page, surface)
            assert 'heading "' in page.locator("body").aria_snapshot()
            for name, width, height, scale in (
                ("desktop", 1280, 720, 1),
                ("narrow", 375, 812, 1),
                ("zoom_200", 640, 720, 2),
            ):
                page.set_viewport_size({"width": width, "height": height})
                cdp = context.new_cdp_session(page)
                cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": scale})
                assert page.evaluate("window.visualViewport.scale") == scale
                _capture(page, surface + "-" + name)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                ), page.evaluate(
                    "({width:innerWidth, client:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth, elements:Array.from(document.querySelectorAll('*')).filter(x => x.scrollWidth > x.clientWidth && !x.children.length).map(x => [x.tagName, x.className, x.textContent.slice(0, 70), x.getBoundingClientRect().right]).slice(0, 12)})"
                )
                cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
                cdp.detach()
            page.emulate_media(media="print")
            assert page.get_by_role("main").is_visible()
            _capture(page, surface + "-print")
            page.emulate_media(media="screen")
            _no_persistence(page, context)
            prior_calls = list(source.calls)
            prior_gh = source.gh_calls.read_text() if source.gh_calls.exists() else ""
            off = browser.new_context(java_script_enabled=False)
            try:
                off_page = off.new_page()
                off_page.goto(ORIGIN + path)
                assert "needs JavaScript" in off_page.get_by_role("alert").inner_text()
                _capture(off_page, surface + "-javascript-off")
                assert source.calls == prior_calls
                assert (source.gh_calls.read_text() if source.gh_calls.exists() else "") == prior_gh
            finally:
                off.close()
        assert all(method == "GET" for method, _ in requests)
        assert all(method == "GET" for method, _ in source.http_calls)
        assert not external and not errors and not console


def test_managed_journey_preserves_focus_failures_and_fresh_return(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    source = managed_sources
    with (
        _server(source, monkeypatch),
        _browser() as (page, context, _browser_instance, external, requests, errors, console),
    ):
        for failure in (
            "refusal",
            "timeout",
            "404",
            "http_status",
            "malformed",
            "request_failure",
            "page_error",
            "console_error",
        ):
            before = len(source.calls)
            if failure == "refusal":
                source.gh_mode.write_text("unavailable")
            else:

                def fail(route):
                    mode = failure
                    if mode in {"timeout", "request_failure"}:
                        route.abort("timedout" if mode == "timeout" else "failed")
                    elif mode == "404":
                        route.fulfill(status=404, json={"detail": "missing"})
                    elif mode == "http_status":
                        route.fulfill(status=503, json={"detail": "unavailable"})
                    elif mode == "malformed":
                        route.fulfill(status=200, content_type="application/json", body="{broken")
                    else:
                        route.continue_()

                page.route("**/api/devui/focus?*", fail)
            page.goto(ORIGIN + FOCUS)
            if failure in {"page_error", "console_error"}:
                _loaded(page, "focus")
                if failure == "page_error":
                    page.evaluate(
                        "setTimeout(() => { throw new Error('fixture page failure'); }, 0)"
                    )
                    page.wait_for_timeout(50)
                    assert errors == ["fixture page failure"]
                else:
                    page.evaluate("console.error('fixture console failure')")
                    assert any("fixture console failure" in error for error in console)
            else:
                page.locator('[data-testid="focus-load-state"][data-state="error"]').wait_for()
                assert (
                    page.locator('[data-testid="devui-focus"]').get_attribute("data-server-state")
                    == "read_error"
                )
                assert page.get_by_role("alert").is_visible()
            assert len(source.calls) == before
            _capture(page, "focus-failure-" + failure)
            page.unroute("**/api/devui/focus?*")
            source.gh_mode.write_text("canonical_case")
            page.get_by_role("link", name="Return to Overview").click()
            _loaded(page, "overview")
            assert len(source.calls) > before
            _no_persistence(page, context)
        assert len([url for _, url in requests if "/api/devui/focus?" in url]) == 8
        assert all(method == "GET" for method, _ in requests)
        assert not external
        assert errors == ["fixture page failure"]
        assert set(url.split("?", 1)[0].removeprefix(ORIGIN) for _, url in requests) <= {
            "/devui/overview",
            "/devui/focus",
            "/devui/assets/devui.css",
            "/devui/assets/overview.js",
            "/devui/assets/focus.js",
            "/api/devui/overview",
            "/api/devui/focus",
        }
        source.mode = "unavailable"
        with page.expect_response(ORIGIN + "/api/devui/overview") as response:
            page.reload()
        _loaded(page, "overview")
        states = response.value.json()["trust_frame"]["provider_states"]
        assert "refused" in json.dumps(states)
        assert "refused" in page.locator('[data-testid="overview-trust-frame"]').inner_text()
def test_first_read_issue_journey_precedes_observation_without_effects(managed_sources, monkeypatch):  # noqa: F811 - imported pytest fixture
    from tests.builderops.test_devui_runtime import _install_first_read_observation

    source = managed_sources
    folder = Path(source.environment["DEVUI_VM102_RECEIPT_DIR"]) / "first-read"
    assert not folder.exists()
    with _server(source, monkeypatch), _browser() as (page, context, _, external, requests, errors, console):
        _install_first_read_observation(source, monkeypatch, retain=False)
        with page.expect_response(ORIGIN + "/api/devui/overview") as first:
            page.goto(ORIGIN + "/devui/overview")
        _loaded(page, "overview")
        assert first.value.headers["x-devui-first-read-observation"] == "refused"
        reads = len(source.calls)
        assert page.get_by_role("link", name="Open Focus").get_attribute("href") == FOCUS
        with page.expect_response(lambda r: "/api/devui/focus?" in r.url) as focus:
            page.get_by_role("link", name="Open Focus").click()
        _loaded(page, "focus")
        assert focus.value.json()["subject"]["stable_id"] == MANAGED_SUBJECT
        assert focus.value.headers["x-pkm-runtime-git-sha"] == first.value.headers["x-pkm-runtime-git-sha"]
        assert focus.value.headers["x-devui-first-read-observation"] == "refused"
        _capture(page, "first-read-before-observation")
        with page.expect_response(ORIGIN + "/api/devui/overview") as returned:
            page.get_by_role("link", name="Return to Overview").click()
        _loaded(page, "overview")
        assert len(source.calls) > reads
        providers = {item["role"]: item for item in returned.value.json()["trust_frame"]["provider_states"]}
        assert providers["first_read_observation"]["status"] == providers["vm102_evidence"]["status"] == "refused"
        assert not folder.exists()
        assert not external and not errors and not console
        assert all(method == "GET" for method, _ in requests + source.http_calls)
        assert sum(url == ORIGIN + "/api/devui/overview" for _, url in requests) == 2
        _no_persistence(page, context)
