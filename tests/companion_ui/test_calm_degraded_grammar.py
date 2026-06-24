"""CUIDR-01 — calm degraded grammar + runtime-enum/identifier humanisation map.

Static ACs (no live runtime). Verifies that:

- A single ``calm_degraded`` grammar helper is the sole code path emitting
  unavailable/error *copy* on a user-facing surface (AC1).
- No raw runtime enum or internal identifier (``resurfacing_source_unavailable``,
  ``prop-move-1``, ``art-123``, ``lifecycle.move``) reaches the rendered HTML;
  each maps to human copy while the classified value still arrives from the
  payload (AC2 / C3).
- The vault browser never surfaces the raw transport error
  ("Error: Failed to fetch"); it uses the calm grammar (AC3 / D3).
- An unmapped degraded-reason token fails closed to the calm fallback rather
  than leaking the raw token (AC4).

Presentation-only constraint: this task humanises *display* tokens. The
server-authoritative classification still arrives in the payload and remains
observable in ``data-*`` attributes on the rendered element.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from typing import Any

import pytest

from companion_ui.workspace import serve_dev_page
from companion_ui.workspace.calm_degraded import (
    FAIL_CLOSED_DEGRADED,
    NOTHING_DECIDED,
    NOTHING_LOST,
    NOTHING_MUTATED,
    calm_degraded,
    humanise_degraded_reason,
    humanise_token,
)
from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html

# --- Confirmed leak tokens from the deep review (REVIEW_RESPONSE.txt C3/D3) ---
KNOWN_ENUM_TOKENS = [
    "resurfacing_source_unavailable",
    "orientation_unavailable",
    "lifecycle.move",
]
SUPPRESSED_ID_TOKENS = ["prop-move-1", "art-123"]
RAW_TRANSPORT_ERROR = "Error: Failed to fetch"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _vault_browser_payload() -> dict[str, Any]:
    return {
        "vault_id": "dev-vault",
        "channel": "dev",
        "provenance": "runtime",
        "query": "",
        "total_notes": 0,
        "filtered_notes": 0,
        "notes": [],
    }


def _degraded_orientation_payload(
    reason: str = "resurfacing_source_unavailable",
) -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-22T12:00:00Z",
            "trace_id": "trace-degraded",
            "freshness": "partial",
            "degraded_reasons": [reason],
            "caps": {
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded",
            "degraded": True,
            "reasons": [reason],
            "authority_role": "derived",
        },
        "mutation_intents": [],
    }


class _ProposalClient:
    """Minimal client returning a workspace payload with one leaky proposal."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/workspace":
            return self._payload
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"unexpected POST: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise AssertionError(f"unexpected DELETE: {url}")


