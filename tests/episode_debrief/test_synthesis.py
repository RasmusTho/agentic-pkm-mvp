"""DEBRIEF-02 proof through migrated PG, retrieval, Create and guarded note writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.activation.expansion_records import build_synthesis_note_proposal_posture
from app.episode_debrief import synthesis
from app.episode_debrief.trigger import debrief_id_for_episode
from app.expansion import create
from app.knowledge.errors import KnowledgeWriteConflict
from app.receipts.decision_receipt_log import append_decision_receipt
from app.retrieval import hybrid
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = [pytest.mark.pg, pytest.mark.usefixtures("product_model_access_gateway")]
ALLOW = WriteGuard(lambda: {"state": "healthy"})


@pytest.fixture
def episode(debrief_db, monkeypatch):
    db = debrief_db
    initialize_test_vault(db.root)
    monkeypatch.setenv("VAULT_ROOT", str(db.root))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    monkeypatch.setattr(hybrid, "_STORE", hybrid.MemoryHybridStore())
    monkeypatch.setattr(hybrid, "_revalidate_cache_generation", lambda: None)
    ep = db.episode(count=0, extra_fields={"time": {"start": "2026-10-13T08:00:00Z", "end": "2026-10-13T10:00:00Z", "closed": True}, "space": ["office"], "goal": ["human goal"], "protagonists": ["human"], "causation": ["human cause"]})
    from app.ingest.vault_alpha import resolve_ingest_config
    folder = (resolve_ingest_config(db.root).include_folders or ["."])[0]
    docs = []
    for kind, extra in (("decision", {}), ("commitment", {"commitment_id": "c-1", "commitment_kind": "next_action", "commitment_state": "next"}), ("capture", {})):
        oid = str(uuid4())
        relative = (Path(folder) / f"{kind}.md").as_posix()
        body = f"Retained {kind} text with a citation."
        fields = {"uuid": oid, "kind": kind, "scope": "work", **extra}
        (db.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (db.root / relative).write_text(dump_frontmatter(fields, body), encoding="utf-8")
        _install_watcher_binding(db, ep, {"payload": {"note_path": relative}})
        docs.append({"doc_id": oid, "text": body, "source_ref": oid + "-0", "payload": {"domain": "work", "note_path": relative, "review_state": "reviewed", "evidence_role": "background"}})
        if kind == "decision":
            append_decision_receipt(object_id=oid, key="review", value={"allow": True, "reason": "retained judgment"}, trace_id="fixture", created_at=datetime(2026, 10, 13, 9, tzinfo=timezone.utc), vault_root=db.root, vault_uuid=None)
    hybrid._STORE.set_documents(docs)
    db.closure(ep)
    db.tick()
    payload = db.triggers()[0]
    return db, ep, payload, docs


def run(episode, **kwargs):
    db, _, payload, _ = episode
    return synthesis.synthesize_debrief(payload, vault_root=db.root, write_guard=ALLOW, **kwargs)


def test_debrief_sections_carry_resolvable_source_refs(episode):
    db, _, _, docs = episode
    result = run(episode)
    raw = (db.root / result["draft"]).read_text()
    fm, body = load_frontmatter(raw)
    for name in synthesis.SECTIONS:
        section = body.split(f"## {name}\n", 1)[1].split("\n## ", 1)[0]
        assert "[source: " in section
    from app.stores import get_object_store
    from uuid import UUID
    for ref in fm["debrief_source_refs"]:
        assert get_object_store().get(UUID(ref["artifact_id"])) is not None
        assert ref["role"] == "background"  # no rank-to-evidence upgrade
    assert "retained judgment" in raw
    # Missing membership is a loud citation failure on a fresh Episode.
    other = db.episode(count=0)
    db.bind(other, count=1, prefix="missing")
    with pytest.raises(create.UnresolvableCitationError):
        synthesis.synthesize_debrief({**episode[2], "episode_id": other, "debrief_id": debrief_id_for_episode(other)}, vault_root=db.root, write_guard=ALLOW)
    assert len(list((db.root / "_system/episode-debriefs").glob("debrief-*.md"))) == 1


def test_synthesis_never_crosses_episode_scope(episode):
    db, ep, payload, docs = episode
    # Adversarial store content has a matching bound identity but foreign scope.
    docs[0]["payload"]["domain"] = "private"
    hybrid._STORE.set_documents(docs)
    with pytest.raises(create.UnresolvableCitationError):
        run(episode)
    assert not (db.root / "_system/episode-debriefs" / f"{payload['debrief_id']}.md").exists()
    # The binding itself is another independent enforcement boundary.
    db.execute("UPDATE episode_artifact_binding SET scope='private' WHERE episode_id=%s", (ep,))
    with pytest.raises(synthesis.DebriefSynthesisError, match="cross_scope_no_flow"):
        run(episode)


def test_synthesis_never_mutates_episode_note_content(episode, monkeypatch):
    db, ep, _, _ = episode
    path = db.root / "episodes" / f"{ep}.md"
    original = path.read_bytes()
    # Also pin byte preservation of comments, ordering, newline convention and body.
    original = original.replace(b"title:", b"# human comment\ntitle:").replace(b"\n", b"\r\n")
    path.write_bytes(original)
    run(episode)
    after = path.read_bytes()
    assert after.replace(next(line for line in after.splitlines(keepends=True) if line.startswith(b"debrief_ref:")), b"") == original
    fm, _ = load_frontmatter(after.decode())
    assert fm["debrief_ref"] == [debrief_id_for_episode(ep)]
    assert synthesis.append_debrief_ref_text(after.decode(), episode_id=ep, scope="work", debrief_id=debrief_id_for_episode(ep)) == after.decode()
    with pytest.raises(synthesis.DebriefSynthesisError):
        synthesis.append_debrief_ref_text(after.decode(), episode_id=ep, scope="private", debrief_id=debrief_id_for_episode(ep))


def test_debrief_note_is_candidate_class_no_authority_receipt_at_creation(episode):
    db, _, _, _ = episode
    result = run(episode)
    fm, _ = load_frontmatter((db.root / result["draft"]).read_text())
    assert (fm["derived_by"], fm["authority_state"], fm["review_state"]) == ("synthesis", "proposal", "draft")
    assert not ({"DecisionToken", "AuthorityReceipt", "decision_token", "authority_receipt"} & fm.keys())
    assert result["kind"] == "create.episode_debrief"


def test_synthesis_idempotent_per_episode(episode, monkeypatch):
    db, ep, _, _ = episode
    first = run(episode)
    path = db.root / first["draft"]
    original = path.read_bytes()
    episode_bytes = (db.root / "episodes" / f"{ep}.md").read_bytes()
    monkeypatch.setattr(create, "_run_cognition", lambda *_: pytest.fail("replay must not regenerate"))
    assert run(episode)["status"] == "already_debriefed"
    assert path.read_bytes() == original
    assert (db.root / "episodes" / f"{ep}.md").read_bytes() == episode_bytes
    lines = (path.parent / "outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_blocked_without_green_activation_record(episode):
    db, _, _, _ = episode
    report = run(episode, activation_posture=build_synthesis_note_proposal_posture(loop_precondition_green=False))
    assert report["status"] == "blocked" and report["reasons"]
    assert not (db.root / "_system/episode-debriefs").exists()


def test_debrief_location_excluded_from_ingest_and_not_swept_by_draft_expiry(episode):
    from app.ingest.vault_alpha import select_source_backed_rebuild_candidates
    db, _, _, _ = episode
    result = run(episode)
    path = db.root / result["draft"]
    assert str(path.relative_to(db.root)).startswith("_system/episode-debriefs/")
    fm, _ = load_frontmatter(path.read_text())
    assert "expires" not in fm
    assert path not in select_source_backed_rebuild_candidates(db.root)
    create.sweep_expired_drafts(vault_root=db.root, outbox_path=path.parent / "outbox.jsonl", now=datetime.now(timezone.utc) + timedelta(days=365))
    assert path.exists()


def test_crash_after_draft_repairs_ref_without_regeneration(episode, monkeypatch):
    db, ep, _, _ = episode
    real = synthesis.write_note_from_absolute
    monkeypatch.setattr(synthesis, "write_note_from_absolute", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("crash before ref")))
    with pytest.raises(OSError):
        run(episode)
    path = db.root / "_system/episode-debriefs" / f"{debrief_id_for_episode(ep)}.md"
    raw = path.read_bytes()
    monkeypatch.setattr(synthesis, "write_note_from_absolute", real)
    monkeypatch.setattr(create, "_run_cognition", lambda *_: pytest.fail("must recover, not regenerate"))
    assert run(episode)["episode_note_updated"] is True
    assert path.read_bytes() == raw


def test_concurrent_human_edit_is_preserved_and_retry_appends_only_ref(episode, monkeypatch):
    db, ep, _, _ = episode
    path = db.root / "episodes" / f"{ep}.md"
    real = synthesis.write_note_from_absolute
    def race(target, text, **kwargs):
        path.write_bytes(path.read_bytes() + b"\nConcurrent human text.\n")
        return real(target, text, **kwargs)
    monkeypatch.setattr(synthesis, "write_note_from_absolute", race)
    with pytest.raises(KnowledgeWriteConflict):
        run(episode)
    human_bytes = path.read_bytes()
    monkeypatch.setattr(synthesis, "write_note_from_absolute", real)
    run(episode)
    assert path.read_bytes().replace(next(line for line in path.read_bytes().splitlines(keepends=True) if line.startswith(b"debrief_ref:")), b"") == human_bytes


def test_write_guard_denies_before_any_durable_effect(episode):
    db, _, payload, _ = episode
    with pytest.raises(WritesBlockedError):
        synthesis.synthesize_debrief(payload, vault_root=db.root, write_guard=WriteGuard(lambda: {"state": "unhealthy"}))
    assert not (db.root / "_system/episode-debriefs").exists()


def test_real_worker_dispatch_consumes_trigger(episode):
    from app.workers.outbox_worker import _dispatch_topic
    db, _, payload, _ = episode
    _dispatch_topic("debrief.trigger.created", payload, trace_id="debrief-test", message={"payload_schema": "debrief.trigger.created.v1"}, vault_root=db.root)
    assert run(episode)["status"] == "already_debriefed"


def test_crash_before_receipt_is_repaired_by_create_replay(episode, monkeypatch):
    db, ep, _, _ = episode
    real = create._emit_receipt
    monkeypatch.setattr(create, "_emit_receipt", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("receipt unavailable")))
    with pytest.raises(OSError):
        run(episode)
    path = db.root / "_system/episode-debriefs" / f"{debrief_id_for_episode(ep)}.md"
    before = path.read_bytes()
    monkeypatch.setattr(create, "_emit_receipt", real)
    monkeypatch.setattr(create, "_run_cognition", lambda *_: pytest.fail("Create replay must recover the receipt"))
    assert run(episode)["episode_note_updated"] is True
    assert path.read_bytes() == before
    assert len((path.parent / "outbox.jsonl").read_text().splitlines()) == 1


def test_damaged_retained_draft_cannot_be_linked(episode, monkeypatch):
    db, ep, _, _ = episode
    real = synthesis.write_note_from_absolute
    monkeypatch.setattr(synthesis, "write_note_from_absolute", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        run(episode)
    path = db.root / "_system/episode-debriefs" / f"{debrief_id_for_episode(ep)}.md"
    path.write_bytes(path.read_bytes() + b"Corrupt content\n")
    monkeypatch.setattr(synthesis, "write_note_from_absolute", real)
    with pytest.raises(create.CreateIdempotencyConflictError):
        run(episode)
    assert "debrief_ref" not in load_frontmatter((db.root / "episodes" / f"{ep}.md").read_text())[0]


def test_cli_replays_only_durable_trigger(episode):
    from click.testing import CliRunner
    from app.cli.episode_debrief import episode_debrief_group
    db, ep, _, _ = episode
    result = CliRunner().invoke(episode_debrief_group, ["synthesize", "--episode", ep, "--vault-root", str(db.root), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["episode_note_updated"] is True
    absent = CliRunner().invoke(episode_debrief_group, ["synthesize", "--episode", "ep-" + str(uuid4()), "--vault-root", str(db.root), "--json"])
    assert absent.exit_code != 0 and "no durable debrief trigger" in absent.output


def test_source_cannot_be_read_from_another_vault(episode, tmp_path):
    db, _, _, docs = episode
    outside = tmp_path.parent / ("foreign-" + uuid4().hex + ".md")
    outside.write_text("foreign secret")
    docs[0]["payload"]["note_path"] = str(outside)
    hybrid._STORE.set_documents(docs)
    try:
        with pytest.raises(RuntimeError, match="outside"):
            run(episode)
    finally:
        outside.unlink()


def test_native_binding_isolation_uses_real_registry_and_effect_window(episode, monkeypatch):
    from tests.episode_debrief.test_trigger import _active_native_runtime
    from app.receipts.decision_receipt_log import iter_decision_receipts, decisions_receipts_dir
    db, _, _, docs = episode
    old_root = db.root
    receipts = iter_decision_receipts(old_root)
    first, _ = _active_native_runtime(db, monkeypatch)
    db.root = Path(first.path)
    initialize_test_vault(db.root)
    ep = db.episode(count=0, binding=first.vault_binding_id)
    for doc in docs:
        relative = doc['payload']['note_path']
        (db.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (db.root / relative).write_bytes((old_root / relative).read_bytes())
        _install_watcher_binding(db, ep, doc, binding=first.vault_binding_id)
        doc['payload']['vault_binding_id'] = first.vault_binding_id
    directory = decisions_receipts_dir(db.root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'decisions-202610.jsonl').write_text('\n'.join(json.dumps(record) for record in receipts) + '\n')
    hybrid._STORE.set_documents(docs)
    payload = {'episode_id': ep, 'debrief_id': debrief_id_for_episode(ep), 'scope': 'work', 'bound_artifact_count': 3}
    report = synthesis.synthesize_debrief(payload, vault_root=db.root, vault_binding_id=first.vault_binding_id, write_guard=ALLOW)
    assert report['status'] == 'created'
    assert (db.root / report['draft']).exists()
    fm, _ = load_frontmatter((db.root / report['draft']).read_text())
    from app.stores import get_object_store, resolve_object_store_port
    from uuid import UUID
    native_store = resolve_object_store_port(vault_binding_id=first.vault_binding_id).store
    for ref in fm['debrief_source_refs']:
        assert native_store.get(UUID(ref['artifact_id'])) is not None
        assert get_object_store().get(UUID(ref['artifact_id'])) is None
    assert fm['proposed_by']['cognition']['outcome'] != 'missing_input'
    # The same identities cannot borrow another binding's index provenance.
    for doc in docs:
        doc['payload']['vault_binding_id'] = 'foreign-binding'
    hybrid._STORE.set_documents(docs)
    ep2 = db.episode(count=0, binding=first.vault_binding_id)
    for doc in docs:
        _install_watcher_binding(db, ep2, doc, binding=first.vault_binding_id)
    with pytest.raises(create.UnresolvableCitationError):
        synthesis.synthesize_debrief({**payload, 'episode_id': ep2, 'debrief_id': debrief_id_for_episode(ep2)}, vault_root=db.root, vault_binding_id=first.vault_binding_id, write_guard=ALLOW)


def test_late_or_unbound_decision_receipts_are_not_synthesized(episode):
    db, _, _, docs = episode
    for oid in (docs[0]['doc_id'], str(uuid4())):
        append_decision_receipt(object_id=oid, key='review', value={'reason': 'OUTSIDE EPISODE'}, trace_id='fixture', created_at=datetime(2026, 10, 14, 9, tzinfo=timezone.utc), vault_root=db.root, vault_uuid=None)
    report = run(episode)
    assert 'OUTSIDE EPISODE' not in (db.root / report['draft']).read_text()


def test_debrief_destination_symlink_is_refused_before_receipt(episode, tmp_path_factory):
    db, _, _, _ = episode
    outside = tmp_path_factory.mktemp('foreign-debrief')
    target = db.root / '_system/episode-debriefs'
    target.parent.mkdir(exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match='outside'):
        run(episode)
    assert not list(outside.iterdir())


def test_episode_machine_writer_preserves_additive_debrief_ref(episode):
    from app.episodes.store import write_episode_note
    from app.episodes.notes import parse_episode_note_document
    db, ep, _, _ = episode
    run(episode)
    path = db.root / 'episodes' / f'{ep}.md'
    fields, _ = parse_episode_note_document(path.read_text())
    write_episode_note(title=fields['title'], scope=fields['scope'], start=fields['time']['start'],
                       end=fields['time'].get('end'), closed=True, episode_id=ep, vault_root=db.root,
                       space=fields.get('space'), goal=fields.get('goal'), protagonists=fields.get('protagonists'),
                       causation=fields.get('causation'), write_guard=ALLOW)
    assert parse_episode_note_document(path.read_text())[0]['debrief_ref'] == [debrief_id_for_episode(ep)]


def _install_watcher_binding(db, ep, doc, *, binding=None):
    import hashlib
    from psycopg.types.json import Jsonb
    from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
    from app.watcher.registry import ingest_vault_changed_payload
    binding = binding or COMPATIBILITY_BINDING_ID
    relative = doc['payload']['note_path']
    path = db.root / relative
    event = str(uuid4())
    payload = ingest_vault_changed_payload(vault_root=db.root, relative_path=Path(relative),
        mtime=datetime(2026, 10, 13, 9, tzinfo=timezone.utc).timestamp(),
        content_hash=hashlib.sha256(path.read_bytes()).hexdigest(), watcher='fixture')
    db.execute("INSERT INTO outbox(id,topic,payload,vault_binding_id) VALUES(%s,'ingest.vault.changed',%s,%s)", (event, Jsonb(payload), binding))
    db.execute("INSERT INTO episode_artifact_binding(vault_binding_id,artifact_ref,episode_id,scope,basis,confidence,binding_state,rule) VALUES(%s,%s,%s,'work','time_overlap',1,'active','fixture')", (binding,'vault.activity:'+event,ep))
    return event


def test_real_watcher_path_only_binding_resolves(episode):
    db, ep, _, docs = episode
    doc = docs[-1]
    db.execute("DELETE FROM episode_artifact_binding WHERE episode_id=%s AND artifact_ref IN (SELECT 'vault.activity:' || id::text FROM outbox WHERE topic='ingest.vault.changed' AND payload->>'relative_path'=%s)", (ep,doc['payload']['note_path']))
    _install_watcher_binding(db, ep, doc)
    assert run(episode)['status'] == 'created'


def test_retained_uuid_maps_to_canonical_source_identity(episode):
    db, _, _, docs = episode
    oid = docs[-1]['doc_id']
    retained = str(uuid4())
    path = db.root / docs[-1]['payload']['note_path']
    fields, body = load_frontmatter(path.read_text())
    fields['uuid'] = retained
    path.write_text(dump_frontmatter(fields, body))
    db.execute("INSERT INTO objects(id,uuid,kind,source_ref,payload) VALUES(%s,%s,'note','fixture','{}'::jsonb)", (oid,retained))
    assert run(episode)['status'] == 'created'


def test_source_uses_production_ingest_panel_normalization(episode, monkeypatch):
    from app.ingest import vault_alpha
    db, _, _, docs = episode
    path = db.root / docs[-1]['payload']['note_path']
    fields, body = load_frontmatter(path.read_text())
    fields.update(domain='work', review_state='reviewed')
    path.write_text(dump_frontmatter(fields, body + '\n%% AI:Start %%\nAI status text\n%% AI:End %%\n'))
    monkeypatch.setattr(vault_alpha, 'classify_run', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_alpha, 'index_ingest_object', lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, 'append_jsonl', lambda *_args, **_kwargs: None)
    result = vault_alpha.run_vault_alpha_ingest_paths(db.root, [path], force=True)
    assert result.ingested == 1
    from app.stores import get_object_store
    from uuid import UUID
    projection = get_object_store().get(UUID(docs[-1]['doc_id']))
    docs[-1]['text'] = projection['payload']['text']
    hybrid._STORE.set_documents(docs)
    report = run(episode)
    assert 'AI status text' not in (db.root / report['draft']).read_text()


def test_unlinked_replay_rechecks_source_scope(episode, monkeypatch):
    db, _, _, docs = episode
    real = synthesis.write_note_from_absolute
    monkeypatch.setattr(synthesis, 'write_note_from_absolute', lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError):
        run(episode)
    monkeypatch.setattr(synthesis, 'write_note_from_absolute', real)
    path = db.root / docs[-1]['payload']['note_path']
    fields, body = load_frontmatter(path.read_text())
    fields['scope'] = 'private'
    path.write_text(dump_frontmatter(fields, body))
    with pytest.raises((synthesis.DebriefSynthesisError, create.UnresolvableCitationError)):
        run(episode)


def test_completed_commitment_is_not_an_open_loop(episode):
    db, _, _, docs = episode
    path = db.root / docs[1]['payload']['note_path']
    fields, body = load_frontmatter(path.read_text())
    fields['commitment_state'] = 'done'
    path.write_text(dump_frontmatter(fields, body))
    _refresh_observation(db, path)
    report = run(episode)
    _, body = load_frontmatter((db.root / report['draft']).read_text())
    section = body.split('## open_loops\n',1)[1].split('\n## ',1)[0]
    assert '(none)' in section


def test_native_worker_consumes_compatibility_projection_trigger(episode, monkeypatch):
    from tests.episode_debrief.test_trigger import _active_native_runtime
    from app.workers.outbox_worker import _dispatch_topic
    from app.receipts.decision_receipt_log import decisions_receipts_dir
    import shutil
    db, ep, _, docs = episode
    old_root = db.root
    first, _ = _active_native_runtime(db, monkeypatch)
    db.root = Path(first.path)
    initialize_test_vault(db.root)
    shutil.copytree(old_root / 'episodes', db.root / 'episodes', dirs_exist_ok=True)
    for doc in docs:
        relative = doc['payload']['note_path']
        (db.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (db.root / relative).write_bytes((old_root / relative).read_bytes())
    shutil.copytree(decisions_receipts_dir(old_root), decisions_receipts_dir(db.root), dirs_exist_ok=True)
    db.tick()
    payload = db.execute("SELECT payload->'payload' FROM outbox WHERE topic='debrief.trigger.created' AND vault_binding_id=%s", (first.vault_binding_id,))[0][0]
    _dispatch_topic('debrief.trigger.created', payload, trace_id='native', message={'vault_binding_id':first.vault_binding_id,'payload_schema':'debrief.trigger.created.v1'}, vault_root=db.root)
    assert (db.root / '_system/episode-debriefs' / f'{debrief_id_for_episode(ep)}.md').exists()


def _refresh_observation(db, path):
    import hashlib
    from psycopg.types.json import Jsonb
    db.execute("UPDATE outbox SET payload=jsonb_set(payload,'{hash}',%s::jsonb) WHERE topic='ingest.vault.changed' AND payload->>'relative_path'=%s", (Jsonb(hashlib.sha256(path.read_bytes()).hexdigest()), str(path.relative_to(db.root))))


@pytest.mark.parametrize('change', ['scope', 'membership'])
def test_source_changes_during_cognition_cannot_be_linked(episode, monkeypatch, change):
    db, ep, _, docs = episode
    original = create.run_create_pass
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == 'scope':
            path = db.root / docs[-1]['payload']['note_path']
            fields, body = load_frontmatter(path.read_text())
            fields['scope'] = 'private'
            path.write_text(dump_frontmatter(fields, body))
        else:
            db.execute("DELETE FROM episode_artifact_binding WHERE episode_id=%s", (ep,))
        return result
    monkeypatch.setattr(create, 'run_create_pass', changed)
    with pytest.raises((synthesis.DebriefSynthesisError, create.UnresolvableCitationError)):
        run(episode)
    fields, _ = load_frontmatter((db.root / 'episodes' / f'{ep}.md').read_text())
    assert not fields.get('debrief_ref')


@pytest.mark.parametrize('change', ['missing_hash', 'late', 'changed'])
def test_closure_state_requires_matching_observation(episode, change):
    from psycopg.types.json import Jsonb
    db, _, _, docs = episode
    relative = docs[1]['payload']['note_path']
    if change == 'changed':
        path = db.root / relative
        fields, body = load_frontmatter(path.read_text())
        fields['commitment_state'] = 'done'
        path.write_text(dump_frontmatter(fields, body))
    else:
        key, value = ('hash', None) if change == 'missing_hash' else ('mtime', datetime(2026,10,14,tzinfo=timezone.utc).timestamp())
        db.execute("UPDATE outbox SET payload=jsonb_set(payload,ARRAY[%s],%s::jsonb) WHERE topic='ingest.vault.changed' AND payload->>'relative_path'=%s", (key, Jsonb(value), relative))
    with pytest.raises(create.UnresolvableCitationError):
        run(episode)
