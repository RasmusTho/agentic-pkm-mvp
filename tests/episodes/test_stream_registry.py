"""Stream Registry and Signal Contract tests (ERE-01, #3176).

Covers the governing Issue's five behavioral Acceptance Criteria:

- ``test_signal_contract_validates_required_shape`` (AC1): the signal
  contract validates its bitemporal / per-dimension-confidence / provenance
  shape and rejects malformed instances.
- ``test_registry_fails_loud_on_malformed_declaration`` (AC2): the registry
  loader fails loud on a missing file, an empty/missing fence, and a
  malformed entry -- never a silent empty/default registry.
- ``test_live_streams_bind_to_existing_transports`` (AC3): every seeded
  `live` entry's transport resolves to a real runtime binding (a registered
  outbox topic or an importable runtime consumer module); an unknown
  transport on a `live` entry is rejected fail-loud.
- ``test_registry_matches_readme_inventory`` (AC4): the seeded registry
  matches ``docs/EPISODE_RESOLUTION_ENGINE/README.md`` § Input-source
  inventory 1:1, including the excluded list.
- ``test_engine_consumes_only_registered_streams`` (AC5, enforcement): the
  stub segmenter entrypoint (`app.episodes.segmenter`) resolves its
  consumers strictly through the registry, at the real production call
  site -- not just a registry-module unit test in isolation -- and rejects
  an unregistered/non-live stream_id attempt.

No network, no Postgres, no real vault.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.context_dimensions import ContextDimensions
from app.episodes import closure, segmenter, stream_registry as sr
from app.episodes.screen_stream import OBSERVATION_TOPIC, SCREEN_CONSUMER_ID, SCREEN_STREAM_ID
from app.heimdal.observation_log import ObservationRow
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "docs" / "EPISODE_RESOLUTION_ENGINE" / "README.md"


# ---------------------------------------------------------------------------
# AC1: signal contract
# ---------------------------------------------------------------------------


def test_signal_contract_validates_required_shape() -> None:
    valid = sr.SignalContract(
        stream_id="heimdal.observations",
        signal_id="sig-1",
        observed_at_start="2026-07-11T09:00:00+00:00",
        observed_at_end="2026-07-11T09:05:00+00:00",
        emitted_at="2026-07-11T09:06:00+00:00",
        dimensions_fed={
            "time": sr.ConfidenceScore(score=0.9, calibration="calibrated"),
            "goal": sr.ConfidenceScore(score=0.6, calibration="heuristic"),
        },
        provenance_ref="observation:obs-123",
        scope_binding=ContextDimensions(scope="work"),
    )
    assert valid.stream_id == "heimdal.observations"
    assert valid.dimensions_fed["time"].score == 0.9
    assert valid.observed_at_end == "2026-07-11T09:05:00+00:00"

    # bitemporal + provenance_ref + non-empty dimensions_fed are required
    with pytest.raises(sr.SignalContractError):
        sr.SignalContract(
            stream_id="heimdal.observations",
            signal_id="sig-2",
            observed_at_start="",  # missing observation time -> fail loud
            emitted_at="2026-07-11T09:06:00+00:00",
            dimensions_fed={"time": sr.ConfidenceScore(score=0.9, calibration="calibrated")},
            provenance_ref="observation:obs-124",
        )

    with pytest.raises(sr.SignalContractError):
        sr.SignalContract(
            stream_id="heimdal.observations",
            signal_id="sig-3",
            observed_at_start="2026-07-11T09:00:00+00:00",
            emitted_at="2026-07-11T09:06:00+00:00",
            dimensions_fed={},  # must evidence at least one dimension
            provenance_ref="observation:obs-125",
        )

    with pytest.raises(sr.SignalContractError):
        sr.SignalContract(
            stream_id="heimdal.observations",
            signal_id="sig-4",
            observed_at_start="2026-07-11T09:00:00+00:00",
            emitted_at="2026-07-11T09:06:00+00:00",
            dimensions_fed={"not_a_dimension": sr.ConfidenceScore(score=0.9, calibration="calibrated")},
            provenance_ref="observation:obs-126",
        )

    # per-dimension confidence is structured (score + calibration), never a bare scalar
    with pytest.raises(sr.SignalContractError):
        sr.ConfidenceScore(score=1.5, calibration="calibrated")

    with pytest.raises(sr.SignalContractError):
        sr.ConfidenceScore(score=0.5, calibration="not_a_real_calibration")


# ---------------------------------------------------------------------------
# AC2: fail-loud on malformed declaration
# ---------------------------------------------------------------------------


def test_registry_fails_loud_on_malformed_declaration(tmp_path: Path) -> None:
    # missing file entirely
    missing = tmp_path / "does_not_exist.md"
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(missing)

    # no fenced yaml stream-registry block at all
    no_fence = tmp_path / "no_fence.md"
    no_fence.write_text("# Stream Registry\n\nnothing to see here\n", encoding="utf-8")
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(no_fence)

    # empty fenced block
    empty_fence = tmp_path / "empty_fence.md"
    empty_fence.write_text("```yaml stream-registry\n```\n", encoding="utf-8")
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(empty_fence)

    # streams: [] -- no silent empty registry
    empty_list = tmp_path / "empty_list.md"
    empty_list.write_text("```yaml stream-registry\nstreams: []\n```\n", encoding="utf-8")
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(empty_list)

    # entry missing required fields (no status)
    missing_status = tmp_path / "missing_status.md"
    missing_status.write_text(
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    owner_constituent: Mimer\n"
        "```\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(missing_status)

    # invalid status value outside the four declared classes
    bad_status = tmp_path / "bad_status.md"
    bad_status.write_text(
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    status: not_a_real_status\n"
        "    owner_constituent: Mimer\n"
        "```\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(bad_status)

    # live entry missing transport -- no silent default streams
    live_missing_transport = tmp_path / "live_missing_transport.md"
    live_missing_transport.write_text(
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    status: live\n"
        "    owner_constituent: Mimer\n"
        "    dimensions_fed: [time]\n"
        "    consent_class: vault_implicit\n"
        "    cadence: sparse\n"
        "```\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(live_missing_transport)

    # duplicate stream_id
    duplicate = tmp_path / "duplicate.md"
    duplicate.write_text(
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    status: excluded\n"
        "    owner_constituent: Mimer\n"
        "  - stream_id: some.stream\n"
        "    status: excluded\n"
        "    owner_constituent: Mimer\n"
        "```\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.StreamRegistryError):
        sr.load_registry(duplicate)

    # a well-formed minimal declaration loads cleanly (proves the failures
    # above are about the malformed shape, not the harness)
    good = tmp_path / "good.md"
    good.write_text(
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    status: excluded\n"
        "    owner_constituent: Mimer\n"
        "```\n",
        encoding="utf-8",
    )
    registry = sr.load_registry(good)
    assert registry.stream_ids() == {"some.stream"}


# ---------------------------------------------------------------------------
# AC3: live streams bind to existing runtime transports
# ---------------------------------------------------------------------------


def test_live_streams_bind_to_existing_transports() -> None:
    registry = sr.load_registry()
    live = registry.live_entries()
    assert live, "expected at least one seeded live stream"

    for entry in live:
        assert entry.transport is not None
        # re-resolving must not raise -- proves the seeded registry's own
        # transports are real runtime bindings, not just syntactically present
        sr._resolve_transport_binding(entry.transport, stream_id=entry.stream_id)

    # an outbox-shaped transport naming an unregistered topic is rejected
    with pytest.raises(sr.UnknownTransportError):
        sr._resolve_transport_binding("outbox:not.a.real.topic", stream_id="fixture.stream")

    # a module-shaped transport naming a module that does not exist is rejected
    with pytest.raises(sr.UnknownTransportError):
        sr._resolve_transport_binding("module:app.does_not_exist.nope", stream_id="fixture.stream")

    # an unrecognized transport shape is rejected
    with pytest.raises(sr.UnknownTransportError):
        sr._resolve_transport_binding("carrier_pigeon", stream_id="fixture.stream")

    # loading a declaration with a live entry naming an unknown transport
    # fails loud at load time, not silently later
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        bad_transport_path = Path(tmp) / "bad_transport.md"
        bad_transport_path.write_text(
            "```yaml stream-registry\n"
            "streams:\n"
            "  - stream_id: bogus.stream\n"
            "    status: live\n"
            "    owner_constituent: Mimer\n"
            "    dimensions_fed: [time]\n"
            "    consent_class: vault_implicit\n"
            "    cadence: sparse\n"
            "    transport: outbox:not.a.real.topic\n"
            "```\n",
            encoding="utf-8",
        )
        with pytest.raises(sr.UnknownTransportError):
            sr.load_registry(bad_transport_path)


# ---------------------------------------------------------------------------
# AC4: registry matches the README inventory 1:1, including excluded
# ---------------------------------------------------------------------------


_BACKTICK_ID = re.compile(r"`([a-zA-Z0-9_.]+)`")
_EXCLUDED_ID = re.compile(r"`([a-zA-Z0-9_.]+)`\s*—")
_STATUS_BOLD = re.compile(r"\*\*(live|planned|future|excluded)\*\*")


def _readme_inventory_statuses() -> dict[str, str]:
    """Extract stream_id -> status for every entry in the README's
    Input-source inventory section: from each table data row, the first
    (`stream_id`) cell's backticked id(s) paired with the second (Status)
    cell's bold status word; plus the excluded paragraph's `id` — entries
    (all `excluded`). Deliberately does not sweep every backtick in the
    section -- the Transport column also quotes outbox topic names (e.g.
    `ingest.vault.changed`), which are not stream_ids."""
    text = README_PATH.read_text(encoding="utf-8")
    start = text.index("## Input-source inventory")
    end = text.index("## Implementation tasks", start)
    section = text[start:end]

    statuses: dict[str, str] = {}
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("| `"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            row_ids = _BACKTICK_ID.findall(cells[0])
            status_match = _STATUS_BOLD.search(cells[1])
            assert status_match is not None, f"README inventory row has no bold status: {stripped}"
            for stream_id in row_ids:
                statuses[stream_id] = status_match.group(1)
        elif stripped.startswith("**Excluded"):
            for stream_id in _EXCLUDED_ID.findall(stripped):
                statuses[stream_id] = "excluded"
    return statuses


def test_registry_matches_readme_inventory() -> None:
    registry = sr.load_registry()
    readme_statuses = _readme_inventory_statuses()
    assert readme_statuses, "expected stream_id -> status entries in the README inventory section"

    # 1:1 parity per id AND per status -- a per-id status drift between the
    # README table and the registry declaration fails here, not only an
    # id-set drift
    registry_statuses = {entry.stream_id: entry.status for entry in registry.entries.values()}
    assert registry_statuses == readme_statuses

    # all four declared status classes are represented, including excluded
    for status in (sr.STATUS_LIVE, sr.STATUS_PLANNED, sr.STATUS_FUTURE, sr.STATUS_EXCLUDED):
        assert registry.by_status(status), f"expected at least one {status!r} entry"


def test_screen_stream_registered_live() -> None:
    registry = sr.load_registry()
    entry = registry.get(SCREEN_STREAM_ID)
    assert entry is not None
    assert entry.status == sr.STATUS_LIVE
    assert entry.transport == "module:app.heimdal.observation_log"
    assert entry.consent_class == "heimdal_gated"
    assert entry.cadence == "continuous"
    assert entry.owner_constituent == "Heimdal"
    assert set(entry.dimensions_fed) == set(sr.DIMENSIONS)
    assert segmenter.resolve_stream_adapter(entry) is not None


# ---------------------------------------------------------------------------
# AC5 (enforcement): the segmenter entrypoint enumerates via the registry only
# ---------------------------------------------------------------------------


def test_engine_consumes_only_registered_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyAdapter:
        def read(self, ctx: segmenter.TickContext) -> segmenter.ReadResult:
            return segmenter.ReadResult(rows=[])

        def normalize(
            self, row: object, ctx: segmenter.TickContext
        ) -> segmenter.SegmentationSignal | None:
            raise AssertionError("an empty adapter must not normalize rows")

        def advance_cursor(self, rows: list[object], ctx: segmenter.TickContext) -> None:
            assert rows == []

    registry = sr.load_registry()
    adapters = {
        entry.stream_id: EmptyAdapter()
        for entry in registry.live_entries()
        if segmenter.resolve_stream_adapter(entry) is not None
    }

    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(
        segmenter,
        "_emit_proposals_with_fusion_gate",
        lambda *a, **k: {"proposed": [], "fused": [], "fusions_denied": 0},
    )
    monkeypatch.setattr(segmenter, "artifact_candidates_from_signals", lambda signals: [])
    monkeypatch.setattr(segmenter, "episode_bounds_from_closed_segments", lambda *a, **k: [])
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda *a, **k: {"pending": 0, "corrected": 0},
    )
    monkeypatch.setattr(
        closure, "run_closure_tick", lambda **k: {"closed": [], "events_emitted": 0}
    )

    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        adapters=adapters,
        write_guard=WriteGuard(lambda: {"state": "healthy", "reason": None}),
    )

    assert set(result["consumed"]) == {entry.stream_id for entry in registry.live_entries()}
    assert SCREEN_STREAM_ID in result["consumed"]

    # swap in a fixture registry: the entrypoint must reflect *that* registry's
    # live entries exactly, never a value baked into the segmenter module
    fixture_registry = sr.StreamRegistry(
        entries={
            "fixture.live.one": sr.StreamRegistryEntry(
                stream_id="fixture.live.one",
                status="live",
                owner_constituent="Test",
                dimensions_fed=("time",),
                transport="module:app.heimdal.observation_log",
                consent_class="vault_implicit",
                cadence="sparse",
            ),
            "fixture.planned.one": sr.StreamRegistryEntry(
                stream_id="fixture.planned.one",
                status="planned",
                owner_constituent="Test",
            ),
        }
    )
    fixture_live = segmenter.run_segmenter_stub(registry=fixture_registry)
    assert {entry.stream_id for entry in fixture_live} == {"fixture.live.one"}

    # explicit stream_ids: a registered live id resolves
    resolved = segmenter.enumerate_consumable_streams(["fixture.live.one"], registry=fixture_registry)
    assert [entry.stream_id for entry in resolved] == ["fixture.live.one"]

    # an unregistered stream_id attempt is rejected at the entrypoint, not
    # silently consumed
    with pytest.raises(sr.UnregisteredStreamError):
        segmenter.enumerate_consumable_streams(["not.a.registered.stream"], registry=fixture_registry)

    # a registered-but-not-live stream_id attempt is also rejected
    with pytest.raises(sr.UnregisteredStreamError):
        segmenter.enumerate_consumable_streams(["fixture.planned.one"], registry=fixture_registry)

    with pytest.raises(sr.UnregisteredStreamError):
        segmenter.run_segmenter_stub(stream_ids=["not.a.registered.stream"], registry=fixture_registry)

    # Exercise the screen stream through its default production adapter with
    # only that registered source enabled. The earlier empty-adapter pass
    # proves registry enumeration; this pass proves a published screen span
    # is normalized and folded at the same entrypoint.
    screen_entry = registry.get(SCREEN_STREAM_ID)
    assert screen_entry is not None
    screen_registry = sr.StreamRegistry(entries={SCREEN_STREAM_ID: screen_entry})
    screen_row = ObservationRow(
        id="log:screen-registry-case",
        topic=OBSERVATION_TOPIC,
        idempotency_key="key:screen-registry-case",
        envelope={
            "event": OBSERVATION_TOPIC,
            "payload": {
                "observation_id": "screen-registry-case",
                "modality": "screen",
                "observed_at_start": "2026-07-11T08:00:00Z",
                "observed_at_end": "2026-07-11T08:00:30Z",
                "scope_hint": "work",
                "attributions": [{"mention_id": "operator", "resolution": "resolved"}],
                "content_structure": {
                    "span": {
                        "dimensions": {
                            "app": "Obsidian",
                            "window": "Project notes",
                            "scope": "work",
                            "goal": "review project notes",
                        }
                    }
                },
                "confidence": {
                    "attribution": {"score": 1.0, "calibration": "by_construction"},
                    "activity_summary": {"score": 0.8, "calibration": "heuristic"},
                    "entity_mention": {"score": 0.7, "calibration": "heuristic"},
                },
                "provenance": {"content_identity": "content:screen-registry-case", "capture_chain": ["capture:1"]},
                "consent": {"grant_ref": "consent:screen:grant-1"},
            },
        },
        created_at=datetime(2026, 7, 11, 8, 1, tzinfo=timezone.utc),
        sequence=1,
    )
    screen_cursor_advances: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda consumer_id, **kwargs: [screen_row])
    monkeypatch.setattr(
        segmenter,
        "advance_cursor_for_consumer",
        lambda consumer_id, rows: screen_cursor_advances.append((consumer_id, [row.id for row in rows])),
    )
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    screen_result = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=screen_registry,
        write_guard=WriteGuard(lambda: {"state": "healthy", "reason": None}),
    )
    assert screen_result["consumed"] == {SCREEN_STREAM_ID: 1}
    assert screen_result["open_segments"] == 1
    assert screen_cursor_advances == [(SCREEN_CONSUMER_ID, [screen_row.id])]


# ---------------------------------------------------------------------------
# Boundary regression: transport validation never imports across the
# interaction-protected boundary
# ---------------------------------------------------------------------------


def test_load_registry_never_imports_interaction_modules() -> None:
    """Validating a `module:` transport (e.g. `module:app.chat.session_log`)
    must be a filesystem existence check, never an import: `find_spec` on a
    dotted path imports the parent package, so resolving `app.chat.session_log`
    would execute the interaction-layer `app.chat` package on every
    `load_registry()` call -- invisible to the AST-based import-linter
    (importlinter.ini interaction-protected contract)."""
    removed = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "app.chat" or name.startswith("app.chat.")
    }
    try:
        registry = sr.load_registry(use_cache=False)
        # the chat.sessions planned entry (transport module:app.chat.session_log)
        # was validated during that load...
        assert registry.get("chat.sessions") is not None
        # ...without importing app.chat or any of its submodules
        polluted = [name for name in sys.modules if name == "app.chat" or name.startswith("app.chat.")]
        assert not polluted, f"load_registry() imported interaction-layer modules: {polluted}"
    finally:
        sys.modules.update(removed)


# ---------------------------------------------------------------------------
# Registry cache: production path loads once; tests can reset/bypass
# ---------------------------------------------------------------------------


def test_load_registry_caches_per_path(tmp_path: Path) -> None:
    sr.reset_registry_cache()
    try:
        first = sr.load_registry()
        second = sr.load_registry()
        assert second is first, "expected the cached registry object on a repeat load"

        # reset forces a fresh parse
        sr.reset_registry_cache()
        third = sr.load_registry()
        assert third is not first
        assert third.stream_ids() == first.stream_ids()

        # use_cache=False bypasses (fresh object) and does not poison the cache
        fourth = sr.load_registry(use_cache=False)
        assert fourth is not third
        assert sr.load_registry() is third

        # a failed load is never cached: the same path parses fresh (and
        # fails again) until the declaration is actually fixed
        flaky = tmp_path / "flaky.md"
        flaky.write_text("no fence here\n", encoding="utf-8")
        with pytest.raises(sr.StreamRegistryError):
            sr.load_registry(flaky)
        flaky.write_text(
            "```yaml stream-registry\n"
            "streams:\n"
            "  - stream_id: some.stream\n"
            "    status: excluded\n"
            "    owner_constituent: Mimer\n"
            "```\n",
            encoding="utf-8",
        )
        fixed = sr.load_registry(flaky)
        assert fixed.stream_ids() == {"some.stream"}
    finally:
        sr.reset_registry_cache()


def test_cached_registry_is_immutable() -> None:
    """`load_registry()` hands the same cached object to every caller, so a
    caller mutating `.entries` must raise instead of silently corrupting the
    process-wide registry for every later consumer."""
    sr.reset_registry_cache()
    try:
        first = sr.load_registry()
        victim = next(iter(first.entries))

        with pytest.raises(TypeError):
            del first.entries[victim]  # type: ignore[attr-defined]
        with pytest.raises(TypeError):
            first.entries[victim] = None  # type: ignore[index]
        with pytest.raises(AttributeError):
            # mappingproxy exposes no mutating methods at all
            first.entries.clear()  # type: ignore[attr-defined]

        # the singleton is unharmed: the same cached object still carries
        # the full inventory on the next load
        second = sr.load_registry()
        assert second is first
        assert victim in second.entries

        # directly constructed registries are equally frozen, and the
        # caller's own dict reference cannot reach the internal mapping
        source: dict[str, sr.StreamRegistryEntry] = {
            "some.stream": sr.StreamRegistryEntry(
                stream_id="some.stream", status="excluded", owner_constituent="Mimer"
            )
        }
        registry = sr.StreamRegistry(entries=source)
        source.clear()
        assert registry.get("some.stream") is not None
    finally:
        sr.reset_registry_cache()


def test_registry_declaration_parses_with_crlf_line_endings() -> None:
    """A CRLF declaration text must parse identically -- in multiline mode
    `$` anchors before the `\\n`, so the closing fence must explicitly
    tolerate the stray `\\r` or a well-formed CRLF document fails to match.

    Feeds the CRLF string straight to `parse_registry_markdown`: a
    file-based test would not exercise the regex, because `Path.read_text`
    universal-newline translation rewrites `\\r\\n` to `\\n` before the
    pattern ever sees it. CRLF text reaches the parser through any caller
    that reads bytes or uses `newline=''`."""
    content = (
        "```yaml stream-registry\n"
        "streams:\n"
        "  - stream_id: some.stream\n"
        "    status: excluded\n"
        "    owner_constituent: Mimer\n"
        "```\n"
    ).replace("\n", "\r\n")
    registry = sr.parse_registry_markdown(content, source="<crlf-fixture>")
    assert registry.stream_ids() == {"some.stream"}
