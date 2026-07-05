"""KERNEL-11 (#2773): dispatch-every-topic-twice handler idempotency harness.

Outbox delivery is at-least-once (``app/workers/outbox_worker.py::run`` re-processes
on restart; ``ack_outbox`` is the last durable action). Handler idempotency
(``handle_T(e); handle_T(e)`` == ``handle_T(e)`` on durable state) was previously
asserted only by convention (audit invariant I-E2,
``docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md``). This harness
proves it by dispatching every registered topic through the real production
entrypoint (``_dispatch_topic``) TWICE with a representative fixture payload and
diffing durable state between the two dispatches.

Durable state = the three legs the spec names
(``docs/RUNTIME_CORRECTNESS_KERNEL/HANDLER_IDEMPOTENCY_HARNESS.md`` line 35:
objects/file_state/vector index + vault writes):

- **store rows** — the memory ``ObjectStore`` (``_MEMORY_STORE``);
- **vector index** — the REAL memory ``MemoryVectorIndex`` (``all_rows()``). The
  vector index is NOT stubbed: only the outbound embeddings *client* is stubbed
  (``_stub_indexer_embeddings`` / ``_stub_consumer_embeddings`` replace
  ``llm_embed_text`` / ``get_embeddings_client`` + ``get_embedding_identity``
  with a fixed dim-8 vector), so the handlers run the genuine
  ``purge_vectors``+``upsert`` and a double-insert on redelivery is caught here;
- **vault writes** — the tmp vault tree (hashed per file).

All three MUST converge for all 7 topics (``durable_state_matches``).

The **emitted outbox events** leg is asserted per each topic's declared
``_EmissionExpectation`` — never a silent empty-list compare:

- IDEMPOTENT (``promote.intent.created``): emits >0 events on dispatch 1 (the
  event_id-keyed ``_PROMOTION_DEDUP`` gate), deduped on dispatch 2. Non-vacuity
  is enforced (emission count must be > 0).
- ZERO_BY_DESIGN (``ingest.object.deleted``, ``note.move.workbench``): the
  handler emits no outbox events; asserted as exactly zero after *both*
  dispatches (an explicit ``== []``, not a silent ``[] == []``).
- KNOWN_NONIDEMPOTENT_2881 (``ingest.object.created``, ``ingest.vault.changed``,
  ``panel.scan.requested``, ``index.embedding.requested``): the audit-emission
  layer appends net-new events on redelivery (see the #2881 note below);
  asserted as growth so a fix must re-classify the topic.

Coverage is dynamic, not a hardcoded list: ``_dispatched_topics()`` walks
``_dispatch_topic``'s own if/elif chain via ``ast`` and resolves BOTH
module-constant (``ast.Name``) and inline string-literal (``ast.Constant``)
comparators (see ``test_string_literal_dispatch_branch_is_enumerated``), so a
newly dispatched topic in either form with no registered ``TOPIC_FIXTURES`` entry
fails this harness loud rather than being silently skipped
(``test_every_topic_has_a_fixture``).

## Reported finding: outbox audit-emission helpers are not idempotent (#2881)

Building this harness surfaced a real, pre-existing gap -- filed as its own issue
(#2881) per this Issue's own "Out of Scope: making handlers idempotent that are
not already... a discovered non-idempotent handler is a separate bug/issue",
rather than silently choosing fixtures that dodge the codepath or widening this
issue's scope to fix it.

``app/outbox/events.py``'s audit-notification emit helpers
(``_append_record_best_effort``, used by ``emit_index_object_embedded``,
``emit_index_embedding_created``, ``emit_index_embedding_failed``) and
``app/services/outbox.py::append_jsonl_outbox_event`` (used by the panel agent's
``run_panel_intent_for_note``) append **unconditionally** to a JSONL audit sink
with a fresh random ``event_id`` on every call -- there is no idempotency-key
dedup at this layer (unlike the DB-backed ``write_outbox_event``, which dedups
via KERNEL-02's mandatory idempotency key). ``derive_idempotency_key``'s own
docstring already names this class of gap for the ``EVENT_ID_FINGERPRINT``
scheme: "protects against double-insert of the same constructed event only, not
logical replay ... move such topics to content-derived fingerprints as their
semantics allow."

Concretely, re-dispatching the same outbox row a second time (crash-retry,
redelivery -- exactly what this harness simulates) produces a **second** audit
JSONL line for ``ingest.object.created``, ``ingest.vault.changed``, and
``index.embedding.requested``. ``panel.scan.requested`` has the same gap at the
audit-emission layer (``sync.latency.summary``) *and* a more severe
content-triggered instance: ``run_panel_intent_for_note`` re-emits N fresh
``panel.intent.created`` events (one per AI-panel block found in the note) on
every scan, unconditionally.

The underlying store/vector-index/vault-file state for every one of these
handlers IS idempotent (upsert keyed by stable id, content-diff-gated writes) --
proven by the durable-state convergence assertion, which holds for all 7 topics.
Only the audit/notification emission layer grows unboundedly on redelivery, so
those four topics are classified KNOWN_NONIDEMPOTENT_2881 and the harness asserts
their *actual, known* non-convergent emission behavior explicitly (net new audit
lines on the second dispatch) so a fix lands as a visible, intentional
re-classification linked to #2881, not a silent regression discovered later.

``panel.scan.requested``'s fixture deliberately uses a note with **no** AI panel
blocks so the harness still exercises the real handler (file read, uuid
resolution, object upsert, latency-audit emission) deterministically without an
LLM/network dependency; the panel-intent-per-block re-emission is covered by
#2881's own acceptance criteria, not duplicated here.
"""