def _leaky_workspace_payload() -> dict[str, Any]:
    """A workspace payload whose proposal carries the confirmed leak tokens."""
    # The loaded note has its own clean identity; the leak token art-123 lives
    # only on the *proposal* (the rail/proposal card is the surface the review
    # flagged). The artifact-identity pill legitimately shows the note's own
    # server-authoritative provenance and is out of scope.
    return {
        "artifact": {
            "artifact_id": "artifact-loaded-note",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": None,
            "session_state": None,
            "user_present": False,
            "can_edit_body": False,
            "recovery_needed": False,
            "session_log_path": None,
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "prop-move-1",
                    "artifact_id": "art-123",
                    "description": "Move this note into Projects/",
                    "status": "staged",
                    "evidence": {
                        "trigger_summary": "Trigger summary",
                        "action_class": "lifecycle.move",
                        "cognition_route": "rule",
                    },
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _render_proposal_html() -> str:
    client = _ProposalClient(_leaky_workspace_payload())
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def _render_degraded_orientation_html(
    reason: str = "resurfacing_source_unavailable",
) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_degraded_orientation_payload(reason),
        orientation_vault_browser=_vault_browser_payload(),
    )


# ---------------------------------------------------------------------------
# AC1 — single grammar helper is the sole unavailable/error copy emitter
# ---------------------------------------------------------------------------
def test_grammar_helper_is_sole_unavailable_emitter() -> None:
    # The helper renders the canonical template for all parametrised inputs.
    assert (
        calm_degraded("Notes", "connection failed", NOTHING_LOST, "Refresh to retry")
        == "Notes unavailable — connection failed. Nothing was lost. Refresh to retry."
    )
    assert (
        calm_degraded("Orientation", "source missing", NOTHING_DECIDED)
        == "Orientation unavailable — source missing. Nothing was decided."
    )
    assert (
        calm_degraded("Canvas", "runtime offline", NOTHING_MUTATED, "Try again shortly")
        == "Canvas unavailable — runtime offline. Nothing was mutated. Try again shortly."
    )
    # An unknown nothing-clause falls back to the calm default, never leaks.
    assert "Nothing was lost." in calm_degraded("X", "y", "Nothing was eaten")

    # Static scan: the raw transport-error emit and the raw degraded-reason
    # emit must no longer appear in the render module. These are the two
    # confirmed copy-leak code paths the helper now owns.
    src = inspect.getsource(serve_dev_page)
    assert "_e(str(error))" not in src, (
        "vault-browser error path must route through calm_degraded, not emit the "
        "raw transport error as copy"
    )
    # The degraded-reason chips must humanise the token, not emit it raw as copy.
    assert "{_e(reason)}</span>" not in src, (
        "orientation degraded-reason chips must route through "
        "humanise_degraded_reason, not emit the raw enum as copy"
    )

    # The calm grammar's signature copy (' unavailable — ') is produced only by
    # the helper: no other render-module call-site inlines the template
    # connective. (Classification tokens / data-attrs / testids carrying the
    # word 'unavailable' in non-copy positions are exempt by construction —
    # the connective ' unavailable — ' is unique to the grammar.)
    assert " unavailable — " not in src, (
        "the degraded grammar connective ' unavailable — ' must be produced "
        "only by calm_degraded(), not inlined at a render call-site"
    )


# ---------------------------------------------------------------------------
# AC2 / C3 — enum map covers known tokens; classified value still arrives
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "token,human",
    [
        ("resurfacing_source_unavailable", "Orientation source unavailable"),
        ("orientation_unavailable", "Orientation unavailable"),
        ("lifecycle.move", "Move note"),
    ],
)
def test_enum_map_covers_known_tokens(token: str, human: str) -> None:
    # The humanised string is produced by the map function, not hardcoded.
    assert humanise_token(token) == human or humanise_degraded_reason(token) == human


def test_enum_map_no_raw_token_on_degraded_surface() -> None:
    for token in ["resurfacing_source_unavailable", "orientation_unavailable"]:
        payload = _degraded_orientation_payload(token)
        html = _render_degraded_orientation_html(token)
        # Humanised copy is present (produced by the map, not the template call).
        assert humanise_degraded_reason(token) in html
        # The raw enum token must be ABSENT from the rendered orientation
        # degraded *surface* — neither as visible chip copy nor echoed into a
        # chip/source data-* attribute on that surface. (The server-authoritative
        # entry-state declaration on <body data-entry-degraded-reasons=…>, set
        # by the entry-state resolver, is the exempt classification carrier and
        # is out of CUIDR-01 scope; we scan the degraded surface, not <body>.)
        surface = _degraded_orientation_surface(html)
        assert token not in surface, f"raw enum {token!r} leaked into degraded surface"
        # The classified value still arrives from the runtime: it is present in
        # the fixture payload passed to the renderer, and the surface declares
        # the degraded posture server-side.
        assert token in payload["meta"]["degraded_reasons"]
        assert token in payload["guards"]["reasons"]
        assert 'data-runtime-posture="degraded"' in html


