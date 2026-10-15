from __future__ import annotations

from copy import deepcopy

import pytest

from tests.cli.test_index_rebuild_cli import _legacy_source_fixture


@pytest.mark.parametrize("location", ["source", "payload", "core6"])
@pytest.mark.parametrize("marker,reason", [
    ({"candidate_only": True}, "legacy_candidate_refused"),
    ({"candidate_only": "false"}, "legacy_candidate_refused"),
    ({"artifact_class": "youtube_source_note"}, "legacy_candidate_refused"),
    ({"artifact_class": "youtube_source_note_proposal"}, "legacy_candidate_refused"),
    ({"authority": "private-canary"}, "legacy_authority_refused"),
    ({"authority": {"source_authoritative": False}}, "legacy_authority_refused"),
    ({"authority": {"requires_review": True}}, "legacy_authority_refused"),
    ({"authority": {"source_authoritative": "true"}}, "legacy_authority_refused"),
    ({"authority": {"requires_review": "false"}}, "legacy_authority_refused"),
    ({"trust": "private-canary"}, "legacy_trust_refused"),
    ({"review_state": "draft"}, "legacy_trust_refused"),
])
def test_admission_refusals_preserve_finite_branch_specific_reason(monkeypatch, tmp_path, location, marker, reason):
    from copy import deepcopy
    import json
    import yaml
    from click.testing import CliRunner
    from app.cli import cli, index_rebuild

    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    if location == "source":
        source.write_text(raw.decode().replace("---\ncanonical", yaml.safe_dump(marker) + "---\ncanonical"))
    elif location == "core6":
        state.rows[0]["payload"]["core6"] = marker
    else:
        state.rows[0]["payload"].update(marker)
    before = deepcopy(state.rows)
    source_before = source.read_bytes()
    monkeypatch.setattr(index_rebuild.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(index_rebuild, "get_vector_index", lambda: index)
    monkeypatch.setattr(index_rebuild, "get_product_embedding_client", factory)
    result = CliRunner().invoke(cli, ["index", "reconcile-legacy", "--json"])
    assert result.exit_code == 79
    assert json.loads(result.output) == {"reason": reason}
    assert state.rows == before and not state.calls and not state.vectors and not state.embedded
    assert source.read_bytes() == source_before


@pytest.mark.parametrize("branch,reason", [
    ("origin", "legacy_origin_refused"),
    ("core6", "legacy_payload_shape_refused"),
    ("system", "legacy_system_path_refused"),
    ("profile", "legacy_profile_refused"),
])
def test_admission_context_refusals_are_private_and_preserve_source(monkeypatch, tmp_path, branch, reason):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    if branch == "origin":
        state.rows[0]["payload"]["origin"] = "private-canary"
    elif branch == "core6":
        state.rows[0]["payload"]["core6"] = "private-canary"
    elif branch == "system":
        target = root / "_system" / "drafts" / "private-canary.md"
        target.parent.mkdir(parents=True)
        source.rename(target)
        source = target
        state.rows[0]["source_ref"] = str(target)
    else:
        monkeypatch.setattr(recovery, "assert_profile_note_ingestible", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private-canary")))
    from copy import deepcopy
    before = deepcopy(state.rows)
    with pytest.raises(recovery.LegacySourceRefusal) as caught:
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert str(caught.value) == reason
    assert state.rows == before and not state.calls and not state.vectors and not state.embedded
    assert source.read_bytes() == raw


@pytest.mark.parametrize("typed", [False, True])
def test_unexpected_private_failure_retains_generic_fallback(monkeypatch, tmp_path, typed):
    import json
    from click.testing import CliRunner
    from app.cli import cli, index_rebuild

    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(index_rebuild.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(index_rebuild, "get_vector_index", lambda: index)
    monkeypatch.setattr(index_rebuild, "get_product_embedding_client", factory)

    def refuse():
        raise recovery.LegacySourceRefusal("private-canary") if typed else RuntimeError("private-canary")

    monkeypatch.setattr(index, "present_object_ids", refuse)
    result = CliRunner().invoke(cli, ["index", "reconcile-legacy", "--json"])
    assert result.exit_code == 79
    assert json.loads(result.output) == {"reason": "legacy_source_refused"}
    assert state.rows == [original] and not state.calls and not state.vectors
    assert source.read_bytes() == raw


def _enable_registry(monkeypatch, root, *, scope="*.md,**/*.md"):
    from tests.helpers.vault_settings import initialize_test_vault
    initialize_test_vault(root)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", scope)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")


def test_producer_applicability_uses_canonical_runtime_configuration(monkeypatch, tmp_path):
    from app.ingest.producer_policy import filesystem_producer_policy
    from scripts import fs_watcher
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "0")
    monkeypatch.setenv("VAULT_DIR", str(root))
    assert not filesystem_producer_policy().includes(source)
    monkeypatch.setattr(fs_watcher, "_default_vault_port", lambda: pytest.fail("disabled producer constructed writer"))
    fs_watcher.run()
    fs_watcher.scan_once()
    monkeypatch.setenv("FS_WATCHER_ENABLE", "unknown-private-canary")
    with pytest.raises(ValueError, match="producer policy ambiguous"):
        fs_watcher.run()
    with pytest.raises(recovery.LegacySourceRefusal, match="legacy_producer_policy_refused"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and not state.calls and not state.vectors


@pytest.mark.parametrize("filename", ["source.md", ".md"])
def test_enabled_entrypoint_consumes_shared_inventory(monkeypatch, tmp_path, filename):
    from scripts import fs_watcher
    from tests.watcher.test_fs_watcher import RecordingVaultPort
    from app.ingest.producer_policy import filesystem_producer_policy
    root = tmp_path / "watcher-vault"
    root.mkdir()
    source = root / filename
    source.write_text("---\nuuid: 68cb2581-17db-4c94-83bf-b2aee37e6ebc\n---\nbody")
    excluded = root / ".obsidian-hidden" / "source.md"
    excluded.parent.mkdir()
    excluded.write_text(source.read_text())
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    monkeypatch.setattr(fs_watcher, "VAULT", root)
    monkeypatch.setattr(fs_watcher, "STATE", {})
    monkeypatch.setattr(fs_watcher, "UUID_INDEX", {})
    monkeypatch.setattr(fs_watcher, "active_edit", lambda _: False)
    port = RecordingVaultPort()
    monkeypatch.setattr(fs_watcher, "_default_vault_port", lambda: port)
    fs_watcher.scan_once()
    assert [item[0] for item in port.upserts] == [str(source)]
    assert filesystem_producer_policy().includes(source)
    assert not filesystem_producer_policy().includes(excluded)
    fs_watcher.scan_once()
    assert not port.deletes and str(source) in fs_watcher.STATE


@pytest.mark.parametrize("inbox, id_only", [(True, True), (False, True), (True, False)])
def test_native_registry_requires_identity_preserved_by_actual_inbox_healer(monkeypatch, tmp_path, inbox, id_only):
    from app.services import note_uuid
    from app.workers import outbox_worker
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    _enable_registry(monkeypatch, root)
    if inbox:
        inbox_dir = root / "Inbox"
        inbox_dir.mkdir(exist_ok=True)
        destination = inbox_dir / source.name
        source.rename(destination)
        source = destination
        state.rows[0]["source_ref"] = original["source_ref"] = str(source)
    if id_only:
        source.write_text(raw.decode().replace("uuid:", "id:"))
    before = source.read_bytes()
    if inbox and id_only:
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_refused"):
            recovery.reconcile_legacy_sources(binding, index, factory)
        assert state.rows == [original] and not state.calls and not state.vectors
    else:
        assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert source.read_bytes() == before
    writes = []
    monkeypatch.setattr(note_uuid.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)
    monkeypatch.setattr(note_uuid, "write_note_from_absolute", lambda *args, **kwargs: writes.append(args))
    actual_healed = outbox_worker._maybe_heal_uuid(source, root)
    if inbox and id_only:
        assert actual_healed != str(original["object_id"]) and writes
    else:
        assert actual_healed == (str(original["object_id"]) if inbox else "") and not writes
    assert source.read_bytes() == before


def test_disabled_optional_producer_does_not_block_exact_retirement(monkeypatch, tmp_path):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "false")
    monkeypatch.setenv("VAULT_DIR", str(root))
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert state.rows == [] and state.vectors == {} and state.embedded == []
    assert source.read_bytes() == raw


@pytest.mark.parametrize("nested_source", [False, True])
def test_filesystem_identity_proof_uses_full_nested_inventory(monkeypatch, tmp_path, nested_source):
    from app.ingest.producer_policy import filesystem_producer_policy
    from tests.helpers.vault_settings import initialize_test_vault
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    nested = root / "Nested"
    initialize_test_vault(nested)
    nested_note = nested / "note.md"
    if nested_source:
        source.rename(nested_note)
        source = nested_note
        state.rows[0]["source_ref"] = str(source)
        original["source_ref"] = str(source)
    else:
        nested_note.write_bytes(raw)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    assert filesystem_producer_policy().includes(nested_note)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    if nested_source:
        assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
        assert state.rows[0]["payload"]["replay"]["source_identity"] == "Nested/note.md"
    else:
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_refused"):
            recovery.reconcile_legacy_sources(binding, index, factory)
        assert state.rows == [original] and not state.calls and not state.vectors
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


@pytest.mark.parametrize("identity", ["id-only", "wikilink", "list", "upper", "hex"])
def test_filesystem_claim_requires_uuid_form_preserved_by_real_adapter(monkeypatch, tmp_path, identity):
    from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    oid = str(original["object_id"])
    replacement = {"id-only": f"id: {oid}", "wikilink": f"uuid: '[[{oid}]]'",
                   "list": f"uuid: [{oid}]", "upper": f"uuid: {oid.upper()}",
                   "hex": f"uuid: '{oid.replace('-', '')}'"}[identity]
    source.write_text(raw.decode().replace(f"uuid: {oid}", replacement))
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    before = source.read_bytes()
    if identity in {"upper", "hex"}:
        adapter = FilesystemVaultAdapter(vault_root=root, backend_writes_enabled=False)
        preserved = adapter.ensure_uuid(adapter.read_note(source))
        assert not preserved.wrote
        assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    else:
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_refused"):
            recovery.reconcile_legacy_sources(binding, index, factory)
        assert state.rows == [original] and not state.calls and not state.vectors
    assert source.read_bytes() == before


def test_filesystem_inventory_drift_during_embedding_refuses(monkeypatch, tmp_path):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    duplicate_dir = root / "Race"
    duplicate_dir.mkdir()
    client = factory()
    def embed(_text):
        (duplicate_dir / "duplicate.md").write_bytes(raw)
        return [1., 2.]
    client.embed_text = embed
    with pytest.raises(recovery.LegacySourceRefusal, match="legacy_producer_policy_refused"):
        recovery.reconcile_legacy_sources(binding, index, lambda **kwargs: client)
    assert state.rows == [original] and not state.calls and not state.vectors
    assert source.read_bytes() == raw


def test_filesystem_incomplete_inventory_refuses_without_constructing_writer(monkeypatch, tmp_path):
    import os
    from scripts import fs_watcher
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    monkeypatch.setattr(fs_watcher, "VAULT", root)
    monkeypatch.setattr(fs_watcher, "_default_vault_port", lambda: pytest.fail("incomplete scan constructed writer"))
    original_scandir = os.scandir
    def scandir(path):
        if str(path) == str(source.parent):
            raise PermissionError("private-canary")
        return original_scandir(path)
    monkeypatch.setattr(os, "scandir", scandir)
    with pytest.raises(PermissionError):
        fs_watcher.scan_once()
    with pytest.raises(recovery.LegacySourceRefusal, match="legacy_producer_policy_refused"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and not state.calls and not state.vectors
    assert source.read_bytes() == raw


@pytest.mark.parametrize("failure, reason", [
    ("policy", "legacy_producer_policy_refused"), ("source", "legacy_source_refused"),
    ("candidate", "legacy_candidate_refused"), ("identity", "legacy_identity_refused"),
    ("drift", "legacy_race_refused"), ("row", "legacy_write_failed"),
    ("embed", "embedding_generation_failed"),
])
def test_private_cli_preserves_only_finite_reason_classes(monkeypatch, tmp_path, failure, reason):
    import json
    from click.testing import CliRunner
    from app.cli import cli, index_rebuild
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path, selected=True)
    if failure == "policy":
        monkeypatch.setenv("FS_WATCHER_ENABLE", "private-canary")
    elif failure == "source":
        source.unlink()
    elif failure == "candidate":
        source.write_text(raw.decode().replace("trust: human", "candidate_only: true\ntrust: human"))
    elif failure == "identity":
        source.write_text(raw.decode().replace(str(original["object_id"]), "private-canary"))
    elif failure == "drift":
        source.write_text(raw.decode() + "private-canary")
    else:
        state.fail = failure
    monkeypatch.setattr(index_rebuild.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(index_rebuild, "get_vector_index", lambda: index)
    monkeypatch.setattr(index_rebuild, "get_product_embedding_client", factory)
    result = CliRunner().invoke(cli, ["index", "reconcile-legacy", "--json"])
    assert result.exit_code == 79
    assert json.loads(result.output) == {"reason": reason}
    assert state.rows == [original] and state.vectors == {} and state.calls == []


@pytest.mark.parametrize("producer_kind", ["filesystem", "registry"])
def test_enabled_broader_producer_reprojects_with_admission_evidence(monkeypatch, tmp_path, producer_kind):
    from app.ingest import vault_alpha
    from app.services.vault_sync import prepare_note_projection
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    if producer_kind == "registry":
        _enable_registry(monkeypatch, root)
    else:
        monkeypatch.setenv("FS_WATCHER_ENABLE", "true")
        monkeypatch.setenv("VAULT_DIR", str(root))
    monkeypatch.setattr(vault_alpha, "_ingest_single", lambda *a, **kw: pytest.fail("broader source laundered through alpha"))
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    parsed, body, error = parse_bounded_frontmatter(raw.decode())
    if producer_kind == "registry":
        from app.services.indexer import prepare_ingest_projection, watched_note_ingest_object
        event = watched_note_ingest_object(source, parsed, body, note_uuid=str(original["object_id"]),
                                          source_text=raw.decode(), observation={})
        expected, _text, metadata = prepare_ingest_projection(event,
            incoming_uuid=str(original["object_id"]), vault_root=root, source_snapshot=raw.decode())
        expected.update(metadata)
    else:
        expected = prepare_note_projection(source, parsed, body, vault_root=root)
    projected = state.rows[0]
    assert projected["object_id"] == original["object_id"]
    assert projected["payload"] == {**expected, "artifact_id": str(original["object_id"]), "stable_id": str(original["object_id"])}
    assert projected["payload"]["frontmatter"]["trust"] == "human"
    assert state.embedded == [expected["content"]] and len(state.vectors) == 1
    assert source.read_bytes() == raw
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0


@pytest.mark.parametrize("state", ["enabled", "disabled", "scoped-out"])
def test_native_registry_uses_actual_config_and_incremental_inventory(monkeypatch, tmp_path, state):
    from app.ingest.producer_policy import registry_producer_policy
    from app.watcher.registry import DEFAULT_REGISTRY_CONFIG_PATH, load_registry_config, source_backed_registry_inventory
    recovery, store, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    (root / "Notes").mkdir(exist_ok=True)
    _enable_registry(monkeypatch, root, scope="Notes/**/*.md" if state == "scoped-out" else "*.md,**/*.md")
    if state == "disabled":
        monkeypatch.setenv("WATCHER_ENABLE", "0")
    cfg = load_registry_config(DEFAULT_REGISTRY_CONFIG_PATH)
    policy = registry_producer_policy(root)
    assert cfg.enable == policy.enabled
    if cfg.enable:
        assert policy.sources == source_backed_registry_inventory(cfg)
    assert policy.includes(source) == (state == "enabled")
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert bool(store.rows) == (state == "enabled")
    assert source.read_bytes() == raw


@pytest.mark.parametrize("failure", ["missing-root", "malformed-enable", "foreign-root", "scope-race", "missing-scope-root", "uninitialized-root", "missing-identity", "registry-config"])
def test_native_registry_policy_ambiguity_or_drift_refuses_atomically(monkeypatch, tmp_path, failure):
    from app.watcher import registry
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    _enable_registry(monkeypatch, root)
    if failure == "missing-root":
        monkeypatch.delenv("WATCHER_VAULT_PATH")
    elif failure == "malformed-enable":
        monkeypatch.setenv("WATCHER_ENABLE", "private-canary")
    elif failure == "foreign-root":
        monkeypatch.setenv("WATCHER_VAULT_PATH", str(root.parent))
    elif failure == "missing-scope-root":
        monkeypatch.setenv("WATCHER_SCOPE_GLOB", "Missing/**/*.md")
    elif failure == "uninitialized-root":
        (root / "settings" / "vault.md").unlink()
    elif failure == "missing-identity":
        settings = root / "settings" / "vault.md"
        import re
        settings.write_text(re.sub(r"^vaultId:.*\n", "", settings.read_text(), flags=re.MULTILINE))
    elif failure == "registry-config":
        malformed = tmp_path / "watchers.yaml"
        malformed.write_text("version: 1\nwatchers:\n- name: unknown\n  emit_event: private-canary\n")
        monkeypatch.setattr(registry, "DEFAULT_REGISTRY_CONFIG_PATH", malformed)
    else:
        def embed(_text):
            monkeypatch.setenv("WATCHER_SCOPE_GLOB", "Outside/*.md")
            return [1., 2.]
        client = factory()
        client.embed_text = embed
        factory = lambda **kwargs: client
    settings_before = {path: path.read_bytes() for path in (root / "settings").glob("*.md")}
    with pytest.raises(recovery.LegacySourceRefusal, match="legacy_producer_policy_refused"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and state.vectors == {} and state.calls == []
    assert source.read_bytes() == raw
    assert {path: path.read_bytes() for path in (root / "settings").glob("*.md")} == settings_before


@pytest.mark.parametrize("marker,reason", [("candidate_only: true", "legacy_candidate_refused"),
    ("authority: {source_authoritative: false}", "legacy_authority_refused"),
    ("trust: external", "legacy_trust_refused"), ("review_state: draft", "legacy_trust_refused")])
def test_native_registry_claim_does_not_bypass_source_admission(monkeypatch, tmp_path, marker, reason):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    _enable_registry(monkeypatch, root)
    source.write_text(raw.decode().replace("trust: human\nreview_state: reviewed", marker))
    with pytest.raises(recovery.LegacySourceRefusal, match=reason):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and state.vectors == {} and state.calls == [] and state.embedded == []


@pytest.mark.parametrize("failure", ["missing-root", "relative-root", "missing-path", "malformed-enable", "other-root", "race"])
def test_ambiguous_or_racing_producer_configuration_is_atomic_and_refused(monkeypatch, tmp_path, failure):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    if failure == "missing-root":
        monkeypatch.delenv("VAULT_DIR")
    elif failure == "relative-root":
        monkeypatch.setenv("VAULT_DIR", "vault")
    elif failure == "missing-path":
        monkeypatch.setenv("VAULT_DIR", str(root / "missing"))
    elif failure == "malformed-enable":
        monkeypatch.setenv("FS_WATCHER_ENABLE", "private-canary")
    elif failure == "other-root":
        monkeypatch.setenv("VAULT_DIR", str(root.parent))
    else:
        def embed(_text):
            monkeypatch.setenv("FS_WATCHER_ENABLE", "0")
            return [1., 2.]
        client = factory()
        client.embed_text = embed
        factory = lambda **kwargs: client
    before = deepcopy(state.rows)
    with pytest.raises(recovery.LegacySourceRefusal) as caught:
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert caught.value.reason == "legacy_producer_policy_refused"
    assert state.rows == before and state.calls == [] and state.vectors == {}
    assert source.read_bytes() == raw