from __future__ import annotations

import ast
import enum
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pytest

import app.workers.outbox_worker as outbox_worker
from app import objects as object_store_module
from app.components.embeddings import EmbeddingIdentity
from app.events.models import new_event
from app.objects import ObjectStore
from app.promotion import consumer as promotion_consumer
from app.stores import get_vector_index

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Dynamic dispatch-table enumeration (mirrors
# tests/events/test_topic_schema_registry.py::_dispatched_topics so a newly
# dispatched topic is discovered from the same source of truth, not a second
# hand-maintained list).
# ---------------------------------------------------------------------------


def _enumerate_topic_comparators(source: str, module_ns: dict[str, Any]) -> list[str]:
    """Resolve every topic string a dispatch-function source compares against.

    Handles both comparator forms so a new branch cannot ship uncovered:
    - ``ast.Name`` — a module-level constant (``topic == INGEST_OBJECT_CREATED``);
      resolved through ``module_ns`` to its string value.
    - ``ast.Constant`` — an inline string literal (``topic == "some.topic"``);
      resolved directly. Without this a literal branch would be invisible and a
      new topic could ship with zero coverage while the fixture gate stayed
      green (see test_string_literal_dispatch_branch_is_enumerated).
    """
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    comparators: list[ast.expr] = []

    def _walk_if_chain(node: ast.stmt) -> None:
        if not isinstance(node, ast.If):
            return
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "topic"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
        ):
            comparators.extend(test.comparators)
        for stmt in node.orelse:
            _walk_if_chain(stmt)

    for stmt in func_def.body:
        _walk_if_chain(stmt)

    resolved: list[str] = []
    for comparator in comparators:
        if isinstance(comparator, ast.Constant):
            assert isinstance(comparator.value, str), (
                f"dispatch table compares topic against non-string literal {comparator.value!r}"
            )
            resolved.append(comparator.value)
        elif isinstance(comparator, ast.Name):
            name = comparator.id
            assert name in module_ns, f"dispatch table references undefined name {name!r}"
            value = module_ns[name]
            assert isinstance(value, str), f"dispatch table constant {name!r} is not a string topic"
            resolved.append(value)
        else:  # pragma: no cover - guards against an unrecognized comparator form
            raise AssertionError(
                f"dispatch table compares topic against an unsupported node {type(comparator).__name__}; "
                "extend _enumerate_topic_comparators to resolve it so the topic cannot ship uncovered."
            )
    return resolved


def _dispatched_topics() -> list[str]:
    """Enumerate every topic constant/literal compared in ``_dispatch_topic``'s if/elif chain."""
    source = inspect.getsource(outbox_worker._dispatch_topic)
    resolved = _enumerate_topic_comparators(source, vars(outbox_worker))
    assert resolved, "expected to find at least one dispatched topic comparator in _dispatch_topic"
    return resolved