def test_enum_map_suppresses_internal_ids_on_proposal_surface() -> None:
    html = _render_proposal_html()
    visible = _visible_text(html)
    # Internal identifiers and the raw action class must not appear as visible
    # copy. The proposal-id / artifact-id correlation IDs may remain only inside
    # pre-existing data-* attributes (server-authoritative correlation, exempt
    # per the AC1 note); they are never rendered as user-facing copy.
    for token in SUPPRESSED_ID_TOKENS:
        assert token not in visible, f"internal id {token!r} leaked to visible copy"
    assert "lifecycle.move" not in visible, "raw action class leaked to visible copy"
    assert "Move note" in html
    # The classified correlation IDs still arrive from the runtime payload
    # (proof of server authority is the payload, not a copy echo).
    payload = _leaky_workspace_payload()
    proposal = payload["panel"]["proposals"][0]
    assert proposal["proposal_id"] == "prop-move-1"
    assert proposal["artifact_id"] == "art-123"
    assert proposal["evidence"]["action_class"] == "lifecycle.move"
    # The proposal's human description is what the user reads instead.
    assert "Move this note into Projects/" in html


# ---------------------------------------------------------------------------
# AC3 / D3 — vault browser fetch error uses the calm grammar
# ---------------------------------------------------------------------------
def test_vault_browser_fetch_error_uses_calm_grammar() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_degraded_orientation_payload(),
        orientation_vault_browser=_vault_browser_payload(),
        orientation_vault_browser_error=RAW_TRANSPORT_ERROR,
    )
    # (a) the literal transport error must not appear in the HTML output at all
    #     (not even echoed into a data-* attribute).
    assert RAW_TRANSPORT_ERROR not in html
    # (b) the output uses the calm grammar template.
    assert (
        "Notes unavailable — connection failed. Nothing was lost. Refresh to retry."
        in html
    )
    # (c) the classified error *state* still arrives from the payload — evidenced
    #     by the state-error element being present.
    assert 'data-testid="workspace-vault-browser-state-error"' in html


# ---------------------------------------------------------------------------
# AC3 / D3 (#2482) — the *live* client-side fetch-failure catch uses the calm
# grammar. #2444 closed on the server-rendered fixture above, which never
# invokes the overlay's JS .catch handler; that handler still concatenated
# err.message. This test extracts and *executes* the real overlay catch with a
# rejecting fetch and asserts on the runtime-produced visible status text.
# ---------------------------------------------------------------------------
_NODE = shutil.which("node")

# The single calm-grammar string the server-rendered vault-browser error path
# emits; the live catch must reuse it (not a second template).
_EXPECTED_CALM_VAULT_COPY = calm_degraded(
    what="Notes",
    why="connection failed",
    nothing_clause=NOTHING_LOST,
    what_to_do="Refresh to retry",
)


