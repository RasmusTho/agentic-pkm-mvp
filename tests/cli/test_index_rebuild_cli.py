from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.db.dsn import resolve_dsn
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app import objects as legacy_store
from app.objects import DomainObject, ObjectStore
from app.stores import get_vector_index, reset_store_backends


def _legacy_source_fixture(monkeypatch, tmp_path, *, selected=False):
    from copy import deepcopy
    from types import SimpleNamespace
    from app.rebuildability import legacy_source as recovery
    from app.stores.pg import PgObjectStore, PgVectorIndex
    from app.components.embeddings import EmbeddingIdentity

    root = tmp_path / "vault"
    root.mkdir()
    layout = root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir()
    layout.write_text("---\ninclude_folders: [Notes]\n---\nLayout.\n")
    source = root / ("Notes" if selected else "Outside") / "note.md"
    source.parent.mkdir()
    oid = uuid4()
    source.write_text(f"---\nuuid: {oid}\ntrust: human\nreview_state: reviewed\n---\ncanonical body\n")
    original_bytes = source.read_bytes()
    row = dict(object_id=oid, kind="note", source_ref=str(source), payload={"content": "canonical body"})
    state = SimpleNamespace(rows=[row], vectors={}, calls=[], embedded=[], fail=None)
    original = deepcopy(row)

    class Store(PgObjectStore):
        vault_binding_id = "fixture"

        def __init__(self):
            pass

        def list_objects(self, **kwargs):
            return deepcopy(state.rows)

        def reconcile_legacy_source(self, expected, **kwargs):
            if state.fail == "source":
                source.write_text(source.read_text() + "changed")
            kwargs["revalidate"]()
            kwargs["check_sources"](state.rows)
            assert expected == row
            if state.fail == "row":
                raise ValueError("private-row-canary")
            state.calls.append(kwargs)
            if kwargs["replacement"] is None:
                state.rows.remove(row)
            else:
                row["payload"] = kwargs["replacement"]
                state.vectors[str(oid)] = kwargs["vector"]

    class Index(PgVectorIndex):
        vault_binding_id = "fixture"

        def __init__(self):
            pass

        def present_object_ids(self):
            return set(state.vectors)

    identity = EmbeddingIdentity(provider="mock", model="selected", dim=2, normalize=False)

    def embed(text):
        state.embedded.append(text)
        if state.fail == "embed":
            raise RuntimeError("private-provider-canary")
        return [1.0, 2.0]

    binding = SimpleNamespace(backend="pg", store=Store())
    index = Index()
    factory = lambda **kwargs: SimpleNamespace(identity=identity, embed_text=embed)
    monkeypatch.setattr(recovery, "resolve_vault_root", lambda: root)
    return recovery, state, root, source, original_bytes, original, binding, index, factory


@pytest.mark.parametrize("selected", [False, True])
def test_legacy_source_reconciliation_uses_current_canonical_eligibility(monkeypatch, tmp_path, selected):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=selected)
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert source.read_bytes() == raw
    if selected:
        projected = state.rows[0]
        assert projected["object_id"] == original["object_id"]
        assert projected["payload"]["frontmatter"]["trust"] == "human"
        assert projected["payload"]["origin"] == "vault"
        assert projected["payload"]["replay"]["source_identity"] == source.relative_to(root).as_posix()
        assert state.embedded == ["canonical body"]
    else:
        assert state.rows == [] and state.embedded == [] and state.vectors == {}
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0
    assert not (root / "_system" / "companions").exists()


def test_legacy_excluded_source_retires_only_exact_stale_projection(monkeypatch, tmp_path):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    unrelated = {**original, "object_id": uuid4(), "source_ref": str(root / "other.md"),
                 "payload": {"text": "other", "frontmatter": {}}}
    state.rows.append(unrelated)
    state.vectors[str(unrelated["object_id"])] = "unchanged"
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert state.rows == [unrelated]
    assert state.vectors == {str(unrelated["object_id"]): "unchanged"}
    assert source.read_bytes() == raw


@pytest.mark.parametrize("failure", ["candidate", "authority", "trust", "malformed", "missing", "symlink",
    "outside", "duplicate", "identity", "body", "source", "row", "embed", "draft", "staged",
    "directory-symlink", "hardlink", "duplicate-case", "profile"])