# ---------------------------------------------------------------------------
# Fixture-registration pattern (Issue #2773 Scope): a TOPIC_FIXTURES mapping
# keyed by topic. Each fixture is a zero-arg callable building the payload plus
# any vault/store setup needed before dispatch. Adding a dispatched topic
# without adding an entry here fails test_every_topic_has_a_fixture below -- no
# silent coverage cap.
#
# Each fixture declares an ``_EmissionExpectation`` (IDEMPOTENT /
# ZERO_BY_DESIGN / KNOWN_NONIDEMPOTENT_2881) describing how its emitted-outbox-
# event leg must behave on the second dispatch given the *current* code (see the
# module docstring and #2881).
# ---------------------------------------------------------------------------


class _EmissionExpectation(enum.Enum):
    """How the emitted-outbox-events leg must behave for a topic's fixture.

    - IDEMPOTENT: the fixture drives a real emission (>0 events) that MUST
      converge across both dispatches. Non-vacuity is enforced: the emission
      count after dispatch-1 must be > 0, or the assertion fails as vacuous.
    - ZERO_BY_DESIGN: the handler emits no outbox events for this fixture at
      all (e.g. a pure-logging no-op, or a handler whose only side effect is a
      vault write). Asserted as exactly zero events after both dispatches --
      not a silent empty-list compare.
    - KNOWN_NONIDEMPOTENT_2881: the audit-emission layer appends a net-new
      event on the second dispatch (tracked by #2881). Asserted as growth so a
      fix flips the flag and this assertion fails loud until updated.
    """

    IDEMPOTENT = "idempotent"
    ZERO_BY_DESIGN = "zero_by_design"
    KNOWN_NONIDEMPOTENT_2881 = "known_nonidempotent_2881"


class _FixtureResult:
    """A fixture's dispatch payload plus an optional side-channel emission counter.

    Most topics' outbox emissions land in the JSONL audit sink this harness
    already snapshots. ``promote.intent.created`` emits through a DB writer
    with no in-memory outbox queue table (`app/services/outbox.py::_open_conn`
    requires a real Postgres connection), so its fixture stubs the DB-write
    choke point and reports emission count via ``emission_count`` instead --
    this keeps the IDEMPOTENT assertion meaningful (checking the dedup gate
    actually fired) rather than vacuously true on two empty JSONL reads.
    """

    def __init__(self, payload: dict[str, Any], *, emission_count: Callable[[], int] | None = None) -> None:
        self.payload = payload
        self.emission_count = emission_count


class _TopicFixture:
    def __init__(
        self,
        event_type: str,
        setup: Callable[[Path, pytest.MonkeyPatch], _FixtureResult],
        *,
        emission: _EmissionExpectation,
    ) -> None:
        self.event_type = event_type
        self.setup = setup
        self.emission = emission


def _write_note(vault_root: Path, rel_path: str, *, note_uuid: str, body: str = "Body text\n") -> Path:
    note_path = vault_root / rel_path
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\ntitle: Fixture Note\nuuid: {note_uuid}\n---\n\n{body}",
        encoding="utf-8",
    )
    return note_path


def _write_layout_note(vault_root: Path, *, inbox_folder: str = "Inbox", desk_folder: str = "Workbench") -> None:
    system = vault_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    (system / "vault.layout.md").write_text(
        "---\n"
        "version: '1'\n"
        "system_folder: 'System'\n"
        f"inbox_folder: '{inbox_folder}'\n"
        f"desk_folder: '{desk_folder}'\n"
        "root_folders: []\n"
        "---\n\n# layout\n",
        encoding="utf-8",
    )


# Deterministic stub identity/vector: dim 8, normalize=False so the real
# MemoryVectorIndex stores the raw vector unchanged (see MemoryVectorIndex.upsert).
_STUB_IDENTITY = EmbeddingIdentity(provider="stub", model="stub-model", dim=8, normalize=False)
_STUB_VECTOR = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


def _stub_indexer_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub only the OUTBOUND embed call for app.services.indexer.

    The vector INDEX itself stays real (``get_vector_index`` is NOT stubbed):
    ``handle_ingest_object_created`` runs the genuine ``MemoryVectorIndex``
    ``purge_vectors``+``upsert``, so a double-insert on redelivery would be
    caught by the vector-index snapshot leg. Only the network-bound embedding
    provider (``llm_embed_text``) and identity resolution are stubbed to a
    fixed dim-8 vector so the harness needs no live embeddings client.
    """
    from app.services import indexer as indexer_module

    monkeypatch.setattr(indexer_module, "llm_embed_text", lambda **_: list(_STUB_VECTOR))
    monkeypatch.setattr(indexer_module, "get_embedding_identity", lambda: _STUB_IDENTITY)


def _stub_consumer_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub only the OUTBOUND embed call for app.indexer.consumer.

    As with _stub_indexer_embeddings, the vector INDEX stays real: the
    consumer's ``get_vector_index().purge_vectors``+``upsert`` run against the
    genuine ``MemoryVectorIndex`` so the vector-index snapshot leg can catch a
    non-idempotent double-insert. Only the embeddings client and identity are
    stubbed.
    """
    from app.indexer import consumer as consumer_module

    class _FakeEmbedder:
        identity = _STUB_IDENTITY

        def embed_text(self, _text: str) -> list[float]:
            return list(_STUB_VECTOR)

    monkeypatch.setattr(consumer_module, "get_embeddings_client", lambda _intent: _FakeEmbedder())
    monkeypatch.setattr(consumer_module, "get_embedding_identity", lambda client=None: _STUB_IDENTITY)


