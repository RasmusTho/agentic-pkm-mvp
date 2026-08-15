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
# (11 production sites verified against `main` @ #2909 implementation time,
# plus a 12th added mid-delivery by KA-01 #2928: the pre-pipeline immutable
# raw record -- formal-model.md's C8 row predates KA-01).
# `app/cli/smoke.py` sites are dev/CI harness writers, structurally excluded
# from the formal model's Σ by declaration (formal-model.md §2.3) and MUST
# NEVER run against a real vault -- they are not part of this census.

REGISTERED_MIRRORS: dict[tuple[str, int], str] = {
    ("app/services/indexer.py", 176): (
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
    ("app/watcher/vault_watcher.py", 247): (
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
    ("app/agents/normalizer/agent.py", 165): (
        "normalize_file's run(): legacy normalizer ingest shim used by classifier/"
        "normalizer test flows and the memory-backend CLI path; the object's creation "
        "event is emitted by the caller (ingest API / vault_alpha) that invokes normalize."
    ),
    ("app/ingest/api.py", 167): (
        "Programmatic ingest helper app.ingest.api.ingest_object. This is NOT the POST /ingest "
        "route -- that goes through app/api/routes/ingest.py::insert_object_and_outbox, and "
        "app.search.service.ingest_object is a third, distinct function that every real call "
        "site uses. This helper has no caller in app/ outside the app/ingest/__init__.py "
        "re-export; the earlier justification here claimed the API path and was wrong "
        "(corrected by #4178). emit_outbox=False is correct on its own terms: this helper "
        "models no creation event at all -- it emits index.embedding.requested itself and "
        "leaves object creation unannounced, so there is no duplicate ingest.object.created "
        "to suppress. "
        "Line drifted 118 -> 167 (site unchanged); re-pinned by #4178, which replaced the "
        "hardcoded _EMBED_MODEL phantom with the _requested_embedding_identity() resolver "
        "defined above this call."
    ),
    ("app/ingest/vault_alpha.py", 569): (
        "Legacy vault-alpha ingest path: keeps classifier/normalizer flows working "
        "against the memory backend during tests/alpha runs; the alpha ingest pipeline "
        "emits its own ingest event upstream of this call in the same run. Line drifted "
        "527 -> 555 -> 582 -> 558 (site unchanged); re-pinned by #3180 (ERE-05) -- round-3 "
        "extracted the episode_ref helper into app/ingest/episode_ref.py, shifting this line "
        "back up. The census gate only fires when this machinery is touched, so the drift "
        "surfaces on the first PR to edit this file."
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
def spy_on_object_store(monkeypatch: pytest.MonkeyPatch, spy: EventSpy) -> Iterator[EventSpy]:
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


# ===========================================================================
# P-3 read-purity (#2911) -- APPEND-ONLY BLOCK, own section
# ===========================================================================
#
# Everything below this marker belongs to P-3 (issue #2911). Do not interleave
# P-1/P-4 seam-register or guard-stub material (#2910) into this section --
# that is a sibling concurrently-delivered block; keep edits confined to this
# one and expect a possible trivial rebase before merge.
#
# Derivation: ``docs/testing/invariant-synthesis-2026-07.md :: P-3`` (on
# ``main`` since PR #2915 -- no anchor drift) and
# ``docs/architecture/formal-model.md`` §3 invariant Q4 ("Read purity").
#
# Q4 is violated three ways today, all deliberately legal per the model's own
# verdict ("the *undocumented* ones are the defect, not healing itself"):
#
#   1. uuid-heal reachable from ``GET /api/companion/workspace``: the real,
#      correctly WriteGuard-gated write chain is
#      ``app.services.artifact_identity.resolve_note_artifact_identity``
#      (heal_missing_uuid=True by default) -> ``app.services.note_uuid
#      .ensure_note_uuid`` -> ``DEFAULT_WRITE_GUARD.assert_writes_allowed
#      ("ensure uuid")`` -> ``app.knowledge.write_ops.write_note_from_absolute``.
#      (The `_writeguard_status()` helper in
#      ``app/api/routes/companion.py`` that calls ``assert_writes_allowed(
#      "companion.workspace.read")`` is a read-side health probe for a
#      response field, NOT the write gate for this heal -- it is not
#      registered as a heal transition because it never writes.)
#   2. lazy identity-heal on vault load: ``VaultManager.load_last_active``
#      (``app/vault/manager.py``) -> ``select_vault`` -> ``validate_vault``
#      -> ``_ensure_frontmatter_id`` -> ``markdown_store.write_frontmatter``,
#      gated only by role-based ``persist`` flags (``allow_shared_identity_heal``
#      / ``allow_local_identity_heal``), NOT by WriteGuard -- this asymmetry
#      with case 1 is intentional per the model and is pinned as-is (Out of
#      Scope: "changing heal behavior").  Reachable from many GET routes that
#      resolve the active vault on a cold manager (``_companion_vault_context_
#      with_lazy_last_active`` in ``companion.py``; the independent lazy-load
#      in ``app/api/routes/vault_resolution.py``), guarded so it only fires
#      once per manager instance (``_LAST_ACTIVE_LOAD_ATTEMPTED_ATTR``).
#   3. ASK's receipt appends to advisory J-sinks: ``POST /api/ask`` (not a GET
#      route -- excluded from the route-walk by construction, ``"GET" not in
#      route.methods``) drives ``app.agent_memory.recall_activation
#      ._emit_recall_receipt`` (J.recall) and ``app.activation.ask_synthesis
#      .emit_ask_synthesis_receipt`` (J.synthesis), both durable JSONL
#      append-only sinks reached from a nominal "read" per the model. Recorded
#      here as the registered advisory-sink list for completeness of the
#      catalog even though POST routes are outside this property's route-walk.

# Closed registry: (module_path, function_qualname) -> justification. Every
# durable write reachable from a GET route must either be absent, or its
# seam must appear here with a WriteGuard-gated=True/False classification and
# a one-line justification -- mirroring REGISTERED_MIRRORS' closed-set shape.
# The write CLASS (not the route path) is the registration key because the
# same heal seam is reachable from several GET routes (documented per-entry).


@dataclass(frozen=True)
class HealTransition:
    """One registered, legal durable write reachable from a GET/read route."""

    seam: str  # "module.path::qualname" of the actual write call site
    wg_gated: bool  # True iff WriteGuard.assert_writes_allowed guards this seam
    justification: str
    example_get_routes: tuple[str, ...]


REGISTERED_HEAL_TRANSITIONS: dict[str, HealTransition] = {
    "app.services.note_uuid::ensure_note_uuid": HealTransition(
        seam="app.services.note_uuid::ensure_note_uuid",
        wg_gated=True,
        justification=(
            "T-uuid-heal (formal-model.md Q4, case 1): heals a note missing "
            "frontmatter.uuid on first read via resolve_note_artifact_identity. "
            'WG-gated at the seam (assert_writes_allowed("ensure uuid")) -- a '
            "denying guard degrades to identity_state=unresolved_missing_uuid "
            "instead of writing, per note_uuid.py / artifact_identity.py."
        ),
        example_get_routes=("/api/companion/workspace",),
    ),
    "app.vault.manager::VaultManager._ensure_frontmatter_id": HealTransition(
        seam="app.vault.manager::VaultManager._ensure_frontmatter_id",
        wg_gated=False,
        justification=(
            "Lazy identity-heal (formal-model.md Q4, case 2): vaultId/"
            "localInstanceId healed during validate_vault on the first "
            "cold-manager load_last_active(). Gated only by role-based "
            "persist flags (allow_shared_identity_heal / "
            "allow_local_identity_heal), NOT WriteGuard -- this is the "
            "documented asymmetry with case 1; pinned as current reality, "
            "not changed by this issue (Out of Scope)."
        ),
        example_get_routes=(
            "/api/companion/workspace",
            "/api/companion/now",
            "/api/companion/vault/context",
            "/api/companion/vault/notes",
            "/api/companion/memory/review-queue",
        ),
    ),
    "app.instance.vault_registry::AppLocalSettingsStore.save": HealTransition(
        seam="app.instance.vault_registry::AppLocalSettingsStore.save",
        wg_gated=False,
        justification=(
            "App-local registry bootstrap-on-first-read: AppLocalSettingsStore"
            ".load() creates the missing .app-local.md file with a fresh "
            "appInstallId the first time any GET route triggers "
            "VaultManager.load_last_active() on a cold manager (the instance "
            "registry compatibility store "
            "load() calling self.save() when self.path does not exist yet). "
            "Not WriteGuard-gated -- found by this property's route-walk "
            "(previously undocumented, a genuine new Q4 instance this issue "
            "pins as current reality rather than changes, per Out of Scope)."
        ),
        example_get_routes=(
            "/api/companion/workspace",
            "/api/companion/now",
            "/api/companion/vault/context",
        ),
    ),
}

# Registered advisory J-sink append list (formal-model.md Q4, case 3). These
# are durable append-only writes from a nominal "read" transition (T-ask), but
# T-ask is a POST route and therefore never appears in this property's GET
# route-walk. Recorded here so the read-purity catalog documents all three
# known Q4 violations explicitly, per the issue scope, even though only cases
# 1-2 are reachable from (and therefore asserted against) the GET route-walk.
REGISTERED_ADVISORY_J_SINKS: dict[str, str] = {
    "app.agent_memory.recall_activation::_emit_recall_receipt": (
        "J.recall receipt append (advisory, FD-J, losable by declaration); "
        "reached only via POST /api/ask -> ask graph recall node, never a "
        "GET route."
    ),
    "app.activation.ask_synthesis::emit_ask_synthesis_receipt": (
        "J.synthesis receipt append (advisory, FD-J, losable by declaration); "
        "reached only via POST /api/ask -> ask graph synthesis node, never a "
        "GET route."
    ),
}


# =============================================================================
# APPEND-ONLY SECTION -- P-1/P-4 guard-at-seam machinery (#2910)
# =============================================================================
#
# Everything below this banner belongs to #2910 (P-1 `guard_asserted_at_write_
# seam` / P-4 `guards_fail_closed`). Keep additions inside this section so a
# concurrent sibling (#2911, heal-transition/advisory-sink machinery) rebases
# cleanly against the P-2 section above. Do not reorder or interleave with
# the P-2 content above the banner.
#
# Derivation: docs/testing/invariant-synthesis-2026-07.md :: P-1, P-4;
# docs/architecture/formal-model.md §3 gap 1 / gap 4, §7 F-A..F-F.

from dataclasses import dataclass as _dataclass  # noqa: E402
from typing import Callable as _Callable  # noqa: E402

# ---------------------------------------------------------------------------
# Registered write-frontmatter census (closed, justified exception set)
# ---------------------------------------------------------------------------
#
# ``MarkdownSettingsStore.write_frontmatter`` is a SECOND vault-write primitive
# alongside the knowledge port (``write_note_from_absolute``) -- it does not
# route through the port at all, so the port's own guard-at-seam assertion
# (#2910) does not cover it. Every production call site is listed here with
# its guard classification, so a new caller cannot silently add an unguarded
# frontmatter write. This is a closed set: adding a new call site requires a
# reviewed classification in the same PR, mirroring REGISTERED_MIRRORS' rule.
#
# Classifications:
#   "guarded"      -- the call site (or its direct, same-transition caller) is
#                      already covered by an ``assert_writes_allowed`` in the
#                      same seam module -- verified against `main` @ #2910.
#   "out_of_scope" -- writes a store outside the vault content plane Sigma
#                      (formal-model.md §2.3), e.g. the app-local device
#                      registry, not a Human Knowledge Artifact.
WRITE_FRONTMATTER_SITE_CLASSIFICATION: dict[tuple[str, int], str] = {
    ("app/ports/filesystem_vault_adapter.py", 57): (
        "guarded: FilesystemVaultAdapter.ensure_uuid calls this class's OWN "
        "write_frontmatter method (line 78), which routes through "
        "write_note_from_absolute (the knowledge port, line 99) -- covered by "
        "the port's own guard-at-seam assertion (#2910), not the "
        "MarkdownSettingsStore primitive this census is otherwise about. "
        "Line drifted 44 -> 45 -> 57 (site unchanged); re-pinned per this "
        "census's own directly-related-repair convention when #3451 bound "
        "write_frontmatter to the exact NoteRead version."
    ),
    ("app/vault/manager.py", 843): (
        "guarded: _ensure_frontmatter_id asserts DEFAULT_WRITE_GUARD."
        "assert_writes_allowed('vault.identity_heal') immediately before this "
        "call (#2910 identity-heal fix); a denying/raising guard raises before "
        "reaching this line. Line drifted 716 -> 841 -> 843 (site unchanged) when "
        "#3452 added conflict-quarantine receipt policy above the manager."
    ),
    ("app/vault/settings_service.py", 617): (
        "guarded: SettingsService.update_setting asserts "
        "DEFAULT_WRITE_GUARD.assert_writes_allowed(_SETTINGS_WRITE_ACTION) "
        "earlier in the same method before persist=True reaches this write. "
        "Line drifted 348 -> 508 -> 589 -> 614 -> 616 -> 617 (site unchanged); re-pinned per this census's "
        "own directly-related-repair convention when YSS-01 (#3916) added the "
        "youtubeSync.* SettingDefinitions and the scaffold action constant "
        "earlier in the file."
    ),
    ("app/instance/vault_registry.py", 2503): (
        "out_of_scope: AppLocalSettingsStore persists the app-local device "
        "registry (default_app_local_settings_path(), typically an XDG data "
        "dir) -- a machine-local app config store outside the vault content "
        "plane Sigma (formal-model.md sec 2.3), not a Human Knowledge Artifact. "
        "Line drifted 1373 -> 1394 -> 1403 -> 1953 -> 2266 -> 2330 -> 2357 -> 2496 -> 2503 "
        "(site unchanged); re-pinned after directly related MVR-05A6 (#4580) inserted "
        "the validated binding-effect lease producer earlier in vault_registry.py. "
        "MVR-05A6 adds no new "
        "write_frontmatter site: like MVR-02/MVR-04, it writes the registry through "
        "_atomic_private_write, "
        "not the vault-content seam."
    ),
}

# ``MarkdownSettingsStore.write_missing`` is a distinct O_EXCL vault-write
# primitive. It is intentionally available to explicit vault bootstrap, while
# post-init scaffolding must be guarded by its direct caller. Keep the census
# closed so moving a write from ``write_frontmatter`` cannot make it disappear
# from the WriteGuard inventory.
WRITE_MISSING_SITE_CLASSIFICATION: dict[tuple[str, int], str] = {
    ("app/vault/manager.py", 623): (
        "bootstrap: VaultManager.initialize_vault is the explicit human/operator "
        "pre-selection initialization transition; O_EXCL preserves existing owner files. "
        "Line drifted 496 -> 621 -> 623 (site unchanged) when #3164 added the "
        "nested canonical prompt seed and #3452 added "
        "conflict-quarantine receipt policy above the manager."
    ),
    ("app/vault/settings_service.py", 696): (
        "guarded: _scaffold_missing_settings_file asserts DEFAULT_WRITE_GUARD."
        "assert_writes_allowed(_SETTINGS_SCAFFOLD_ACTION) before the O_EXCL scaffold call."
    ),
}


@dataclass
class DurableWriteCall:
    """One recorded call into a durable-write primitive during a GET request."""

    seam: str
    caller: str
    args_repr: str


def _immediate_caller_qualname() -> str:
    """Best-effort ``module::qualname`` of the function that invoked the
    wrapped primitive, walking past this module's own spy frames.

    This is what makes the spy attribute writes to the REAL call site that
    reached the primitive (e.g. ``app.services.note_uuid::ensure_note_uuid``)
    rather than to the primitive itself -- a direct, out-of-band call to the
    same primitive (as the fixture-proven negative test does) is honestly
    attributed to ITS OWN caller and is therefore correctly unregistered.
    """
    import inspect

    frame = inspect.currentframe()
    try:
        # Skip this function's own frame, then the immediate `traced_*`
        # wrapper frame in this module -- the next frame up is the real caller.
        outer = frame.f_back.f_back if frame and frame.f_back else None
        if outer is None:
            return "<unknown>"
        module_name = outer.f_globals.get("__name__", "<unknown>")
        qualname = (
            outer.f_code.co_qualname
            if hasattr(outer.f_code, "co_qualname")
            else outer.f_code.co_name
        )
        return f"{module_name}::{qualname}"
    finally:
        del frame


@dataclass
class WriteSpy:
    """Records every real production call into the two durable-write
    primitives P-3 cares about, calling straight through to the original
    implementation (spy, not stub/fake) -- mirrors ``EventSpy``'s shape.

    Wraps:
      - ``app.vault.markdown_settings.MarkdownSettingsStore.write_frontmatter``
        (the lazy identity-heal write primitive, case 2)
      - ``app.knowledge.write_ops.write_note_from_absolute`` (the uuid-heal
        write primitive, case 1)

    Each recorded call's ``seam`` is the REAL CALLER that reached the
    primitive (introspected from the stack), not the primitive's own name --
    so a registered heal is registered by "who legitimately reaches this
    write", and a new/unexpected caller of the same primitive is correctly
    unregistered (the fixture-proven negative in
    ``test_read_purity.py::test_unregistered_route_write_fails`` depends on
    this attribution).
    """

    calls: list[DurableWriteCall] = field(default_factory=list)

    def record(self, seam: str, caller: str, args_repr: str) -> None:
        self.calls.append(DurableWriteCall(seam=seam, caller=caller, args_repr=args_repr))

    def seams_hit(self) -> frozenset[str]:
        return frozenset(call.caller for call in self.calls)


@contextmanager
def spy_on_durable_writes(monkeypatch: pytest.MonkeyPatch, spy: WriteSpy) -> Iterator[WriteSpy]:
    """Wrap the REAL write-primitive seams with recording spies that still
    delegate to the original implementation -- observe, don't fake."""
    import app.vault.markdown_settings as markdown_settings_mod
    import app.knowledge.write_ops as write_ops_mod

    original_write_frontmatter = markdown_settings_mod.MarkdownSettingsStore.write_frontmatter
    original_write_missing = markdown_settings_mod.MarkdownSettingsStore.write_missing
    original_write_note_from_absolute = write_ops_mod.write_note_from_absolute

    def traced_write_frontmatter(
        self: Any, path: Any, frontmatter: Any, *, body: Any = None
    ) -> Any:
        spy.record(
            seam="app.vault.markdown_settings::MarkdownSettingsStore.write_frontmatter",
            caller=_immediate_caller_qualname(),
            args_repr=f"path={path!r}",
        )
        return original_write_frontmatter(self, path, frontmatter, body=body)

    def traced_write_missing(
        self: Any, path: Any, frontmatter: Any, body: Any
    ) -> Any:
        spy.record(
            seam="app.vault.markdown_settings::MarkdownSettingsStore.write_missing",
            caller=_immediate_caller_qualname(),
            args_repr=f"path={path!r}",
        )
        return original_write_missing(self, path, frontmatter, body)

    def traced_write_note_from_absolute(
        path: Any, content: Any, *, vault_root: Any, **kwargs: Any
    ) -> Any:
        spy.record(
            seam="app.knowledge.write_ops::write_note_from_absolute",
            caller=_immediate_caller_qualname(),
            args_repr=f"path={path!r}",
        )
        return original_write_note_from_absolute(path, content, vault_root=vault_root, **kwargs)

    monkeypatch.setattr(
        markdown_settings_mod.MarkdownSettingsStore, "write_frontmatter", traced_write_frontmatter
    )
    monkeypatch.setattr(
        markdown_settings_mod.MarkdownSettingsStore, "write_missing", traced_write_missing
    )
    monkeypatch.setattr(write_ops_mod, "write_note_from_absolute", traced_write_note_from_absolute)
    # note_uuid.py imported write_note_from_absolute directly into its module
    # namespace, so patch the reference actually called from ensure_note_uuid.
    import app.services.note_uuid as note_uuid_mod

    monkeypatch.setattr(note_uuid_mod, "write_note_from_absolute", traced_write_note_from_absolute)
    yield spy


@pytest.fixture
def write_spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[WriteSpy]:
    spy = WriteSpy()
    with spy_on_durable_writes(monkeypatch, spy):
        yield spy


def find_write_frontmatter_call_sites(root: Path = APP_ROOT) -> list[tuple[str, int]]:
    """AST-scan ``app/**/*.py`` for ``*.write_frontmatter(...)`` call sites.

    Matches any attribute call named ``write_frontmatter`` (the method lives on
    ``MarkdownSettingsStore``; production callers reach it via
    ``self.markdown_store.write_frontmatter(...)`` or equivalent), excluding
    the method's own ``def`` site. Deliberately returns every site with no
    filtering -- classification against
    ``WRITE_FRONTMATTER_SITE_CLASSIFICATION`` is the caller's job, so this
    scanner itself cannot become a new escape hatch.
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
            if isinstance(node, ast.FunctionDef) and node.name == "write_frontmatter":
                continue
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "write_frontmatter":
                sites.append((rel, node.lineno))
    return sites


def find_write_missing_call_sites(root: Path = APP_ROOT) -> list[tuple[str, int]]:
    """AST-scan every production ``*.write_missing(...)`` call site."""

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
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "write_missing":
                sites.append((rel, node.lineno))
    return sites


# ---------------------------------------------------------------------------
# Registered write-note-relative census (closed, justified exception set)
# ---------------------------------------------------------------------------
#
# ``write_note_relative`` (``app/knowledge/write_ops.py``) is the relative-path
# sibling of the knowledge port (``write_note_from_absolute``). #2910 only
# guarded the absolute-path port at the seam itself; #2953 closes the same
# gap for this port (the P-1 census gap the issue names: a live unguarded
# caller in ``app/mcp/vault_tools.py`` reached the vault through this helper
# with no WriteGuard anywhere on its call path). Every production call site is
# listed here by stable ``(path, enclosing scope, call ordinal)`` identity, so
# ordinary source-line drift cannot invalidate an unchanged classification and
# a NEW call site added later without port-or-caller coverage
# fails this gate instead of silently shipping the next unguarded-seam
# regression -- mirroring ``WRITE_FRONTMATTER_SITE_CLASSIFICATION``'s shape
# exactly (closed set, one-line justification per entry, checked against
# `main` @ #2953 implementation time).
#
# Classifications:
#   "guarded_by_port"   -- the port itself (``write_note_relative``) now
#                           asserts WriteGuard unconditionally before any I/O
#                           (#2953), so every call site is guarded by
#                           construction regardless of caller-side behavior.
#   "guarded_by_caller" -- in addition to the port guard, the caller ALSO
#                           asserts its own action string caller-side
#                           (defense-in-depth, pre-dates #2953).
WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION: dict[tuple[str, str, int], str] = {
    ("app/chat/session_log.py", "SessionLogWriter.open_session", 1): (
        "guarded_by_caller: SessionLogWriter.open_session asserts "
        "DEFAULT_WRITE_GUARD.assert_writes_allowed(CHAT_SESSION_PERSIST_ACTION) "
        "before resolving identity and preparing the session artifact, in "
        "addition to the port's own guard (#2807)."
    ),
    ("app/briefing/compose.py", "_atomic_write", 1): (
        "guarded_by_caller: compose_briefing asserts write_guard."
        "assert_writes_allowed(BRIEFING_WRITE_ACTION) before the private atomic "
        "staging directory is created, and passes the same guard/action through "
        "to the port's own guard (#3315)."
    ),
    ("app/relevance/materialization.py", "materialize_moment", 1): (
        "guarded_by_caller: materialize_moment asserts write_guard."
        "assert_writes_allowed(MOMENT_MATERIALIZE_ACTION) immediately before "
        "this call, in addition to the port's own guard (#2953)."
    ),
    ("app/agent_memory/materialization.py", "materialize_promoted_memory", 1): (
        "guarded_by_caller: materialize_promoted_memory asserts write_guard."
        "assert_writes_allowed(MEMORY_MATERIALIZATION_ACTION) immediately "
        "before this call, in addition to the port's own guard (#2953)."
    ),
    ("app/agent_memory/provisional_write.py", "write_provisional_memory", 1): (
        "guarded_by_caller: write_provisional_memory asserts write_guard."
        "assert_writes_allowed(PROVISIONAL_MEMORY_WRITE_ACTION) before the "
        "staged receipt and passes the same guard/action to the port, in "
        "addition to the port's own guard (#3719)."
    ),
    ("app/eval/failure_capture.py", "_write_draft", 1): (
        "guarded_by_caller: the shared draft-write helper asserts "
        "write_guard.assert_writes_allowed(FAILURE_CAPTURE_DRAFT_ACTION) "
        "immediately before this call, in addition to the port's own guard "
        "(#2953)."
    ),
    ("app/eval/failure_capture.py", "_decide", 1): (
        "guarded_by_caller: same shared draft-write helper as line 258 "
        "(second draft-kind call site), same caller-side assert plus the "
        "port's own guard (#2953)."
    ),
    ("app/services/commitment_persistence.py", "persist_commitment", 1): (
        "guarded_by_caller: the persistence entrypoint asserts write_guard."
        "assert_writes_allowed(COMMITMENT_PERSIST_ACTION) immediately before "
        "this call, in addition to the port's own guard (#2953)."
    ),
    ("app/mcp/vault_tools.py", "append_note", 1): (
        "guarded_by_port: append_note had NO caller-side WriteGuard assert on "
        "`main` before #2953 (the issue's named live violator) -- now closed "
        "by the port's own unconditional guard-at-seam assertion, exactly the "
        "way #2910 closed the absolute-path port's unguarded sites."
    ),
    ("app/heimdal/entity_register.py", "EntityRegister._write_entry", 1): (
        "guarded_by_caller: EntityRegister._write_entry asserts write_guard."
        "assert_writes_allowed(REGISTER_WRITE_ACTION) immediately before this "
        "call, in addition to the port's own guard (#3038, Epic #3019 A1) -- "
        "classification added by #3034 (A14) as a directly-related repair of "
        "a pre-existing census gap left unregistered by #3038's PR (#3069). "
        "Line drifted 290 -> 297 (site unchanged); re-pinned as a directly-"
        "related repair the first time this census machinery is touched again "
        "after later Heimdal slices shifted the file."
    ),
    ("app/heimdal/settings_notes.py", "write_settings_note", 1): (
        "guarded_by_caller: write_settings_note passes write_guard through to "
        "write_note_relative, which asserts write_guard.assert_writes_allowed"
        "(action) at the port itself before any I/O (#2953); callers such as "
        "apply_agent_update never bypass this seam (#3034, Epic #3019 A14). "
        "Line drifted 531 -> 644 -> 651 (site unchanged; the 644 -> 651 shift "
        "came from an upstream Heimdal change that landed without re-pinning); "
        "re-pinned per this census's own convention as a directly-related "
        "repair the next time the machinery was touched (#3177)."
    ),
    ("app/heimdal/candidate_projection.py", "write_candidate_note", 1): (
        "guarded_by_caller: write_candidate_note asserts write_guard."
        "assert_writes_allowed(CANDIDATE_WRITE_ACTION) immediately before this "
        "call (converting a blocked write into a loud, item-scoped, re-runnable "
        "'blocked' result), in addition to the port's own guard (#3031, Epic "
        "#3019 A11 Mimer projector)."
    ),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note", 1): (
        "guarded_by_caller: write_reading_candidate_note asserts write_guard."
        "assert_writes_allowed(READING_CANDIDATE_WRITE_ACTION) immediately before "
        "this call, in addition to the port's own guard; a blocked caller guard "
        "returns the item-scoped, re-runnable 'blocked' result."
    ),
    ("app/heimdal/time_spend.py", "write_time_spend_note", 1): (
        "guarded_by_port: write_time_spend_note passes write_guard (and the "
        "distinct heimdal.time_spend.write action) through to "
        "write_note_relative, which asserts write_guard.assert_writes_allowed"
        "(action) at the port itself before any I/O (#2953); the caller-side "
        "pre-assert #3345 added was removed by #4609 when the write became an "
        "expected-version compare-and-swap (for this write_note_relative call "
        "site the port guard is the only gate -- the function's create branch "
        "is separately gated by create_candidate_note_once's own assert and "
        "separately registered in the create-once census -- and "
        "WritesBlockedError from it still converts to the loud, "
        "item-scoped, re-runnable 'blocked' result). Re-classified from "
        "guarded_by_caller as a directly-related repair in the same change "
        "that altered the seam, per this census's own convention (#4609)."
    ),
    ("app/heimdal/capture_note.py", "write_capture_note", 1): (
        "guarded_by_port: write_capture_note passes write_guard through to "
        "write_note_relative, which asserts write_guard.assert_writes_allowed"
        "(action) at the port itself before any I/O (#2953); the function's "
        "own monotonic-status check is not a write gate, so port coverage is "
        "what guards this seam (#3035, Epic #3019 A15 capture note / J0)."
    ),
    ("app/episodes/store.py", "write_episode_note", 1): (
        "guarded_by_port: write_episode_note passes write_guard (and the "
        "distinct episodes.write_note action) through to write_note_relative, "
        "which asserts write_guard.assert_writes_allowed(action) at the port "
        "itself before any I/O (#2910/#2953 precedent); no caller-side assert "
        "exists in this module by design -- this IS the production seam ERE-02 "
        "AC2 verifies (#3177). Line drifted 115 -> 203 -> 217 (site unchanged; "
        "the 203 -> 217 shift came from #3450 reading the current note bytes "
        "once to supply an opt-in expected_version); re-pinned per this "
        "census's own directly-related-repair convention (#3450)."
    ),
    ("app/episodes/segmenter.py", "_write_fusion_receipt", 1): (
        "guarded_by_port: _write_fusion_receipt passes write_guard (and the "
        "distinct episodes.cross_scope_fusion_receipt action) through to "
        "write_note_relative, which asserts write_guard.assert_writes_allowed"
        "(action) at the port itself before any I/O -- so a blocked guard writes "
        "neither the fusion receipt nor the fused note (receipt-before-note, "
        "ERE-08 #3183). No caller-side assert by design, mirroring the ERE-02 "
        "store seam above. Line drifted 827 -> 897 (site unchanged; an upstream "
        "episodes-projection sync change grew the module); re-pinned per this "
        "census's own directly-related-repair convention the next time the "
        "machinery was touched (#3329)."
    ),
    ("app/standing_questions/question_store.py", "QuestionStore._write", 1): (
        "guarded_by_caller: QuestionStore._write asserts self.write_guard."
        "assert_writes_allowed(WRITE_ACTION) on the line immediately before this "
        "call (question_store.py:164), before any serialisation, path creation, or "
        "filesystem mutation, and ALSO passes the same guard/action through to the "
        "port's own guard as defense-in-depth (#3329). This is the sole production "
        "write seam for Standing Questions Question notes."
    ),
}


def find_write_note_relative_call_sites(
    root: Path = APP_ROOT, *, repo_root: Path = REPO_ROOT
) -> list[tuple[str, str, int]]:
    """AST-scan ``app/**/*.py`` for ``write_note_relative(...)`` call sites.

    Matches direct-name calls to ``write_note_relative`` (imported by name
    into each caller module, e.g. ``from app.knowledge.write_ops import
    write_note_relative``), excluding the function's own ``def`` site.
    Deliberately returns every site with no filtering -- classification
    against ``WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION`` is the caller's job,
    so this scanner itself cannot become a new escape hatch (#2953, mirrors
    ``find_write_frontmatter_call_sites``).
    """
    sites: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        rel = str(path.relative_to(repo_root))

        class _WriteNoteRelativeVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: list[str] = []
                self.call_counts: dict[str, int] = {}

            def _visit_scope(self, node: ast.AST, name: str) -> None:
                self.scope.append(name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self._visit_scope(node, node.name)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._visit_scope(node, node.name)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._visit_scope(node, node.name)

            def visit_Call(self, node: ast.Call) -> None:
                func = node.func
                is_write_note_relative = (
                    isinstance(func, ast.Name) and func.id == "write_note_relative"
                ) or (isinstance(func, ast.Attribute) and func.attr == "write_note_relative")
                if is_write_note_relative:
                    qualname = ".".join(self.scope) or "<module>"
                    ordinal = self.call_counts.get(qualname, 0) + 1
                    self.call_counts[qualname] = ordinal
                    sites.append((rel, qualname, ordinal))
                self.generic_visit(node)

        _WriteNoteRelativeVisitor().visit(tree)
    return sites


# ---------------------------------------------------------------------------
# Registered write-seam descriptors for the P-1/P-4 runtime property
# ---------------------------------------------------------------------------
#
# Each entry names a real production seam this issue's scope covers, plus a
# zero-argument callable (built by ``invoke_factory``) that drives that seam's
# real write attempt over a fixture. ``given(seam=sampled_from(...))`` (the
# spec's own vocabulary) samples this registry so both P-1 (denying guard ->
# atomic block) and P-4 (raising guard -> fail-closed, loud) exercise every
# named seam identically.


@_dataclass(frozen=True)
class RegisteredWriteSeam:
    name: str
    action: str
    guard_patch_target: str  # dotted path to the WriteGuard instance to patch
    invoke_factory: _Callable[[Path, "pytest.MonkeyPatch"], _Callable[[], None]]
    unchanged_paths: _Callable[[Path], dict[Path, bytes]]


def _knowledge_port_invoke(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> _Callable[[], None]:
    """The knowledge write port itself (#2910 scope item 1)."""
    from app.knowledge.write_ops import write_note_from_absolute

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    note = vault / "seam-note.md"
    note.write_text("original\n", encoding="utf-8")

    def _invoke() -> None:
        write_note_from_absolute(note, "changed\n", vault_root=vault)

    return _invoke


def _knowledge_port_snapshot(tmp_path: Path) -> dict[Path, bytes]:
    vault = tmp_path / "vault"
    return {p: p.read_bytes() for p in sorted(vault.rglob("*")) if p.is_file()}


def _identity_heal_invoke(tmp_path: Path, monkeypatch: "pytest.MonkeyPatch") -> _Callable[[], None]:
    """Identity-heal via ``VaultManager._ensure_frontmatter_id`` (#2910 scope
    item 2) -- the exact seam the issue names ("identity-heal via
    write_frontmatter"), called directly so the raised ``WritesBlockedError``
    carries the guard's real state/reason.

    A companion assertion (``test_identity_heal_blocked_surfaces_as_invalid_
    vault_context`` below) separately pins ``validate_vault``'s own
    except-clause wrapping of that same exception into a loud, non-crashing
    ``VaultContext(status="invalid")`` -- both behaviors matter, but the
    shared P-1/P-4 properties need the seam's own raised error untouched.
    """
    from app.vault.manager import VaultManager

    vault = tmp_path / "vault"
    settings_dir = vault / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    vault_md = settings_dir / "vault.md"
    vault_md.write_text(
        "---\nschema: design-handoff.vault.v1\nvaultName: Seam\n---\nBody\n",
        encoding="utf-8",
    )

    manager = VaultManager()
    frontmatter = {"schema": "design-handoff.vault.v1", "vaultName": "Seam"}

    def _invoke() -> None:
        manager._ensure_frontmatter_id(
            vault_md,
            frontmatter,
            key="vaultId",
            prefix="vault",
            body="Body\n",
            persist=True,
        )

    return _invoke


def _identity_heal_snapshot(tmp_path: Path) -> dict[Path, bytes]:
    vault = tmp_path / "vault"
    return {p: p.read_bytes() for p in sorted(vault.rglob("*")) if p.is_file()}


def _checkbox_rollback_invoke(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> _Callable[[], None]:
    """Checkbox-projection rollback write (#2910 scope item 3).

    Forces ``run_panel_note_execution`` to raise after the checkbox has been
    projected, so ``CheckboxProjectionService._project_locked``'s exception
    handler reaches its compensating ``write_note_from_absolute(note_path,
    rollback_text, ...)`` call -- covered automatically once the port itself
    is guarded (issue scope item 3's stated mechanism), not by a second
    caller-side assert in the handler.
    """
    import app.panel.checkbox_projection as projection_module
    from app.panel.checkbox_projection import (
        CheckboxProjectionIdempotencyStore,
        CheckboxProjectionRequest,
        CheckboxProjectionService,
        extract_panel_selectable_options,
    )

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    note = vault / "panel.md"
    note.write_text(
        "---\nuuid: seam-note\n---\n\n"
        "%% AI:Start %%\n## AI-instruktion\nDo it.\n## AI-åtgärder\n"
        "- [ ] Send email <!--ai:option_id=opt_1--> <!--ai:id=send.email--> "
        "<!--ai:proposed=1-->\n%% AI:End %%\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(
        projection_module,
        "run_panel_note_execution",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("seam property forced failure")),
    )
    monkeypatch.setattr(
        projection_module,
        "refresh_panel_note_object",
        lambda *a, **k: None,
    )

    def _invoke() -> None:
        content = note.read_text(encoding="utf-8")
        from app.text.helpers import content_hash as _content_hash

        options = extract_panel_selectable_options(
            content,
            artifact_id="seam-note",
            note_path="panel.md",
            content_hash=_content_hash(content),
        )
        option = next(o for o in options if o.option_id == "opt_1")
        service = CheckboxProjectionService(idempotency_store=CheckboxProjectionIdempotencyStore())
        request = CheckboxProjectionRequest(
            artifact_id="seam-note",
            note_path="panel.md",
            panel_id=option.panel_id,
            option_id="opt_1",
            expected_content_hash=option.content_hash,
            expected_source_hash=option.source_hash,
            idempotency_key="idem-seam-property",
        )
        response = service._project_locked(request, "panel.md")
        # A blocked write returns a "blocked" response instead of raising --
        # the service's own contract catches WritesBlockedError at its own
        # caller-side check (checkbox_projection.py's "panel.checkbox_
        # projection" action, BEFORE the projected write or the rollback
        # write are ever reached) and converts it to a response object (see
        # CheckboxProjectionService._project_locked). Re-raise a
        # WritesBlockedError carrying the ORIGINAL guard state/reason (parsed
        # back out of the response) so the shared P-1/P-4 assertions can
        # treat every registered seam uniformly without a synthetic state.
        if response.status == "blocked":
            from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

            snapshot = DEFAULT_WRITE_GUARD.snapshot_fn()
            raise WritesBlockedError(
                str(snapshot.get("state") or "blocked"),
                response.block_reason,
                "panel.checkbox_projection",
            )

    return _invoke


def _checkbox_rollback_snapshot(tmp_path: Path) -> dict[Path, bytes]:
    vault = tmp_path / "vault"
    return {p: p.read_bytes() for p in sorted(vault.rglob("*")) if p.is_file()}


def _mcp_vault_tools_invoke(
    tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> _Callable[[], None]:
    """The named live violator (#2953): ``app/mcp/vault_tools.py::append_note``
    reaches ``write_note_relative`` with NO caller-side WriteGuard assert on
    `main` -- the issue's concrete example of why the relative-path port
    itself (not caller convention) must be the guarded seam. Exercising the
    real ``append_note`` entrypoint (not calling ``write_note_relative``
    directly) proves the port-level fix actually closes this specific caller.
    """
    from app.mcp.vault_tools import append_note

    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    def _invoke() -> None:
        append_note(title="Seam Note", body="original content", vault_root=vault)

    return _invoke


def _mcp_vault_tools_snapshot(tmp_path: Path) -> dict[Path, bytes]:
    vault = tmp_path / "vault"
    return {p: p.read_bytes() for p in sorted(vault.rglob("*")) if p.is_file()}


REGISTERED_WRITE_SEAMS: tuple[RegisteredWriteSeam, ...] = (
    RegisteredWriteSeam(
        name="knowledge_write_port",
        action="knowledge.write_note",
        guard_patch_target="app.write_guard.DEFAULT_WRITE_GUARD",
        invoke_factory=_knowledge_port_invoke,
        unchanged_paths=_knowledge_port_snapshot,
    ),
    RegisteredWriteSeam(
        name="identity_heal",
        action="vault.identity_heal",
        guard_patch_target="app.write_guard.DEFAULT_WRITE_GUARD",
        invoke_factory=_identity_heal_invoke,
        unchanged_paths=_identity_heal_snapshot,
    ),
    RegisteredWriteSeam(
        name="checkbox_rollback",
        action="knowledge.write_note",
        guard_patch_target="app.write_guard.DEFAULT_WRITE_GUARD",
        invoke_factory=_checkbox_rollback_invoke,
        unchanged_paths=_checkbox_rollback_snapshot,
    ),
    RegisteredWriteSeam(
        name="mcp_vault_tools_append_note",
        action="knowledge.write_note",
        guard_patch_target="app.write_guard.DEFAULT_WRITE_GUARD",
        invoke_factory=_mcp_vault_tools_invoke,
        unchanged_paths=_mcp_vault_tools_snapshot,
    ),
)


# ---------------------------------------------------------------------------
# Store-payload episode_ref census (ERE-05, #3180 -- invariant->producers)
# ---------------------------------------------------------------------------
#
# episode_ref is vault-canonical (ERE-03): every producer that writes a note's DB-side
# store_objects / store_vector_index payload MUST carry episode_ref, or a stamped binding is
# blind-dropped and retrieval reverts to `unbound`
# (docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md). Rounds 2/3/4 of PR #3520 each
# found a producer the previous census missed. Round 4 CLOSED the scanner gap: it now recognizes
# EVERY store-payload sink method name -- put, upsert, save_object, ingest_object,
# index_ingest_object -- not just put/ingest_object (the round-3 blind spot that let save_object /
# upsert producers drop episode_ref while the census passed). Audited against the write methods on
# app/stores/base.py (ObjectStore.put, ObjectsStore.upsert, VectorIndex.upsert) and the
# app/objects/__init__.py ObjectStore.save_object facade.
#
# Two gates (tests/properties/test_store_payload_episode_ref.py): (1) every sink site is classified
# with a justification (a NEW unclassified sink fails); (2) every PRODUCER site is verified to carry
# episode_ref by the check its classification names.
#
# Classification prefixes (the prefix selects the verification a producer gets):
#   "carries_frontmatter"             -- fresh note payload whose dict literal includes episode_ref
#                                        via episode_ref_from_frontmatter; verified: episode_ref key
#                                        present in the statically-resolved payload dict.
#   "carries_unbound_default"         -- frontmatter-less source (external/raw/api/fitness) whose
#                                        payload dict includes an explicit episode_ref (honest
#                                        'unbound'); verified same as carries_frontmatter.
#   "carries_normalized"              -- normalizes episode_ref from an upstream-authored payload
#                                        (reflection); verified same (episode_ref key present).
#   "carries_via_indexed_unit_builder"-- payload = build_indexed_unit_payload(...); the builder
#                                        unconditionally defaults episode_ref (the choke), so every
#                                        store_vector_index row RETRIEVAL reads carries it. Verified:
#                                        payload expr calls build_indexed_unit_payload AND
#                                        test_build_indexed_unit_payload_always_sets_episode_ref.
#   "preserves_existing_payload"      -- updates an existing object starting from
#                                        dict(existing.payload); a stamped episode_ref survives.
#                                        Verified: payload expr reads `.payload` of an existing row.
#   "superseded_by_store_put"         -- an intermediate write immediately overwritten, for the same
#                                        object_id in the same flow, by a carries_* store.put.
#   "transport_passthrough"           -- store/facade plumbing forwarding a caller-built payload; the
#                                        producing caller carries episode_ref, not this layer.
#   "not_store_object_payload"        -- writes a DIFFERENT store (reasoning/decisions) or a
#                                        Queue.put -- not a store_objects/store_vector_index payload.
#   "harness_excluded"                -- dev/CI harness seeder (formal-model.md §2.3).
_SINK_METHOD_NAMES: frozenset[str] = frozenset(
    {"put", "upsert", "save_object", "ingest_object", "index_ingest_object"}
)


def find_store_payload_sink_sites(root: Path = APP_ROOT) -> list[tuple[str, int]]:
    """AST-scan ``app/**/*.py`` for every store-payload SINK call site.

    A sink is a call to any store write method that carries an object payload:
    ``ingest_object``/``index_ingest_object`` (always payload=), ``save_object`` (payload inside the
    DomainObject arg), or ``put``/``upsert`` that pass a ``payload=`` kwarg or ``**kwargs`` (the two
    protocol methods on app/stores/base.py that take a payload; a bare ``Queue.put((...))`` or a
    ``DecisionsStore.put(value=...)`` carries neither and is correctly skipped). Returns EVERY match
    unfiltered -- classification against :data:`STORE_PAYLOAD_SINK_CLASSIFICATION` is the caller's
    job, so this scanner cannot itself become an escape hatch. This is the round-4 meta-fix: the
    round-3 scanner recognized only ``put``/``ingest_object`` and so missed the save_object/upsert
    producers entirely.
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
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if name not in _SINK_METHOD_NAMES:
                continue
            has_payload_kw = any(kw.arg == "payload" for kw in node.keywords)
            has_star_kw = any(kw.arg is None for kw in node.keywords)
            if name in ("put", "upsert"):
                # object payload only when a payload=/**kwargs is present (skips Queue.put /
                # DecisionsStore.put(value=...) / reasoning_store.upsert(id, output)).
                if not (has_payload_kw or has_star_kw):
                    continue
            sites.append((rel, node.lineno))
    return sites


def _enclosing_function(tree: ast.AST, lineno: int) -> ast.AST | None:
    best: ast.AST | None = None
    best_span = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            if start <= lineno <= end:
                span = end - start
                if best_span is None or span < best_span:
                    best, best_span = node, span
    return best


def _name_assignments(name: str, func: ast.AST) -> list[ast.AST]:
    """Every value expression assigned to ``name`` within ``func`` (plain and ``name.payload =``
    attribute assigns), in source order."""
    values: list[ast.AST] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
    return values


def _dict_keys_reachable(
    expr: ast.AST, func: ast.AST, seen: frozenset[str] = frozenset()
) -> set[str]:
    """String keys reachable from ``expr`` as a payload dict, following ``Name`` assignments,
    ``**unpack``, and ``dict(<name>)`` wrappers within ``func`` (bounded, cycle-guarded)."""
    keys: set[str] = set()
    if isinstance(expr, ast.Dict):
        for k, v in zip(expr.keys, expr.values):
            if k is None:  # ** unpack
                keys |= _dict_keys_reachable(v, func, seen)
            elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
    elif isinstance(expr, ast.Name):
        if expr.id in seen:
            return keys
        seen = seen | {expr.id}
        for value in _name_assignments(expr.id, func):
            keys |= _dict_keys_reachable(value, func, seen)
    elif isinstance(expr, ast.Call):
        # dict(<x>) wrapper -> recurse into its first positional arg.
        f = expr.func
        if isinstance(f, ast.Name) and f.id == "dict" and expr.args:
            keys |= _dict_keys_reachable(expr.args[0], func, seen)
    return keys


def _domain_object_payload_expr(
    expr: ast.AST, func: ast.AST, seen: frozenset[str] = frozenset()
) -> ast.AST | None:
    """Resolve the payload expression written by ``save_object(<expr>)`` -- ``<expr>`` is a
    DomainObject/shim (inline or a Name). Returns the payload= kwarg's value (or the last
    ``<name>.payload = ...`` reassignment before the call)."""
    if isinstance(expr, ast.Call):
        for kw in expr.keywords:
            if kw.arg == "payload":
                return kw.value
        return None
    if isinstance(expr, ast.Name):
        if expr.id in seen:
            return None
        seen = seen | {expr.id}
        # a later ``<name>.payload = <p>`` reassignment wins (panel/promotion update path).
        attr_payload: ast.AST | None = None
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "payload"
                        and isinstance(target.value, ast.Name)
                        and target.value.id == expr.id
                    ):
                        attr_payload = node.value
        if attr_payload is not None:
            return attr_payload
        # else the DomainObject(...) the name was bound to.
        for value in _name_assignments(expr.id, func):
            resolved = _domain_object_payload_expr(value, func, seen)
            if resolved is not None:
                return resolved
    return None


def _kwargs_payload_expr(star_name: str, func: ast.AST) -> ast.AST | None:
    """Resolve the ``payload`` value inside a ``**<star_name>`` kwargs built earlier in ``func`` --
    both the ``{"payload": ...}`` dict-literal form (``upsert_kwargs = {"payload":
    build_indexed_unit_payload(...), ...}``) and the ``dict(payload=..., ...)`` call form
    (``upsert_kwargs = dict(kind="note", payload=canonical_payload, ...)`` -- vault_root)."""
    for value in _name_assignments(star_name, func):
        if isinstance(value, ast.Dict):
            for k, v in zip(value.keys, value.values):
                if isinstance(k, ast.Constant) and k.value == "payload":
                    return v
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
        ):
            for kw in value.keywords:
                if kw.arg == "payload":
                    return kw.value
    return None


def _resolve_payload_expr(rel_path: str, lineno: int) -> tuple[ast.AST | None, ast.AST | None]:
    """Return ``(payload_expr, enclosing_func)`` for the sink call at ``(rel_path, lineno)`` --
    handles payload= kwarg, ``**kwargs``, and ``save_object(<DomainObject>)``. ``payload_expr`` is
    ``None`` when unresolvable (which fails a producer census loudly)."""
    path = REPO_ROOT / rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None, None
    func = _enclosing_function(tree, lineno)
    if func is None:
        return None, None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.lineno == lineno):
            continue
        fn = node.func
        name = (
            fn.id
            if isinstance(fn, ast.Name)
            else (fn.attr if isinstance(fn, ast.Attribute) else None)
        )
        # direct payload= kwarg
        for kw in node.keywords:
            if kw.arg == "payload":
                return kw.value, func
        # save_object(<DomainObject-or-Name>)
        if name == "save_object" and node.args:
            return _domain_object_payload_expr(node.args[0], func), func
        # **kwargs
        for kw in node.keywords:
            if kw.arg is None and isinstance(kw.value, ast.Name):
                return _kwargs_payload_expr(kw.value.id, func), func
        return None, func
    return None, func


def payload_keys_at_sink(rel_path: str, lineno: int) -> set[str] | None:
    """Statically-resolved episode_ref-relevant key set of the payload written at the sink, or
    ``None`` when unresolvable."""
    expr, func = _resolve_payload_expr(rel_path, lineno)
    if expr is None or func is None:
        return None
    return _dict_keys_reachable(expr, func)


def payload_expr_at_sink(rel_path: str, lineno: int) -> str | None:
    """The unparsed payload expression at the sink (for the builder / preserve structural checks),
    or ``None`` when unresolvable."""
    expr, _func = _resolve_payload_expr(rel_path, lineno)
    return ast.unparse(expr) if expr is not None else None


def payload_source_blob(rel_path: str, lineno: int) -> str | None:
    """The payload expression at the sink PLUS the unparsed value of every ``Name`` it transitively
    references (bounded, cycle-guarded), joined -- so a builder/preserve check sees through a
    payload bound to a variable (``payload_out = build_indexed_unit_payload(...)``;
    ``payload = dict(existing.payload)``). ``None`` when the payload arg cannot be resolved."""
    expr, func = _resolve_payload_expr(rel_path, lineno)
    if expr is None or func is None:
        return None
    texts: list[str] = []
    seen_names: set[str] = set()
    stack: list[ast.AST] = [expr]
    while stack:
        e = stack.pop()
        texts.append(ast.unparse(e))
        for n in ast.walk(e):
            if isinstance(n, ast.Name) and n.id not in seen_names:
                seen_names.add(n.id)
                stack.extend(_name_assignments(n.id, func))
    return "\n".join(texts)


STORE_PAYLOAD_SINK_CLASSIFICATION: dict[tuple[str, int], str] = {
    # ============================================================================================
    # Round-5 re-audit: EVERY classification below is verified by the sink's ACTUAL DB write
    # DESTINATION (traced through facades: PgObjects.upsert -> PgObjectStore.put -> store_objects;
    # ObjectStore.save_object -> (pg) store.put -> store_objects; ingest_object -> idx.upsert ->
    # store_vector_index), NOT the surface method name. The round-4 misclassification of
    # vault_root's objects_store.upsert as "not_store_object_payload" (it actually writes the
    # canonical store_objects table) proved name/surface classification is unsafe. There is now NO
    # "not a producer" escape hatch: every sink is a carry / preserve / builder / construction
    # producer, or transport (forwards a verified-carrying caller payload), or harness.
    # ============================================================================================
    # -- carries_frontmatter: fresh note payload dict; episode_ref from frontmatter --------------
    ("app/cli/alpha_human_flows.py", 120): (
        "carries_frontmatter: _ingest_note payload carries episode_ref_from_frontmatter(frontmatter)"
        "; index_ingest_object -> store_vector_index."
    ),
    ("app/cli/alpha_human_flows.py", 132): (
        "carries_frontmatter: same payload (store_payload = {**payload, 'text': ...}) -> store.put "
        "-> store_objects."
    ),
    ("app/ingest/vault_alpha.py", 569): (
        "carries_frontmatter: obj.payload carries episode_ref_from_frontmatter(frontmatter); "
        "ObjectStore().save_object(obj) -> (pg) store.put -> store_objects (round-5: the carrying "
        "get_object_store().put below is in try/except:pass, so THIS row must carry it too)."
    ),
    ("app/ingest/vault_alpha.py", 604): (
        "carries_frontmatter: store_payload carries episode_ref; get_object_store().put -> "
        "store_objects."
    ),
    ("app/ingest/vault_alpha.py", 618): (
        "carries_frontmatter: same store_payload -> index_ingest_object -> store_vector_index."
    ),
    ("app/ingest/vault_root.py", 91): (
        "carries_frontmatter: canonical_payload carries episode_ref; objects_store.upsert -> "
        "PgObjects.upsert -> PgObjectStore.put -> store_objects (round-5 finding: this IS a "
        "canonical store_objects write, not the legacy `objects` table alone)."
    ),
    ("app/ingest/vault_root.py", 95): (
        "carries_frontmatter: the id-less fallback of the same canonical_payload objects_store."
        "upsert -> store_objects."
    ),
    ("app/ingest/vault_root.py", 110): (
        "carries_frontmatter: _ingest_file payload carries episode_ref; index_ingest_object -> "
        "store_vector_index."
    ),
    ("app/ingest/vault_root.py", 122): (
        "carries_frontmatter: same payload ({**payload, 'text': ...}) -> store.put -> store_objects."
    ),
    # -- carries_unbound_default: frontmatter-less source; honest 'unbound' -----------------------
    ("app/ingest/external.py", 66): (
        "carries_unbound_default: external raw sources have no frontmatter and are never ERE-05 "
        "targets; explicit 'unbound'; store.put -> store_objects."
    ),
    ("app/ingest/external.py", 67): (
        "carries_unbound_default: same payload -> index_ingest_object -> store_vector_index."
    ),
    ("app/fitness/metrics.py", 111): (
        "carries_unbound_default: CI latency probe (kind='fitness', never a note) writing "
        "store_vector_index directly (bypasses the build_indexed_unit_payload choke); explicit "
        "'unbound'."
    ),
    ("app/ingest/api.py", 167): (
        "carries_unbound_default: programmatic ingest helper builds a fresh frontmatter-less "
        "store_objects payload; episode_ref normalized to 'unbound' via the {**...} rebuild; "
        "save_object -> store_objects. Line drifted 118 -> 167 (site unchanged); re-pinned "
        "by #4178."
    ),
    ("app/reasoning/multi.py", 51): (
        "carries_unbound_default: UUID-addressable reasoning inputs are rebuildable proposal "
        "mirrors, not episode-bound vault knowledge; payload explicitly carries honest "
        "episode_ref='unbound'; store.put -> store_objects."
    ),
    # -- carries_normalized: normalize episode_ref from an upstream-authored payload --------------
    ("app/ingest/reflection_consumer.py", 37): (
        "carries_normalized: reflection re-ingest normalizes episode_ref from the queued "
        "derived-artifact payload; ingest_object -> store_vector_index."
    ),
    # -- carries_via_indexed_unit_builder: payload = build_indexed_unit_payload(...) (the choke) --
    ("app/cli/index_rebuild.py", 320): (
        "carries_via_indexed_unit_builder: cold rebuild re-embeds store_objects rows through "
        "build_indexed_unit_payload (defaults episode_ref) -> idx.upsert -> store_vector_index."
    ),
    ("app/cli/index_rebuild.py", 726): (
        "carries_via_indexed_unit_builder: fallback rebuild upsert via build_indexed_unit_payload "
        "-> store_vector_index."
    ),
    ("app/indexer/consumer.py", 88): (
        "carries_via_indexed_unit_builder: legacy embedding-in-event path; payload = "
        "build_indexed_unit_payload(...) -> idx.upsert -> store_vector_index."
    ),
    ("app/indexer/consumer.py", 180): (
        "carries_via_indexed_unit_builder: INDEX_EMBEDDING_REQUESTED path; upsert_kwargs['payload'] "
        "= build_indexed_unit_payload(payload=dict(obj.payload)) -> store_vector_index."
    ),
    ("app/search/service.py", 282): (
        "carries_via_indexed_unit_builder: ingest_object's internal idx.upsert; payload_out = "
        "build_indexed_unit_payload(payload=<caller payload>) -> store_vector_index."
    ),
    ("app/services/indexer.py", 176): (
        "carries_via_indexed_unit_builder: handle_ingest_object_created save_object; domain.payload "
        "= build_indexed_unit_payload(...) -> store_objects. Also carries frontmatter episode_ref "
        "into the input on the vault-changed path and preserves an existing binding via the merge."
    ),
    ("app/services/indexer.py", 256): (
        "carries_via_indexed_unit_builder: same handler's vector_index.upsert; upsert_kwargs["
        "'payload'] = build_indexed_unit_payload(...) -> store_vector_index."
    ),
    # -- preserves_existing_payload: update starting from dict(existing.payload) ------------------
    ("app/agents/panel/writeback.py", 213): (
        "preserves_existing_payload: panel writeback updates from dict(existing.payload); save_object"
        " -> store_objects; a stamped episode_ref survives (new-object branch has no prior row to "
        "drop)."
    ),
    ("app/agents/panel_agent/execution.py", 62): (
        "preserves_existing_payload: panel execution updates from dict(existing.payload or {}); "
        "save_object -> store_objects."
    ),
    ("app/agents/panel_agent/runtime.py", 112): (
        "preserves_existing_payload: _persist_log appends to dict(existing.payload); save_object -> "
        "store_objects; episode_ref preserved."
    ),
    ("app/agents/planner/graph.py", 237): (
        "preserves_existing_payload: panel-action frontmatter update reuses obj.payload from "
        "get_object; save_object -> store_objects; episode_ref preserved."
    ),
    ("app/promotion/consumer.py", 97): (
        "preserves_existing_payload: promotion updates from dict(existing.payload); save_object -> "
        "store_objects; a new-note branch has no prior row and no binding (unbound correct via the "
        "build_indexed_unit_payload choke at index time)."
    ),
    ("app/watcher/vault_watcher.py", 247): (
        "preserves_existing_payload: _hydrate_store_with_markdown updates raw_text on "
        "dict(obj.payload); save_object -> store_objects; episode_ref preserved."
    ),
    # -- carries_at_construction: payload built in a separate function that carries episode_ref;
    #    verified by a RUNTIME test (the payload is opaque at this call site) ---------------------
    ("app/agents/normalizer/agent.py", 165): (
        "carries_at_construction: shim.payload = normalize_file(...)['payload'], which carries "
        "episode_ref_from_frontmatter(frontmatter) in app/agents/normalizer/agent.py::normalize_file"
        "; save_object -> store_objects. Verified by "
        "test_normalizer_run_carries_episode_ref_to_store_objects."
    ),
    ("app/agents/planner/agent.py", 118): (
        "carries_at_construction: obj = plan.to_object(), whose payload carries episode_ref='unbound'"
        " (a Plan never originates in an episode) in app/domain/plan.py::Plan.to_object; save_object "
        "-> store_objects. Verified by test_plan_to_object_carries_episode_ref."
    ),
    # -- transport_passthrough: facade/plumbing forwarding a caller-built (verified) payload ------
    ("app/objects/__init__.py", 120): (
        "transport_passthrough: ObjectStore.save_object facade forwards dict(obj.payload) to the "
        "backing store.put -> store_objects; the caller that builds obj.payload carries episode_ref "
        "(every save_object caller is itself a classified producer above). Line drifted 116 -> 122 "
        "when atomic create support was added above this facade call (#4111)."
    ),
    ("app/stores/memory.py", 98): (
        "transport_passthrough: MemoryObjectStore.put_if_absent delegates the caller-supplied "
        "payload unchanged to put; the atomic-create facade caller constructs and classifies the "
        "payload before crossing this backing-store boundary (#4111)."
    ),
    ("app/stores/postgres.py", 28): (
        "transport_passthrough: PgObjects.upsert forwards its caller-supplied payload arg to "
        "canonical_store.put (PgObjectStore.put) -> store_objects; the caller (vault_root:92/96) "
        "carries episode_ref in canonical_payload."
    ),
    # -- harness_excluded: dev/CI seeders (formal-model.md 2.3) -----------------------------------
    (
        "app/cli/smoke.py",
        115,
    ): "harness_excluded: smoke reality-probe seeder; never a real vault producer.",
    ("app/cli/smoke.py", 139): "harness_excluded: smoke reality-probe seeder.",
    ("app/cli/smoke.py", 277): "harness_excluded: smoke ASK-corpus seeder.",
    ("app/cli/smoke.py", 281): "harness_excluded: smoke ASK-corpus seeder (index_ingest_object).",
}

STORE_PAYLOAD_CARRIES_DICT_PREFIXES: tuple[str, ...] = (
    "carries_frontmatter",
    "carries_unbound_default",
    "carries_normalized",
)
#: Producers verified statically by a resolvable-dict episode_ref key, by tracing to
#: build_indexed_unit_payload, or by tracing to an existing row's .payload.
STORE_PAYLOAD_STATIC_PRODUCER_PREFIXES: tuple[str, ...] = STORE_PAYLOAD_CARRIES_DICT_PREFIXES + (
    "carries_via_indexed_unit_builder",
    "preserves_existing_payload",
)
#: carries_at_construction producers build the payload in a separate function (opaque at the call
#: site) and are verified by a named RUNTIME test instead of the static resolver.
STORE_PAYLOAD_PRODUCER_PREFIXES: tuple[str, ...] = STORE_PAYLOAD_STATIC_PRODUCER_PREFIXES + (
    "carries_at_construction",
)
#: The ONLY non-producer exemptions -- each forwards a verified caller payload / is a harness. No
#: "not_store_object_payload" or "superseded" escape hatches (round-5: those hid a real producer).
_STORE_PAYLOAD_ALL_PREFIXES: tuple[str, ...] = STORE_PAYLOAD_PRODUCER_PREFIXES + (
    "transport_passthrough",
    "harness_excluded",
)