def test_legacy_source_reconciliation_refuses_unsafe_or_racing_sources(monkeypatch, tmp_path, failure):
    from app.cli import index_rebuild as repair
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=failure == "embed")
    if failure in ("candidate", "authority", "trust", "draft"):
        marker = {"candidate": "candidate_only: true", "authority": "authority: {source_authoritative: false}",
                  "trust": "trust: external", "draft": "review_state: draft"}[failure]
        source.write_text(raw.decode().replace("---\ncanonical", f"{marker}\n---\ncanonical"))
    elif failure == "malformed":
        source.write_text("---\nuuid: [\n---\ncanonical body")
    elif failure == "missing":
        source.unlink()
    elif failure == "symlink":
        target = root / "target.md"
        source.rename(target)
        source.symlink_to(target)
    elif failure == "outside":
        state.rows[0]["source_ref"] = str(tmp_path / "external.md")
    elif failure == "duplicate":
        (root / "duplicate.md").write_bytes(raw)
    elif failure == "duplicate-case":
        (root / "duplicate.md").write_text(raw.decode().replace(str(original["object_id"]), str(original["object_id"]).upper()))
    elif failure == "directory-symlink":
        target = root / "redirected"
        source.parent.rename(target)
        source.parent.symlink_to(target, target_is_directory=True)
    elif failure == "hardlink":
        import os
        os.link(source, root / "alias.md")
    elif failure == "profile":
        monkeypatch.setattr(recovery, "assert_profile_note_ingestible", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private-authority-canary")))
    elif failure == "identity":
        source.write_text(raw.decode().replace(str(original["object_id"]), "not-a-uuid"))
    elif failure == "body":
        source.write_text(raw.decode() + "changed")
    elif failure == "staged":
        staged = root / "_system" / "drafts" / "note.md"
        staged.parent.mkdir(parents=True)
        source.rename(staged)
        state.rows[0]["source_ref"] = str(staged)
    else:
        state.fail = failure
    before = __import__("copy").deepcopy(state.rows)
    monkeypatch.setattr(repair.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(repair, "get_vector_index", lambda: index)
    monkeypatch.setattr(repair, "get_product_embedding_client", factory)
    result = CliRunner().invoke(cli, ["index", "reconcile-legacy", "--json"])
    assert result.exit_code == 79, result.output
    assert json.loads(result.output) == {"reason": "source_post_rebuild_failed"}
    assert state.calls == [] and state.rows == before and state.vectors == {}
    assert str(root) not in result.output and "canary" not in result.output


@pytest.mark.parametrize("scope", ["same", "ancestor", "subtree"])
def test_legacy_source_reconciliation_refuses_broader_legacy_producer_scope(monkeypatch, tmp_path, scope):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    legacy_root = {"same": root, "ancestor": root.parent, "subtree": source.parent}[scope]
    monkeypatch.setenv("VAULT_DIR", str(legacy_root))
    with pytest.raises(ValueError, match="ambiguous producer inventory"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and state.calls == [] and state.vectors == {}
    assert source.read_bytes() == raw


def test_legacy_source_reconciliation_suppresses_conflict_and_settings_logs(monkeypatch, tmp_path, caplog):
    import logging
    from app.settings.locations import LEGACY_COMPILED_DIR
    from app.knowledge.multiwriter import conflict_artifact_path
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path, selected=True)
    legacy = root / LEGACY_COMPILED_DIR / "watchers.md"
    legacy.parent.mkdir()
    legacy.write_text("---\ncompanion: {}\n---\nsettings")
    conflict = root / conflict_artifact_path("private.md", written_at=datetime.now(timezone.utc), writer_identity="private-writer")
    conflict.write_text("private conflict canary")
    previous = logging.root.manager.disable
    with caplog.at_level(logging.DEBUG):
        assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert str(root) not in caplog.text and "private" not in caplog.text
    assert logging.root.manager.disable == previous
    assert conflict.exists() and source.read_bytes() == raw


@pytest.mark.parametrize("selected", [True, False])
@pytest.mark.parametrize("alias", ["relative", "absolute", "replay", "case", "frontmatter", "stable-id"])
def test_legacy_source_reconciliation_refuses_projection_locator_aliases(monkeypatch, tmp_path, selected, alias):
    from copy import deepcopy
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=selected)
    if alias == "absolute":
        state.rows[0]["source_ref"] = source.relative_to(root).as_posix()
    other = {**original, "object_id": uuid4(), "payload": {"content": "other"},
             "source_ref": str(source) if alias == "absolute" else source.relative_to(root).as_posix()}
    if alias == "replay":
        other["source_ref"] = "other.md"
        other["payload"]["replay"] = {"source_identity": source.relative_to(root).as_posix()}
    if alias == "case":
        other["source_ref"] = other["source_ref"].upper()
    if alias in ("frontmatter", "stable-id"):
        other["source_ref"] = "other.md"
        if alias == "frontmatter":
            other["payload"]["frontmatter"] = {"uuid": str(original["object_id"])}
        else:
            other["payload"]["stable_id"] = str(original["object_id"])
    state.rows.append(other)
    state.vectors[str(other["object_id"])] = "existing vector preserved"
    before = deepcopy(state.rows)
    with pytest.raises(ValueError, match="ambiguous source projection"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == before and state.calls == []
    assert state.vectors == {str(other["object_id"]): "existing vector preserved"}
    assert source.read_bytes() == raw


def test_legacy_source_reconciliation_checks_write_guard_before_store_resolution(monkeypatch):
    from app.cli import index_rebuild as repair
    from app.write_guard import DEFAULT_WRITE_GUARD

    def denied(action):
        raise RuntimeError("private guard diagnostic")

    def unexpected_store():
        pytest.fail("store constructed before write admission")

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", denied)
    monkeypatch.setattr(repair.domain_objects, "resolve_object_store_port", unexpected_store)
    result = CliRunner().invoke(cli, ["index", "reconcile-legacy", "--json"])
    assert result.exit_code == 79
    assert json.loads(result.output) == {"reason": "source_post_rebuild_failed"}


def _missing_repair_fixture(monkeypatch):
    """Run the production ObjectStore consumer and PG insert SQL against a tiny DB double."""
    from contextlib import nullcontext
    from dataclasses import asdict
    from types import SimpleNamespace
    from app.cli import index_rebuild as repair
    from app.components.embeddings import EmbeddingIdentity
    from app.rebuildability.product_total_loss import product_replay_provenance
    from app.stores import pg

    identity = EmbeddingIdentity(provider="mock", model="selected-model", dim=2, normalize=False)
    payload = dict(content="canonical body", text="stale alias", origin="vault",
                   frontmatter={},
                   trust="unreviewed", review_state="provisional", episode_ref="unbound",
                   replay=product_replay_provenance(source_identity="outside.md", source_text="canonical body"))
    row = dict(object_id=uuid4(), kind="note", source_ref="outside.md", payload=payload)
    state = SimpleNamespace(rows=[row], vectors={}, embedded=[], statements=[], fail=None)

    class Cursor:
        result = None

        def execute(self, statement, params):
            state.statements.append(statement)
            if "SELECT object_id FROM store_vector_index" in statement:
                self.result = [dict(object_id=key) for key in state.vectors]
            elif "SELECT kind, source_ref, payload" in statement:
                self.result = {key: row[key] for key in ("kind", "source_ref", "payload")}
                if state.fail == "stale":
                    self.result = {**self.result, "payload": {"content": "changed"}}
            elif "SELECT identity_json" in statement:
                self.result = dict(identity_json=json.dumps(asdict(identity)))
            elif "INSERT INTO store_vector_index" in statement:
                if state.fail == "write":
                    raise RuntimeError("private provider canary")
                assert "DO NOTHING" in statement and "DO UPDATE" not in statement
                state.vectors.setdefault(str(params[1]), params)
            else:
                raise AssertionError(statement)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    cursor = Cursor()
    monkeypatch.setattr(pg, "_ensure_tables", lambda: None)
    monkeypatch.setattr(pg, "_connect", lambda: nullcontext(SimpleNamespace(cursor=lambda: nullcontext(cursor))))
    index = pg.PgVectorIndex()
    binding = SimpleNamespace(backend="pg", store=SimpleNamespace(
        vault_binding_id=index.vault_binding_id, list_objects=lambda **kwargs: state.rows))
    monkeypatch.setattr(repair.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(repair, "get_vector_index", lambda: index)

    def embed(text):
        state.embedded.append(text)
        if state.fail == "embed":
            raise RuntimeError("private provider canary")
        if state.fail == "race":
            state.vectors[str(row["object_id"])] = "racing winner"
        return [1.0, 2.0]

    monkeypatch.setattr(repair, "get_product_embedding_client", lambda **kwargs: SimpleNamespace(
        identity=identity, embed_text=embed))
    return repair, state, identity


def test_missing_only_repair_never_overwrites_existing_vectors(monkeypatch):
    import copy
    repair, state, identity = _missing_repair_fixture(monkeypatch)
    original = copy.deepcopy(state.rows)
    old_id = str(uuid4())
    state.vectors[old_id] = "preserved"
    state.rows.append({**state.rows[0], "object_id": old_id, "payload": {"content": "existing"}})
    assert repair.repair_missing_vectors() == 1
    assert state.vectors[old_id] == "preserved"
    assert state.rows[0] == original[0]
    assert state.embedded == ["canonical body"]
    inserted = state.vectors[str(state.rows[0]["object_id"])]
    assert inserted[7:10] == (identity.model, identity.provider, identity.normalize)
    projected = json.loads(inserted[4])
    assert projected["text"] == projected["content"] == "canonical body"
    assert projected["replay"] == original[0]["payload"]["replay"]
    assert projected["trust"] == "unreviewed"
    assert repair.repair_missing_vectors() == 0
    assert state.embedded == ["canonical body"]


@pytest.mark.parametrize("failure", ["embed", "write", "stale", "race"])
def test_missing_only_repair_atomic_or_absent(monkeypatch, failure):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    state.fail = failure
    if failure == "race":
        repair.repair_missing_vectors()
        assert list(state.vectors.values()) == ["racing winner"]
    else:
        with pytest.raises(repair.MissingVectorRepairFailure):
            repair.repair_missing_vectors()
        assert state.vectors == {}


def test_missing_only_repair_preserves_core6_metadata(monkeypatch):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    payload = state.rows[0]["payload"]
    payload["core6"] = {"origin": payload.pop("origin"), "trust": "human",
                        "review_state": "protected", "title": "preserved title"}
    payload.pop("trust")
    payload.pop("review_state")
    repair.repair_missing_vectors()
    projected = json.loads(state.vectors[str(state.rows[0]["object_id"])][4])
    assert projected["origin"] == "vault"
    assert projected["trust"] == "human"
    assert projected["review_state"] == "protected"
    assert projected["title"] == "preserved title"
    assert "trust" not in payload and "review_state" not in payload


@pytest.mark.parametrize("change", [
    {"origin": "external"}, {"trust": "untrusted"}, {"review_state": "draft"},
    {"candidate_only": True}, {"authority": {"source_authoritative": False}},
    {"replay": {}}, {"replay": {"source_identity": "secret"}},
])
def test_missing_only_repair_refuses_unadmitted_payload(monkeypatch, change):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    state.rows[0]["payload"].update(change)
    with pytest.raises(repair.MissingVectorRepairFailure, match="^source_post_rebuild_failed$"):
        repair.repair_missing_vectors()
    assert state.vectors == {} and state.embedded == []


@pytest.mark.parametrize("level", ["frontmatter", "core6", "top"])
@pytest.mark.parametrize("change", [
    {"candidate_only": True}, {"artifact_class": "youtube_source_note"},
    {"authority": {"source_authoritative": False}}, {"authority": "malformed"},
    {"authority": {"source_authoritative": "true"}},
    {"authority": {"requires_review": True}}, {"trust": "untrusted"},
    {"review_state": "draft"},
])
def test_missing_only_repair_refuses_nested_or_missing_admission(monkeypatch, level, change):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    payload = state.rows[0]["payload"]
    payload.update(candidate_only=False, authority={"source_authoritative": True})
    target = payload if level == "top" else payload.setdefault(level, {})
    target.update(change)
    with pytest.raises(repair.MissingVectorRepairFailure, match="^source_post_rebuild_failed$"):
        repair.repair_missing_vectors()
    assert state.embedded == [] and state.vectors == {}


@pytest.mark.parametrize("snapshot", [None, "malformed", False, []])
def test_missing_only_repair_refuses_legacy_admission_absence(monkeypatch, snapshot):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    state.rows[0]["payload"]["frontmatter"] = snapshot
    with pytest.raises(repair.MissingVectorRepairFailure, match="^source_post_rebuild_failed$"):
        repair.repair_missing_vectors()
    assert state.embedded == [] and state.vectors == {}


@pytest.mark.parametrize("producer", ["alpha", "alpha_recovery", "alpha_carrying_failure",
                                    "vault_sync", "indexer", "vault_root",
                                    "vault_root_carrying_failure", "projection"])
def test_missing_only_repair_producer_admission_snapshots(monkeypatch, tmp_path, producer):
    from types import SimpleNamespace
    from app.ingest import vault_alpha, vault_root
    from app.services import indexer, vault_sync
    from app.rebuildability import RetainedProjectionSource
    from app.rebuildability.product_total_loss import product_replay_provenance

    repair, state, identity = _missing_repair_fixture(monkeypatch)
    object_id = str(state.rows[0]["object_id"])
    note = tmp_path / "outside.md"
    raw = f"---\nuuid: {object_id}\ntitle: Captured\nreview_state: provisional\nauthority:\n  source_authoritative: true\n---\n\ncanonical body\n"
    note.write_text(raw)
    from app.rebuildability import parse_markdown_text
    frontmatter, _ = parse_markdown_text(raw)
    outputs = []

    class CapturingStore:
        vault_binding_id = COMPATIBILITY_BINDING_ID

        def put(self, oid, **kwargs):
            if producer.endswith("carrying_failure"):
                raise RuntimeError("secondary carrying write unavailable")
            outputs.append(kwargs["payload"])

        def put_and_reconcile_source_backed(self, oid, **kwargs):
            outputs.append(kwargs["payload"])
            return str(oid)

    monkeypatch.setattr(vault_alpha, "classify_run", lambda *args, **kwargs: {})
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **kwargs: None)
    monkeypatch.setattr(vault_alpha, "append_jsonl", lambda *args, **kwargs: None)
    monkeypatch.setattr(vault_alpha, "load_companion_settings", lambda *args: SimpleNamespace(
        create_cooldown_seconds=0, rename_cooldown_seconds=0))
    monkeypatch.setattr(vault_alpha, "check_companion_eligibility", lambda *args, **kwargs: SimpleNamespace(eligible=True))
    monkeypatch.setattr(vault_alpha, "resolve_vault_note_identity", lambda *args, **kwargs: SimpleNamespace(
        note_uuid=object_id, companion=None))
    monkeypatch.setattr(vault_alpha, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(vault_alpha, "get_object_store", CapturingStore)
    monkeypatch.setattr(vault_alpha, "ObjectStore", lambda: SimpleNamespace(save_object=lambda obj, **kwargs: outputs.append(obj.payload)))
    if producer.startswith("alpha"):
        vault_alpha._ingest_single(note, vault_root=tmp_path, trace_id="fixture",
            write_companion_record=False, reconcile_existing_projection=producer == "alpha_recovery")
    elif producer == "vault_sync":
        outputs.append(vault_sync._canonical_note_payload(frontmatter=frontmatter,
            title="Captured", review_state="provisional", maturity=None, content="canonical body",
            replay=product_replay_provenance(source_identity="outside.md", source_text="canonical body")))
    elif producer == "indexer":
        first = indexer._source_backed_projection_metadata({"source_ref": str(note)},
            vault_root=tmp_path, source_snapshot=raw)
        changed = raw.replace("source_authoritative: true", "source_authoritative: false")
        second = indexer._source_backed_projection_metadata({"source_ref": str(note)},
            vault_root=tmp_path, source_snapshot=changed)
        assert first["replay"] == second["replay"]  # Metadata-only changes are not body provenance.
        assert second["frontmatter"]["authority"]["source_authoritative"] is False
        outputs.append(first)
    elif producer.startswith("vault_root"):
        monkeypatch.setenv("STORE_BACKEND", "pg")
        monkeypatch.setattr(vault_root, "resolve_canonical_object_id", lambda value: value)
        monkeypatch.setattr(vault_root, "normalize_run", lambda *args, **kwargs: dict(
            object_id=object_id, core6={}, payload={"content": "canonical body"}))
        monkeypatch.setattr(vault_root, "get_stores", lambda: (SimpleNamespace(upsert=lambda **kwargs: outputs.append(kwargs["payload"])), None))
        monkeypatch.setattr(vault_root, "get_object_store", CapturingStore)
        monkeypatch.setattr(vault_root, "classify_run", lambda *args, **kwargs: {})
        monkeypatch.setattr(vault_root, "index_ingest_object", lambda **kwargs: None)
        monkeypatch.setattr(vault_root, "append_jsonl", lambda *args, **kwargs: None)
        vault_root._ingest_file(note, trace_id="fixture", vault_root=tmp_path)
    else:
        source = RetainedProjectionSource.from_retained_file(vault_root=tmp_path,
            source_identity="outside.md", object_id=state.rows[0]["object_id"],
            payload=state.rows[0]["payload"], embedding_source=SimpleNamespace(
                identity=identity, embed_text=lambda text: [1.0, 2.0]))
        outputs.append(source.canonical_payload)

    assert outputs
    for captured in outputs:
        assert captured["frontmatter"] == frontmatter
        # Every surviving payload carries actual source proof, including the
        # primary write when a best-effort secondary carrying write fails.
        state.rows[0]["payload"] = {**state.rows[0]["payload"], **captured,
            "origin": "vault", "trust": "unreviewed", "review_state": "provisional"}
        state.vectors.clear()
        assert repair.repair_missing_vectors() == 1


@pytest.mark.parametrize("malformed", [False, True, "no_snapshot"])
def test_missing_only_repair_indexer_refresh_never_retains_stale_admission(monkeypatch, tmp_path, malformed):
    from types import SimpleNamespace
    from app.services import indexer

    repair, state, _ = _missing_repair_fixture(monkeypatch)
    row = state.rows[0]
    object_id = str(row["object_id"])
    note = tmp_path / "outside.md"
    raw = ("---\ninvalid: [\n---\n\ncanonical body" if malformed is True else
           f"---\nuuid: {object_id}\nauthority:\n  source_authoritative: false\n---\n\ncanonical body")
    note.write_text(raw)
    original_replay = dict(row["payload"]["replay"])
    existing = DomainObject(uuid=object_id, kind="note", payload=row["payload"],
        source_ref=str(note), created_at=datetime.now(timezone.utc))

    class AfterStoreWrite(RuntimeError):
        pass

    monkeypatch.setattr(indexer, "resolve_event_object_id", lambda obj: object_id)
    monkeypatch.setattr(indexer, "ObjectStore", lambda: SimpleNamespace(
        get_object=lambda oid: existing,
        save_object=lambda domain, **kwargs: row.update(payload=domain.payload)))
    monkeypatch.setattr(indexer, "get_product_embedding_client", lambda: (_ for _ in ()).throw(AfterStoreWrite()))
    with pytest.raises(AfterStoreWrite):
        indexer.handle_ingest_object_created(dict(uuid=object_id, source_ref=str(note),
            content="canonical body", payload={"frontmatter": {"source_authoritative": True}}),
            vault_root=tmp_path, source_snapshot=None if malformed == "no_snapshot" else raw)
    assert row["payload"]["replay"] == original_replay
    if malformed:
        assert "frontmatter" not in row["payload"]
    else:
        assert row["payload"]["frontmatter"]["authority"]["source_authoritative"] is False
    with pytest.raises(repair.MissingVectorRepairFailure, match="^source_post_rebuild_failed$"):
        repair.repair_missing_vectors()
    assert state.embedded == [] and state.vectors == {}


@pytest.mark.parametrize("raw", ["---\n[one, two]\n---\nbody", "---\ninvalid: [\n---\nbody", "---\ntrust: trusted\n"])
def test_missing_only_repair_malformed_source_is_not_empty_admission(raw):
    from app.rebuildability.product_total_loss import capture_source_frontmatter
    assert capture_source_frontmatter(raw) is None
    assert capture_source_frontmatter("body without frontmatter") == {}
    assert capture_source_frontmatter("---\ncreated: 2026-10-14\n---\nbody") == {"created": "2026-10-14"}


def _seed_object(text: str, *, source_ref: str = "tests") -> str:
    store = ObjectStore()
    obj_id = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(obj_id),
            kind="note",
            payload={"text": text, "content": text},
            source_ref=source_ref,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-seed",
    )
    return str(obj_id)


def test_index_rebuild_dry_run(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("alpha beta knowledge")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("alpha beta knowledge")
    hits = idx.search(query, k=1, identity=identity)
    assert hits == []

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_populates_index(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    obj_uuid = _seed_object("agentic policy note")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"])

    assert result.exit_code == 0
    assert "total=1 processed=1 skipped=0 errors=0" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("agentic policy")
    hits = idx.search(query, k=1, identity=identity)
    assert hits
    assert str(hits[0].object_id) == obj_uuid

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_json_summary(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("json summary object")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["processed"] == 1
    assert data["errors"] == []

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_reports_failures(monkeypatch, tmp_path) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    obj_uuid = _seed_object("failure object")
    failures_path = tmp_path / "failures.jsonl"

    idx = get_vector_index()
    original_upsert = idx.upsert

    def _failing_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    idx.upsert = _failing_upsert  # type: ignore[assignment]
    runner = CliRunner()
    try:
        result = runner.invoke(
            cli,
            ["index", "rebuild", "--json", "--failures-path", str(failures_path)],
        )
    finally:
        idx.upsert = original_upsert

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["errors"]
    error = data["errors"][0]
    assert error["object_id"] == obj_uuid
    assert error["source_ref"] == "tests"
    assert error["stage"] == "upsert"
    assert error["exception_type"] == "ValueError"
    assert data["failures_path"] == str(failures_path)
    assert failures_path.exists()

    with open(failures_path, encoding="utf-8") as fh:
        first_line = fh.readline().strip()
    assert first_line
    failure_entry = json.loads(first_line)
    assert failure_entry["object_id"] == obj_uuid
    assert failure_entry["stage"] == "upsert"
    assert failure_entry["source_ref"] == "tests"
    assert failure_entry["identity"]["provider"] == "mock"

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_strict_fails_on_error(monkeypatch, tmp_path) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("will fail")
    failures_path = tmp_path / "strict-failures.jsonl"

    idx = get_vector_index()
    original_upsert = idx.upsert

    def _failing_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    idx.upsert = _failing_upsert  # type: ignore[assignment]
    runner = CliRunner()
    try:
        result = runner.invoke(
            cli,
            [
                "index",
                "rebuild",
                "--json",
                "--strict",
                "--failures-path",
                str(failures_path),
            ],
        )
    finally:
        idx.upsert = original_upsert

    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["failures_path"] == str(failures_path)
    assert data["errors"]
    assert data["errors"][0]["stage"] == "upsert"
    assert failures_path.exists()

    legacy_store._MEMORY_STORE.clear()

@pytest.mark.pg
def test_index_rebuild_sets_pg_meta(monkeypatch) -> None:
    try:
        from tests.stores.test_store_contract_pg import _pg_available  # reuse helper
    except Exception:  # pragma: no cover - fallback when module moves
        pytest.skip("Postgres helper unavailable")

    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    dsn = resolve_dsn()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("pg domain object", source_ref="pg-test")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"], env={"DATABASE_URL": dsn})
    assert result.exit_code == 0

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1")
            row = cur.fetchone()
            assert row is not None
            data = json.loads(row[0])
            assert data.get("provider")
            assert data.get("model")
            assert int(data.get("dim", 0)) > 0

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()

@pytest.mark.pg
def test_index_rebuild_resets_missing_meta(monkeypatch) -> None:
    try:
        from tests.stores.test_store_contract_pg import _pg_available
    except Exception:
        pytest.skip("Postgres helper unavailable")

    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    dsn = resolve_dsn()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("pg meta reset object", source_ref="pg-test")

    get_vector_index()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vector_index_meta WHERE vault_binding_id = %s",
                (COMPATIBILITY_BINDING_ID,),
            )
            cur.execute(
                "DELETE FROM store_vector_index WHERE vault_binding_id = %s",
                (COMPATIBILITY_BINDING_ID,),
            )
            cur.execute(
                "INSERT INTO store_vector_index "
                "(vault_binding_id, object_id, kind, source_ref, payload, embedding, dim, model, updated_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())",
                (
                    COMPATIBILITY_BINDING_ID,
                    uuid4(),
                    "note",
                    "stale",
                    json.dumps({}),
                    [0.1, 0.2],
                    2,
                    "stale-model",
                ),
            )

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"], env={"DATABASE_URL": dsn})
    assert result.exit_code == 0

    expected = get_embedding_identity(client=get_embedding_client())
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1")
            row = cur.fetchone()
            assert row is not None
            data = json.loads(row[0])
            assert data.get("provider") == expected.provider
            assert data.get("model") == expected.model
            assert int(data.get("dim", 0)) == expected.dim
            cur.execute("SELECT DISTINCT dim FROM store_vector_index")
            dims = {int(row[0]) for row in cur.fetchall() if row and row[0] is not None}
            assert dims == {expected.dim}
            cur.execute("SELECT count(*) FROM store_vector_index")
            count_row = cur.fetchone()
            assert int(count_row[0]) > 0

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