def _setup_ingest_object_created(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    _stub_indexer_embeddings(monkeypatch)
    # A real UUID: an invalid one is re-randomized on every call by
    # handle_ingest_object_created's _is_valid_uuid fallback, which would make
    # the object-store state diverge between dispatch 1 and 2 independent of
    # any handler bug (a harness-fixture pitfall, not a handler one).
    return _FixtureResult(
        {
            "uuid": "11111111-1111-1111-1111-111111111111",
            "kind": "note",
            "title": "Fixture Object",
            "content": "hello world",
            "source_ref": "Inbox/fixture-object.md",
        }
    )


def _setup_ingest_vault_changed(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    _stub_indexer_embeddings(monkeypatch)
    _write_layout_note(vault_root)
    note_path = _write_note(
        vault_root,
        "Inbox/fixture-vault-changed.md",
        note_uuid="22222222-2222-2222-2222-222222222222",
        body="Vault-changed fixture body.\n",
    )
    return _FixtureResult(
        {
            "vault_path": str(note_path),
            "relative_path": "Inbox/fixture-vault-changed.md",
            "mtime": 123.0,
            "hash": "fixture-hash",
            "watcher": "harness",
        }
    )


def _setup_ingest_object_deleted(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    """Seed a real vector row for the fixture's object id before dispatch.

    #2944 wired ``handle_ingest_object_deleted`` to purge_vectors for real
    (previously an explicit no-op). Seeding a genuine vector via the real
    ``MemoryVectorIndex`` (not stubbed -- see the module docstring's vector
    index rationale) means dispatch 1 exercises an actual purge (1 row -> 0
    rows) and dispatch 2 exercises the documented redelivery no-op (0 rows,
    ``purge_vectors`` returns 0 without raising) -- both legs of AC2's
    idempotency contract, not a vacuous purge-of-nothing.
    """
    from app.components.embeddings import EmbeddingIdentity
    from app.stores import get_vector_index

    object_id = "33333333-3333-3333-3333-333333333333"
    idx = get_vector_index()
    identity = EmbeddingIdentity(provider="stub", model="stub-model", dim=8, normalize=False)
    idx.upsert(
        UUID(object_id),
        kind="note",
        source_ref="Inbox/deleted.md",
        payload={"title": "Deleted Fixture Note"},
        embedding=list(_STUB_VECTOR),
        model="stub-model",
        identity=identity,
    )
    return _FixtureResult(
        {
            "uuid": object_id,
            "path": str(vault_root / "Inbox" / "deleted.md"),
            "deleted": True,
            "reason": "fixture",
        }
    )


def _setup_panel_scan_requested(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    # No AI-instruction/actions/log fence blocks: find_panels() returns [] so
    # zero panel.intent.created events are emitted (that re-emission gap is
    # #2881's, not duplicated here). This fixture still exercises the real
    # handler: file read, uuid resolution, object upsert, latency-audit emit.
    _write_layout_note(vault_root)
    note_path = _write_note(
        vault_root,
        "Inbox/fixture-panel-scan.md",
        note_uuid="44444444-4444-4444-4444-444444444444",
        body="No AI panel blocks here.\n",
    )
    return _FixtureResult(
        {
            "vault_path": str(note_path),
            "relative_path": "Inbox/fixture-panel-scan.md",
            "mtime": 123.0,
            "hash": "fixture-hash",
            "watcher": "harness",
        }
    )


def _setup_promote_intent_created(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    emitted: list[Any] = []
    # _emit_db_event always calls write_outbox_event(conn=None), which opens a
    # real DB connection (app/services/outbox.py::_open_conn) -- there is no
    # in-memory outbox queue table. Route it through an in-memory recording
    # sink instead of a live Postgres, consistent with driving the real
    # consumer/dedup logic (app.promotion.consumer._handle_promotion_payload)
    # without a live DB dependency. emission_count exposes the recording sink
    # so the harness can assert the dedup gate actually fired (call count
    # stays 1 across both dispatches) instead of comparing two empty JSONL
    # reads.
    monkeypatch.setattr(
        promotion_consumer,
        "_emit_db_event",
        lambda event_type, payload, trace: emitted.append(
            {"event_type": event_type, "payload": payload, "trace": trace}
        ),
    )
    note_path = _write_note(
        vault_root,
        "Inbox/fixture-promote.md",
        note_uuid="55555555-5555-5555-5555-555555555555",
        body="Promotion fixture body.\n",
    )
    return _FixtureResult(
        {
            "note": {
                "uuid": "55555555-5555-5555-5555-555555555555",
                "path": str(note_path),
                "title": "Fixture Promote",
            },
            "maturity": "seed",
            "review_state": "draft",
            "transition": {"family": "promotion", "target_maturity": "seed"},
        },
        emission_count=lambda: len(emitted),
    )


def _setup_note_move_workbench(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    _write_layout_note(vault_root, inbox_folder="Inbox", desk_folder="Workbench")
    note_path = _write_note(
        vault_root,
        "Inbox/fixture-move.md",
        note_uuid="66666666-6666-6666-6666-666666666666",
        body="Move-to-workbench fixture body.\n",
    )
    return _FixtureResult(
        {
            "note_path": str(note_path),
            "note_uuid": "66666666-6666-6666-6666-666666666666",
            "params": {"destination_zone": "workbench"},
            "action_id": "fixture-move-action",
        }
    )


def _domain_object_for_embedding(object_uuid: str):
    from datetime import datetime, timezone

    from app.objects import DomainObject

    return DomainObject(
        uuid=object_uuid,
        kind="note",
        payload={"content": "embed me", "text": "embed me"},
        source_ref="Inbox/fixture-embed.md",
        created_at=datetime.now(timezone.utc),
    )


def _setup_index_embedding_requested(vault_root: Path, monkeypatch: pytest.MonkeyPatch) -> _FixtureResult:
    _stub_consumer_embeddings(monkeypatch)
    object_uuid = "77777777-7777-7777-7777-777777777777"
    ObjectStore().save_object(_domain_object_for_embedding(object_uuid), emit_outbox=False)
    return _FixtureResult({"object_id": object_uuid})


TOPIC_FIXTURES: dict[str, _TopicFixture] = {
    "ingest.object.created": _TopicFixture(
        "ingest.object.created",
        _setup_ingest_object_created,
        emission=_EmissionExpectation.KNOWN_NONIDEMPOTENT_2881,
    ),
    "ingest.vault.changed": _TopicFixture(
        "ingest.vault.changed",
        _setup_ingest_vault_changed,
        emission=_EmissionExpectation.KNOWN_NONIDEMPOTENT_2881,
    ),
    "ingest.object.deleted": _TopicFixture(
        "ingest.object.deleted",
        _setup_ingest_object_deleted,
        # #2944: the handler now purges the durable vector-index row for real
        # (durable-state leg), but it still emits no outbox events of its own
        # -- purely a vector-index mutation, no notification/audit emission.
        emission=_EmissionExpectation.ZERO_BY_DESIGN,
    ),
    "panel.scan.requested": _TopicFixture(
        "panel.scan.requested",
        _setup_panel_scan_requested,
        emission=_EmissionExpectation.KNOWN_NONIDEMPOTENT_2881,
    ),
    "promote.intent.created": _TopicFixture(
        "promote.intent.created",
        _setup_promote_intent_created,
        # event_id-keyed dedup (_PROMOTION_DEDUP); emits on dispatch 1, deduped
        # on dispatch 2. Non-vacuity enforced via emission_count > 0.
        emission=_EmissionExpectation.IDEMPOTENT,
    ),
    "note.move.workbench": _TopicFixture(
        "note.move.workbench",
        _setup_note_move_workbench,
        # Handler emits no outbox events (its only durable side effects are the
        # vault file move + an in-note receipt, both covered by the vault leg).
        emission=_EmissionExpectation.ZERO_BY_DESIGN,
    ),
    "index.embedding.requested": _TopicFixture(
        "index.embedding.requested",
        _setup_index_embedding_requested,
        emission=_EmissionExpectation.KNOWN_NONIDEMPOTENT_2881,
    ),
}


def test_every_topic_has_a_fixture() -> None:
    """A registered dispatch topic with no fixture must fail loud, never skip silently."""
    dispatched = set(_dispatched_topics())
    assert len(dispatched) >= 7, f"expected at least the 7 known dispatch topics, got {dispatched}"
    assert dispatched == set(TOPIC_FIXTURES), (
        "TOPIC_FIXTURES must cover exactly the live _dispatch_topic table -- "
        f"dispatched={sorted(dispatched)} fixtures={sorted(TOPIC_FIXTURES)}. "
        "Add a TOPIC_FIXTURES entry for any new topic before it can ship."
    )


def test_string_literal_dispatch_branch_is_enumerated() -> None:
    """A dispatch branch keyed on a string literal is enumerated, not silently missed.

    Regression guard for the AST enumerator: an earlier version only recognized
    ``ast.Name`` comparators, so a future ``elif topic == "some.literal":`` branch
    would be invisible and that topic could ship with zero idempotency coverage
    while ``test_every_topic_has_a_fixture`` stayed green. This drives the shared
    ``_enumerate_topic_comparators`` against a synthetic dispatch function mixing
    a module-constant branch and a string-literal branch, asserting BOTH are
    resolved.
    """
    synthetic_source = (
        "def _dispatch(topic):\n"
        "    if topic == KNOWN_CONSTANT_TOPIC:\n"
        "        pass\n"
        "    elif topic == 'inline.literal.topic':\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
    )
    resolved = _enumerate_topic_comparators(
        synthetic_source, {"KNOWN_CONSTANT_TOPIC": "known.constant.topic"}
    )
    assert resolved == ["known.constant.topic", "inline.literal.topic"], (
        "the enumerator must resolve both a module-constant branch and a string-literal branch; "
        f"got {resolved}"
    )


# ---------------------------------------------------------------------------
# Durable-state snapshotting: store rows (memory ObjectStore), vector index
# (real MemoryVectorIndex), and vault filesystem tree -- the three legs that
# must converge for every topic. Emitted outbox events (JSONL audit log) are
# captured too but asserted separately per the topic's _EmissionExpectation.
# ---------------------------------------------------------------------------


def _snapshot_object_store() -> dict[str, Any]:
    return {
        uuid: (obj.kind, obj.source_ref, json.dumps(obj.payload, sort_keys=True, default=str))
        for uuid, obj in object_store_module._MEMORY_STORE.items()
    }


def _snapshot_vector_index() -> dict[str, Any]:
    """Snapshot the real (memory-backend) vector index, keyed by object_id.

    Reads the genuine ``MemoryVectorIndex.all_rows()`` (the vector index is NOT
    stubbed -- see _stub_indexer_embeddings/_stub_consumer_embeddings), so a
    handler that double-inserts or otherwise mutates a vector row on the second
    dispatch is caught here. Keyed by object_id with the full stored row
    (kind/source_ref/payload/embedding) as the value -- a duplicate row, a
    changed embedding, or a changed payload all show up as a diff.
    """
    try:
        idx = get_vector_index()
    except Exception:  # pragma: no cover - only if backend resolution fails
        return {}
    all_rows = getattr(idx, "all_rows", None)
    if all_rows is None:  # pragma: no cover - MemoryVectorIndex always has it
        return {}
    snapshot: dict[str, Any] = {}
    for row in all_rows():
        object_id = str(row.get("object_id"))
        snapshot[object_id] = json.dumps(
            {
                "kind": row.get("kind"),
                "source_ref": row.get("source_ref"),
                "payload": row.get("payload"),
                "embedding": row.get("embedding"),
            },
            sort_keys=True,
            default=str,
        )
    return snapshot


def _snapshot_vault_tree(vault_root: Path) -> dict[str, str]:
    """Hash every vault file except the companion-note ingest timestamp field.

    ``handle_ingest_vault_changed`` writes ``CompanionNote.last_ingested`` as a
    fresh wall-clock value on every call (app/services/companion_note.py) --
    an intentional "when was this last observed" field, not semantic drift.
    Excluding just that one line keeps the assertion meaningful (it still
    catches a genuine content_hash/frontmatter change) without failing on a
    field that is designed to always differ.
    """
    snapshot: dict[str, str] = {}
    if not vault_root.exists():
        return snapshot
    for path in sorted(vault_root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(vault_root))
        raw = path.read_bytes()
        if "/companions/" in rel and rel.endswith(".md"):
            text = raw.decode("utf-8", errors="replace")
            lines = [line for line in text.splitlines() if not line.startswith("last_ingested:")]
            raw = "\n".join(lines).encode("utf-8")
        snapshot[rel] = hashlib.sha256(raw).hexdigest()
    return snapshot


def _snapshot_outbox_jsonl(outbox_path: Path) -> list[str]:
    if not outbox_path.exists():
        return []
    return [line for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _DurableSnapshot:
    def __init__(
        self,
        *,
        store: dict[str, Any],
        vector_index: dict[str, Any],
        vault: dict[str, str],
        outbox_events: list[str],
    ) -> None:
        self.store = store
        self.vector_index = vector_index
        self.vault = vault
        self.outbox_events = outbox_events

    def durable_state_matches(self, other: "_DurableSnapshot") -> bool:
        """The three "durable state" legs the spec names: store rows, vector index, vault writes.

        (``docs/RUNTIME_CORRECTNESS_KERNEL/HANDLER_IDEMPOTENCY_HARNESS.md`` names
        objects/file_state/vector index + vault writes; emitted outbox events are
        asserted separately per the topic's _EmissionExpectation.)
        """
        return (
            self.store == other.store
            and self.vector_index == other.vector_index
            and self.vault == other.vault
        )

    def diff_durable_state(self, other: "_DurableSnapshot") -> str:
        parts = []
        if self.store != other.store:
            parts.append(f"store changed: before={self.store!r} after={other.store!r}")
        if self.vector_index != other.vector_index:
            parts.append(f"vector index changed: before={self.vector_index!r} after={other.vector_index!r}")
        if self.vault != other.vault:
            parts.append(f"vault changed: before={self.vault!r} after={other.vault!r}")
        return "; ".join(parts)


def _take_snapshot(vault_root: Path, outbox_path: Path) -> _DurableSnapshot:
    return _DurableSnapshot(
        store=_snapshot_object_store(),
        vector_index=_snapshot_vector_index(),
        vault=_snapshot_vault_tree(vault_root),
        outbox_events=_snapshot_outbox_jsonl(outbox_path),
    )


@pytest.fixture(autouse=True)
def _reset_dispatch_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset every global durable-state singleton the dispatch table touches.

    ``_MEMORY_STORE`` (app/objects), the store-backend lru_cache singletons
    (app/stores), the worker's in-memory ``_EventDedup`` cache, and the
    promotion consumer's ``_PROMOTION_DEDUP`` cache are module-level globals --
    each test must start from a clean slate so dispatch 1 vs dispatch 2 diffs
    are not polluted by a prior test/topic, and so promote.intent.created's
    dedup gate is exercised freshly by this test's own event_id rather than
    short-circuiting on a stale one from a previous test.
    """
    from app.stores import reset_store_backends

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    object_store_module._MEMORY_STORE.clear()
    reset_store_backends()
    outbox_worker._EVENT_DEDUP._seen.clear()
    promotion_consumer.reset_promotion_dedup_store()
    yield
    object_store_module._MEMORY_STORE.clear()
    reset_store_backends()
    outbox_worker._EVENT_DEDUP._seen.clear()
    promotion_consumer.reset_promotion_dedup_store()


@pytest.mark.parametrize("topic", sorted(TOPIC_FIXTURES))
def test_dispatch_twice_is_idempotent(
    topic: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dispatching ``topic`` twice via the real _dispatch_topic entrypoint changes no durable state.

    Drives ``app.workers.outbox_worker._dispatch_topic`` directly (the shared
    production dispatch entrypoint used by both ``run_once`` and the daemon
    ``run()`` loop) rather than a per-handler helper, per the Issue's Verify:
    marker. Store rows and vault filesystem writes must converge for every
    topic. Emitted outbox events must converge too, except for the four topics
    where that is a known, separately-tracked gap (#2881, see module
    docstring) -- those assert the actual current (non-convergent) behavior so
    a future fix is a visible, intentional test change, not a silent
    assumption this harness overlooked.
    """
    fixture = TOPIC_FIXTURES[topic]
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    outbox_path = tmp_path / "outbox_audit.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    fixture_result = fixture.setup(vault_root, monkeypatch)
    payload = fixture_result.payload

    # Same event_id across both dispatches, mirroring a real at-least-once
    # redelivery of the same outbox row (event.event_id threads through
    # _dispatch_topic's `event_id` kwarg via _event_id_from_message).
    envelope = new_event(event_type=fixture.event_type, payload=dict(payload))
    message: dict[str, Any] = {
        "id": "harness-row-1",
        "topic": topic,
        "payload": payload,
        "event": envelope,
        "timestamp": envelope.created_at,
    }
    trace_id = "harness-trace"
    event_id = outbox_worker._event_id_from_message(message)

    def _dispatch_once() -> None:
        outbox_worker._dispatch_topic(
            topic,
            payload,
            trace_id=trace_id,
            message=message,
            event_id=event_id,
        )

    _dispatch_once()
    after_first = _take_snapshot(vault_root, outbox_path)
    emission_count_after_first = (
        fixture_result.emission_count() if fixture_result.emission_count is not None else None
    )

    _dispatch_once()
    after_second = _take_snapshot(vault_root, outbox_path)
    emission_count_after_second = (
        fixture_result.emission_count() if fixture_result.emission_count is not None else None
    )

    # Durable state = store rows + vector index + vault writes (the three legs
    # the spec names). Must converge across both dispatches for every topic.
    assert after_first.durable_state_matches(after_second), (
        f"topic {topic!r} is NOT idempotent on durable state (store/vector-index/vault): "
        f"dispatching twice changed state that must converge under I-E2. "
        f"{after_first.diff_durable_state(after_second)}"
    )

    # Emitted-outbox-events leg: asserted per the topic's declared expectation,
    # never a silent empty-list compare.
    if fixture.emission is _EmissionExpectation.IDEMPOTENT:
        assert emission_count_after_first is not None, (
            f"topic {topic!r} is marked IDEMPOTENT but its fixture supplied no emission_count -- "
            "an IDEMPOTENT topic must report a real (non-vacuous) emission count."
        )
        assert emission_count_after_first > 0, (
            f"topic {topic!r} is marked IDEMPOTENT but emitted zero events on the first dispatch -- "
            "the convergence assertion would be vacuous. Fix the fixture to exercise the emission "
            "path, or re-classify the topic as ZERO_BY_DESIGN."
        )
        assert emission_count_after_second == emission_count_after_first, (
            f"topic {topic!r} was expected to dedup emission on the second dispatch (e.g. via "
            f"event_id-keyed dedup) but emission count grew: "
            f"first={emission_count_after_first} second={emission_count_after_second}"
        )
        assert after_first.outbox_events == after_second.outbox_events, (
            f"topic {topic!r} IDEMPOTENT: the JSONL outbox-event log grew on the second dispatch: "
            f"before={after_first.outbox_events!r} after={after_second.outbox_events!r}"
        )
    elif fixture.emission is _EmissionExpectation.ZERO_BY_DESIGN:
        # Assert the zero explicitly, both dispatches -- not a silent []==[].
        assert after_first.outbox_events == [] and after_second.outbox_events == [], (
            f"topic {topic!r} is marked ZERO_BY_DESIGN but emitted outbox events "
            f"(first={after_first.outbox_events!r} second={after_second.outbox_events!r}) -- "
            "re-classify it as IDEMPOTENT (and assert convergence) or KNOWN_NONIDEMPOTENT_2881."
        )
        if emission_count_after_first is not None:
            assert emission_count_after_first == 0 and emission_count_after_second == 0, (
                f"topic {topic!r} ZERO_BY_DESIGN reported non-zero emissions via its side channel: "
                f"first={emission_count_after_first} second={emission_count_after_second}"
            )
    else:  # _EmissionExpectation.KNOWN_NONIDEMPOTENT_2881
        # Known gap (#2881): the audit-emission layer appends unconditionally
        # with a fresh event_id, so the second dispatch grows the outbox-event
        # log. Assert the actual current behavior (net new lines) rather than
        # silently ignoring this dimension -- a fix for #2881 should re-classify
        # this topic as IDEMPOTENT and this branch will then fail loud until the
        # classification is updated.
        assert len(after_second.outbox_events) > len(after_first.outbox_events), (
            f"topic {topic!r} is marked KNOWN_NONIDEMPOTENT_2881 but no new outbox events were "
            "emitted on the second dispatch -- if this handler was fixed, re-classify it as "
            "IDEMPOTENT instead of leaving this assertion stale."
        )
