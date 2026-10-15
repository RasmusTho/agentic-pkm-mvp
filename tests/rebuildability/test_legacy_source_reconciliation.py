from __future__ import annotations

from copy import deepcopy

import pytest

from tests.cli.test_index_rebuild_cli import _legacy_source_fixture


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


def test_enabled_broader_producer_reprojects_with_admission_evidence(monkeypatch, tmp_path):
    from app.ingest import vault_alpha
    from app.services.vault_sync import prepare_note_projection
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "true")
    monkeypatch.setenv("VAULT_DIR", str(root))
    monkeypatch.setattr(vault_alpha, "_ingest_single", lambda *a, **kw: pytest.fail("broader source laundered through alpha"))
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    parsed, body, error = parse_bounded_frontmatter(raw.decode())
    expected = prepare_note_projection(source, parsed, body, vault_root=root)
    projected = state.rows[0]
    assert projected["object_id"] == original["object_id"]
    assert projected["payload"] == {**expected, "artifact_id": str(original["object_id"]), "stable_id": str(original["object_id"])}
    assert projected["payload"]["frontmatter"]["trust"] == "human"
    assert state.embedded == [expected["content"]] and len(state.vectors) == 1
    assert source.read_bytes() == raw
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0


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
