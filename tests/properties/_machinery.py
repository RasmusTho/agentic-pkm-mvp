"""Shared machinery for the P-2 event-completeness property (#2909).

Derivation: ``docs/architecture/formal-model.md`` §3 gap 2 ("Event-completeness")
and §4 seam C8 (the mirror census). The upstream property spec that names the
``Verify:`` targets this package implements lives in
``docs/testing/invariant-synthesis-2026-07.md :: P-2`` on the yet-unmerged
``docs/research-invariants-evolution-constitution`` branch (RESEARCH-03, #2781);
that doc is quoted here in full because it is not yet on ``main`` — see the
"Anchor drift" note in the governing issue's implementation PR.

This module is the census + spy-fixture layer other ``tests/properties/*``
modules (P-1, P-3..P-7; #2910-#2913) will extend. Keep it free of any single
property's assertions -- those live in the ``test_*.py`` files.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"

# ---------------------------------------------------------------------------
# Registered-mirror census (closed, justified exception set)
# ---------------------------------------------------------------------------
#
# Every production call site that invokes ``ObjectStore.save_object`` (or any
# future store-mutation primitive) with ``emit_outbox=False`` MUST be listed
# here with a one-line justification, or ``test_mirror_census_is_closed``
# fails. This is deliberately a closed set, not a wildcard/pattern allowlist:
# adding a new mirror site requires a reviewed one-line justification in the
# same PR that introduces it, per the issue's binding constraint ("adding to
# it requires a one-line justification, not just an entry").
#
# Census source: docs/architecture/formal-model.md :: 4. Consistency model, C8
# (11 production sites verified against `main` @ #2909 implementation time).
# `app/cli/smoke.py` sites are dev/CI harness writers, structurally excluded
# from the formal model's Σ by declaration (formal-model.md §2.3) and MUST
# NEVER run against a real vault -- they are not part of this census.

REGISTERED_MIRRORS: dict[tuple[str, int], str] = {
    ("app/services/indexer.py", 93): (
        "T-materialize sink (handle_ingest_object_created): the INGEST_OBJECT_CREATED "
        "event that CAUSED this row is its own record -- emitting a second event here "
        "would be a duplicate, not completeness (formal-model.md T-materialize)."
    ),
    ("app/promotion/consumer.py", 97): (
        "_apply_promotion_to_store: the caller (consume_promotion_intents) emits "
        "promote.done / promotion.transition.applied after this call on the same "
        "trace_id; the mirror write and the event are one logical transition (T-promote)."
    ),
    ("app/agents/panel_agent/execution.py", 62): (
        "refresh_panel_note_object: panel note refresh is a read-model refresh inside "
        "run_panel_note_execution, which emits panel.action.logged/blocked via the "
        "runtime's own outbox path (app/agents/panel_agent/runtime.py) for the same turn."
    ),
    ("app/watcher/vault_watcher.py", 136): (
        "_hydrate_store_with_markdown: best-effort raw_text hydration for panel-scan "
        "note refresh; the mutating vault-sync path (T-sync) already emitted "
        "ingest.object.* for this note earlier in the same tick."
    ),
    ("app/agents/panel_agent/runtime.py", 112): (
        "_persist_log: appends an in-payload panel_logs entry (observability, not new "
        "domain content); the panel action itself emits panel.action.logged/blocked "
        "via _write_db_outbox_events in the same runtime module."
    ),
    ("app/agents/panel/writeback.py", 213): (
        "upsert_executed_ids: records already-executed panel action ids for "
        "idempotency bookkeeping (S.proposals-adjacent); the action's own execution "
        "emits its event via the panel runtime seam that calls this helper."
    ),
    ("app/agents/planner/agent.py", 118): (
        "PlannerAgent.save_plan: persists in-progress plan/step state (agent working "
        "memory, CAO plane), not P.objects domain content with independent replay "
        "meaning -- no event topic models plan-step mutation today (tracked, not new)."
    ),
    ("app/agents/planner/graph.py", 237): (
        "plan-state graph node: mirrors a review_state/maturity frontmatter update the "
        "caller drives through the promotion transition path (T-promote), which emits "
        "the promotion events; this write is the plan/graph bookkeeping half."
    ),
    ("app/agents/normalizer/agent.py", 159): (
        "normalize_file's run(): legacy normalizer ingest shim used by classifier/"
        "normalizer test flows and the memory-backend CLI path; the object's creation "
        "event is emitted by the caller (ingest API / vault_alpha) that invokes normalize."
    ),
    ("app/ingest/api.py", 112): (
        "POST /ingest object persistence: insert_object_and_outbox already emitted "
        "ingest.object.created for this same logical ingest (T-ingest-api splits "
        "event-emission and object-materialization -- see formal-model.md T-materialize); "
        "this call is the eventual T-materialize-equivalent write for the API path."
    ),
    ("app/ingest/vault_alpha.py", 526): (
        "Legacy vault-alpha ingest path: keeps classifier/normalizer flows working "
        "against the memory backend during tests/alpha runs; the alpha ingest pipeline "
        "emits its own ingest event upstream of this call in the same run."
    ),
}

# Sites that are structurally excluded from the census by declaration
# (formal-model.md §2.3: "Dev/CI harness writers ... are structurally identical
# writes and are EXCLUDED from this model by declaration; they must never run
# against a real vault"). Listed explicitly (not wildcarded) so a new
# non-harness file cannot hide behind a path-prefix escape hatch.
HARNESS_EXCLUDED_FILES: frozenset[str] = frozenset({"app/cli/smoke.py"})


# ---------------------------------------------------------------------------
# Static census scan
# ---------------------------------------------------------------------------


def find_emit_outbox_false_sites(root: Path = APP_ROOT) -> list[tuple[str, int]]:
    """AST-scan every ``app/**/*.py`` file for ``emit_outbox=False`` call sites.

    Returns ``(relative_path, lineno)`` pairs, deliberately excluding nothing --
    filtering harness-excluded files is the caller's job (`REGISTERED_MIRRORS`
    lookups vs. `HARNESS_EXCLUDED_FILES`) so this function itself cannot be the
    place a new escape hatch quietly gets added.
    """
    sites: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "emit_outbox":
                    continue
                if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    sites.append((rel, node.lineno))
    return sites


# ---------------------------------------------------------------------------
# Spy fixtures over the real production outbox seam
# ---------------------------------------------------------------------------


@dataclass
class OutboxCall:
    """One recorded call into the outbox-insert seam."""

    topic: str
    object_id: str | None
    source: str | None


@dataclass
class SaveObjectCall:
    """One recorded call into ``ObjectStore.save_object``."""

    uuid: str
    kind: str
    emit_outbox: bool


@dataclass
class EventSpy:
    """Records every real production call that would emit or mirror an event.

    Wraps the two seams a P-2 transition can reach:
      - ``app.objects.ObjectStore.save_object`` (records emit_outbox + uuid)
      - ``app.services.outbox.insert_object_and_outbox`` (records the topic
        actually enqueued -- the ground truth for "an event was emitted")

    Spying at these two real seams (not re-implementing them) is what makes
    this a property over the *actual* production call sites per the issue's
    guard-coverage requirement, rather than a test of a test double.
    """

    save_object_calls: list[SaveObjectCall] = field(default_factory=list)
    outbox_calls: list[OutboxCall] = field(default_factory=list)

    def record_save_object(self, uuid: str, kind: str, emit_outbox: bool) -> None:
        self.save_object_calls.append(SaveObjectCall(uuid=uuid, kind=kind, emit_outbox=emit_outbox))

    def record_outbox_insert(self, topic: str, object_id: str | None, source: str | None) -> None:
        self.outbox_calls.append(OutboxCall(topic=topic, object_id=object_id, source=source))

    def emitted_for(self, uuid: str) -> bool:
        return any(call.object_id == uuid for call in self.outbox_calls)


@contextmanager
def spy_on_object_store(
    monkeypatch: pytest.MonkeyPatch, spy: EventSpy
) -> Iterator[EventSpy]:
    """Wrap the REAL ``ObjectStore.save_object`` and ``insert_object_and_outbox``
    seams with recording spies, calling straight through to the original
    implementation. This is a spy (observe + delegate), not a stub/fake --
    every wrapped call still executes the production code path.
    """
    import app.objects as objects_mod
    import app.services.outbox as outbox_mod

    original_save_object = objects_mod.ObjectStore.save_object
    original_insert = outbox_mod.insert_object_and_outbox

    def traced_save_object(
        self: Any,
        obj: Any,
        emit_outbox: bool = True,
        trace_id: str | None = None,
    ) -> None:
        spy.record_save_object(uuid=str(obj.uuid), kind=str(obj.kind), emit_outbox=emit_outbox)
        return original_save_object(self, obj, emit_outbox=emit_outbox, trace_id=trace_id)

    def traced_insert(
        payload: dict[str, Any],
        topic: str,
        trace_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        object_id = kwargs.get("object_id") or payload.get("uuid") or payload.get("object_id")
        source = kwargs.get("source")
        spy.record_outbox_insert(topic=topic, object_id=object_id and str(object_id), source=source)
        return original_insert(payload, topic, trace_id, **kwargs)

    monkeypatch.setattr(objects_mod.ObjectStore, "save_object", traced_save_object)
    # objects.py imported insert_object_and_outbox directly into its module
    # namespace, so patch the reference actually called from save_object.
    monkeypatch.setattr(objects_mod, "insert_object_and_outbox", traced_insert)
    monkeypatch.setattr(outbox_mod, "insert_object_and_outbox", traced_insert)
    yield spy


@pytest.fixture
def event_spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[EventSpy]:
    spy = EventSpy()
    with spy_on_object_store(monkeypatch, spy):
        yield spy


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """All P-2 property tests run over the explicit memory backend (`not pg`).

    Also clears the in-process ``_MEMORY_STORE`` mirror (module-level dict, not
    covered by ``reset_store_backends``'s lru_cache clear) before AND after each
    test/example so state never leaks between hypothesis examples or tests --
    the established pattern in
    ``tests/promotion/test_panel_promotion_intent_payload.py``.
    """
    import app.objects as objects_mod

    monkeypatch.setenv("STORE_BACKEND", "memory")
    objects_mod._MEMORY_STORE.clear()
    yield
    objects_mod._MEMORY_STORE.clear()
