from __future__ import annotations

from copy import deepcopy

import pytest

from tests.cli.test_index_rebuild_cli import _legacy_source_fixture


def _enable_registry(monkeypatch, root, *, scope="*.md,**/*.md"):
    from tests.helpers.vault_settings import initialize_test_vault
    initialize_test_vault(root)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", scope)


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


def test_enabled_entrypoint_consumes_shared_inventory(monkeypatch, tmp_path):
    from scripts import fs_watcher
    from tests.watcher.test_fs_watcher import RecordingVaultPort
    from app.ingest.producer_policy import filesystem_producer_policy
    root = tmp_path / "watcher-vault"
    root.mkdir()
    source = root / "source.md"
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


def test_disabled_optional_producer_does_not_block_exact_retirement(monkeypatch, tmp_path):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "false")
    monkeypatch.setenv("VAULT_DIR", str(root))
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert state.rows == [] and state.vectors == {} and state.embedded == []
    assert source.read_bytes() == raw


@pytest.mark.parametrize("failure, reason", [
    ("policy", "legacy_producer_policy_refused"), ("source", "legacy_source_refused"),
    ("candidate", "legacy_admission_refused"), ("identity", "legacy_identity_refused"),
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


@pytest.mark.parametrize("marker", ["candidate_only: true", "authority: {source_authoritative: false}",
                                 "trust: external", "review_state: draft"])
def test_native_registry_claim_does_not_bypass_source_admission(monkeypatch, tmp_path, marker):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    _enable_registry(monkeypatch, root)
    source.write_text(raw.decode().replace("trust: human\nreview_state: reviewed", marker))
    with pytest.raises(recovery.LegacySourceRefusal, match="legacy_admission_refused"):
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