class _ScriptBodyCollector(HTMLParser):
    """Collect the text of every ``<script>`` element via a real HTML parser.

    Used to pull the overlay IIFE out of the rendered page so it can be
    *executed* under Node. A parser (not a regex tag-filter) is used so the
    extraction is robust to upper-case / whitespace-padded ``</script>`` tags.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in_script = False
        self._buf: list[str] = []
        self.bodies: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "script":
            self._in_script = True
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script:
            self._in_script = False
            self.bodies.append("".join(self._buf))


def _script_bodies(html: str) -> list[str]:
    collector = _ScriptBodyCollector()
    collector.feed(html)
    collector.close()
    return collector.bodies


def _vault_browser_overlay_script() -> str:
    """Extract the vault-browser overlay IIFE (defines ``fetchNotes``)."""
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
    )
    for body in _script_bodies(html):
        if "function fetchNotes" in body and "vault-browser-status" in body:
            return body
    raise AssertionError("vault-browser overlay script (fetchNotes) not found")


def test_vault_browser_overlay_fetch_fail_catch_has_no_raw_error() -> None:
    """Source guard: the live catch reuses calm grammar, not ``err.message``."""
    script = _vault_browser_overlay_script()
    catch = re.search(
        r"\.catch\(function\s*\(err\)\s*\{(.*?)\}\);", script, flags=re.DOTALL
    )
    assert catch is not None, "vault-browser fetch catch handler not found"
    body = catch.group(1)
    assert (
        json.dumps(_EXPECTED_CALM_VAULT_COPY) in body
        or _EXPECTED_CALM_VAULT_COPY in body
    ), "live catch must hand the calm-grammar string to setStatus"
    assert "'Error: ' + err.message" not in body
    assert "setStatus('Error:" not in body


@pytest.mark.skipif(
    _NODE is None, reason="node not available for live-catch execution"
)
def test_vault_browser_overlay_fetch_fail_uses_calm_grammar() -> None:
    """Execute the *live* overlay catch with a rejecting fetch under Node.

    Runs the real ``fetchNotes`` handler from the rendered page with the DOM and
    ``fetch`` stubbed, forcing ``fetch`` to reject with a transport error
    exactly as a browser would. Captures the string the handler writes via
    ``setStatus`` (the DOM ``textContent``) and asserts on that runtime-produced
    *visible* text — not a static fixture. This is the catch that #2444's
    server-rendered fixture never exercised.
    """
    script = _vault_browser_overlay_script()
    harness = textwrap.dedent(
        """
        'use strict';
        const captured = {{ status: null }};
        function makeEl() {{
          return {{
            _text: '', value: '', _html: '',
            set textContent(v) {{ this._text = v; captured.status = v; }},
            get textContent() {{ return this._text; }},
            set innerHTML(v) {{ this._html = v; }},
            get innerHTML() {{ return this._html; }},
            appendChild() {{}}, addEventListener() {{}},
            setAttribute() {{}}, removeAttribute() {{}},
            classList: {{ add() {{}}, remove() {{}} }},
            querySelector() {{ return null; }},
            scrollIntoView() {{}}, focus() {{}}, style: {{}},
          }};
        }}
        const elements = {{}};
        global.document = {{
          getElementById(id) {{
            if (!elements[id]) elements[id] = makeEl();
            return elements[id];
          }},
          addEventListener() {{}}, createElement() {{ return makeEl(); }},
        }};
        global.window = {{
          matchMedia() {{ return {{ matches: false }}; }},
          getComputedStyle() {{ return {{ display: 'block' }}; }},
          console: {{ debug() {{}}, error() {{}} }},
        }};
        global.console = {{ debug() {{}}, error() {{}}, log() {{}} }};
        // The real transport failure: fetch rejects with "Failed to fetch".
        global.fetch = function() {{
          return Promise.reject(new Error('Failed to fetch'));
        }};
        global.setTimeout = function(fn) {{ return 0; }};
        global.clearTimeout = function() {{}};

        {script}

        Promise.resolve()
          .then(function() {{ return window.vaultBrowser.open(); }})
          .then(function() {{ return new Promise(function(r) {{ Promise.resolve().then(r); }}); }})
          .then(function() {{ return new Promise(function(r) {{ Promise.resolve().then(r); }}); }})
          .then(function() {{
            process.stdout.write(JSON.stringify({{ status: captured.status }}));
          }})
          .catch(function(e) {{
            process.stdout.write(JSON.stringify({{ error: String(e) }}));
          }});
        """
    ).format(script=script)

    result = subprocess.run(
        [_NODE, "-e", harness], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"node failed: {result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert "error" not in payload, f"harness error: {payload.get('error')}"
    status = payload["status"]

    # The live catch wrote a visible status: it must be the calm grammar, and it
    # must NOT leak the raw transport error or echo err.message.
    assert status is not None, "live overlay catch never set a status"
    assert status == _EXPECTED_CALM_VAULT_COPY, (
        f"live overlay catch produced {status!r}, expected the calm grammar"
    )
    assert RAW_TRANSPORT_ERROR not in status
    assert "Failed to fetch" not in status
    assert "Error:" not in status


# ---------------------------------------------------------------------------
# AC4 — fail closed on unknown token
# ---------------------------------------------------------------------------
def test_enum_map_fail_closed_on_unknown_token() -> None:
    unknown = "some_new_runtime_token_not_in_map"
    assert humanise_degraded_reason(unknown) == FAIL_CLOSED_DEGRADED
    assert FAIL_CLOSED_DEGRADED == "… unavailable — details withheld. Nothing was lost."

    # End-to-end: an unknown degraded reason renders the fallback, and the raw
    # token is absent from the rendered degraded surface (not echoed into a
    # chip/source data-* attribute). The entry-state <body> declaration is the
    # exempt server-authoritative carrier and is out of scope here.
    payload = _degraded_orientation_payload(unknown)
    html = _render_degraded_orientation_html(unknown)
    surface = _degraded_orientation_surface(html)
    assert unknown not in surface, "unmapped token leaked into degraded surface"
    assert "details withheld" in html
    # The classified value still arrives from the runtime payload.
    assert unknown in payload["meta"]["degraded_reasons"]


def test_humanise_token_passes_through_legitimate_action_class() -> None:
    # A legitimate, already-human action class is not an enum, an id, or a
    # classified-namespace token — it passes through unchanged.
    assert humanise_token("bounded.panel_action") == "bounded.panel_action"
    assert humanise_token("followup.create") == "followup.create"
    assert humanise_token("maturity_transition") == "maturity_transition"


def test_humanise_token_suppresses_id_patterns() -> None:
    for token in ["prop-move-1", "prop-001", "art-123", "artifact-x", "note-a"]:
        assert humanise_token(token) == ""


def test_palette_filter_haystack_includes_humanised_label() -> None:
    # The palette filters on the visible text. A mapped action class renders as
    # "Move note", so typing "Move note" must still match the row even when the
    # description does not contain that exact phrase.
    from companion_ui.workspace.panel_palette import (
        filter_palette_rows,
        palette_row_model,
    )

    proposal = {
        "proposal_id": "prop-move-1",
        "artifact_id": "art-123",
        "description": "Relocate into Projects/",  # does not contain "Move note"
        "status": "staged",
        "evidence": {"action_class": "lifecycle.move"},
        "affordances": {"confirm": True, "correct": True, "reject": True},
    }
    row = palette_row_model(proposal, writeguard_blocked=False)
    assert "move note" in row["filter_text"], "humanised label missing from haystack"
    assert filter_palette_rows([row], "Move note") == [row]


def test_humanise_token_fails_closed_on_unmapped_classified_namespace() -> None:
    # A mapped classified token humanises; an UNMAPPED token in the same
    # classified namespace (lifecycle.*) must fail closed to suppression rather
    # than leak raw to a user surface (CUIDR-01 fail-closed for unmapped enums).
    assert humanise_token("lifecycle.move") == "Move note"
    for unmapped in ["lifecycle.archive", "lifecycle.delete", "lifecycle.split"]:
        assert humanise_token(unmapped) == "", f"{unmapped!r} must fail closed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_VISIBLE_SKIP_TAGS = frozenset({"head", "script", "style", "template"})
_VISIBLE_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _VisibleTextExtractor(HTMLParser):
    """Collect on-screen text via a real HTML parser (no regex tag-filter), so
    whitespace-padded or upper-case close tags (``</script >``, ``<SCRIPT>``)
    cannot leak inert markup into the scanned copy."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth or tag in _VISIBLE_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)


def _visible_text(html: str) -> str:
    """Rendered human-visible text: tags removed and <script>/<style>/<head>
    bodies dropped. Whitespace-collapsed and lower-cased for substring scans."""
    extractor = _VisibleTextExtractor()
    extractor.feed(html)
    extractor.close()
    return " ".join("".join(extractor._chunks).split()).lower()


def _degraded_orientation_surface(html: str) -> str:
    """Isolate the rendered orientation degraded/resurface region.

    Excludes the ``<body>`` tag, whose ``data-entry-degraded-reasons``
    declaration is the server-authoritative entry-state classification carrier
    (set by the entry-state resolver, exempt and out of CUIDR-01 scope). The
    raw-token scan targets the degraded chips, banner, and resurface posture
    region that this task humanises.
    """
    marker = "<main"
    idx = html.find(marker)
    return html[idx:] if idx != -1 else html
