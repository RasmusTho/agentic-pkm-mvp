from __future__ import annotations

from copy import deepcopy

import pytest

from tests.cli.test_index_rebuild_cli import _legacy_source_fixture


def _persist_companion_identity(root, source, oid):
    from app.ingest import vault_alpha as producer
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.companion_note import CompanionNote, companion_path, write_companion

    source.write_text(source.read_text().replace(f"uuid: {oid}\n", ""))
    _, body, _ = parse_bounded_frontmatter(source.read_text())
    companion = CompanionNote(uuid=str(oid), source_ref=source.relative_to(root).as_posix(),
        title=producer._derive_title(body, source),
        content_hash=str(producer._compute_ingest_fingerprint(body.strip(), source)["text_sha256"]),
        ingest_state="tracked", last_ingested="", created_by_instance="fixture")
    write_companion(root, companion)
    return root / companion_path(str(oid), root)


@pytest.mark.parametrize("location", ["canonical", "legacy"])
def test_persisted_companion_identity_allows_only_exact_excluded_retirement(monkeypatch, tmp_path, location):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    companion = _persist_companion_identity(root, source, original["object_id"])
    if location == "legacy":
        destination = root / "_system/companions" / companion.name
        destination.parent.mkdir(parents=True)
        companion.rename(destination)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert not state.rows and not state.vectors and not state.embedded
    assert len(state.calls) == 1
    assert state.calls[0]["replacement"] is None and state.calls[0]["vector"] is None
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0


@pytest.mark.parametrize("producer", ["alpha", "filesystem", "registry"])
@pytest.mark.parametrize("location", ["canonical", "legacy"])
def test_persisted_companion_identity_never_authorizes_reprojection(monkeypatch, tmp_path, producer, location):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=producer == "alpha")
    companion = _persist_companion_identity(root, source, original["object_id"])
    if location == "legacy":
        destination = root / "_system/companions" / companion.name
        destination.parent.mkdir(parents=True)
        companion.rename(destination)
    if producer == "filesystem":
        monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
        monkeypatch.setenv("VAULT_DIR", str(root))
    elif producer == "registry":
        _enable_registry(monkeypatch, root)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    with pytest.raises(recovery.LegacySourceRefusal, match="^legacy_identity_producer_refused$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and not state.calls and not state.vectors and not state.embedded
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


@pytest.mark.parametrize("location", ["canonical", "legacy"])
@pytest.mark.parametrize("other_first", [False, True])
def test_companion_discovery_filters_title_before_selection_in_every_location(monkeypatch, tmp_path, location, other_first):
    from dataclasses import replace
    from pathlib import Path
    from uuid import uuid4
    from app.services.companion_note import read_companion, write_companion

    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    companion_path = _persist_companion_identity(root, source, original["object_id"])
    companion = read_companion(root, str(original["object_id"]))
    source.write_text(source.read_text().replace("---\n", "---\ntitle: Target\n", 1))
    write_companion(root, replace(companion, title="Target"))
    # An unrelated continuity observation can share template body text while
    # declaring a different title. It must not shadow the one eligible match.
    other_uuid = str(uuid4())
    write_companion(root, replace(companion, uuid=other_uuid, title="Other", source_ref="other.md"))
    canonical_dir = companion_path.parent
    if location == "legacy":
        destination = root / "_system/companions" / companion_path.name
        destination.parent.mkdir(parents=True)
        companion_path.rename(destination)
    glob = Path.glob
    def ordered_glob(path, pattern):
        found = list(glob(path, pattern))
        if path == canonical_dir and pattern == "*.md":
            found.sort(key=lambda item: (item.stem == other_uuid) != other_first)
        return iter(found)
    monkeypatch.setattr(Path, "glob", ordered_glob)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert not state.rows and not state.embedded and not state.vectors
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_enabled_producer_companion_claim_is_not_hidden_as_metadata(monkeypatch, tmp_path):
    from app.ingest.producer_policy import filesystem_producer_policy

    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    companion = _persist_companion_identity(root, source, original["object_id"])
    source.write_bytes(raw)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    policy = filesystem_producer_policy()
    assert policy.includes(source) and policy.includes(companion)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    with pytest.raises(recovery.LegacySourceRefusal, match="^legacy_identity_ambiguous_refused$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and not state.calls and not state.vectors and not state.embedded
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def _effective_producer_collision(monkeypatch, root, source, raw, original, producer_kind):
    from app.ingest import vault_alpha as producer
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter

    other = root / "Notes" / str(original["object_id"]) / "other.md"
    other.parent.mkdir(parents=True)
    declaration = "uuid: invalid\n" if producer_kind == "alpha-invalid" else ""
    if (producer_kind.startswith("registry-") and producer_kind != "registry-derived") or producer_kind == "filesystem-integer":
        from uuid import UUID
        identity = str(original["object_id"])
        key = "id" if "-id-" in producer_kind else "uuid"
        value = f"[{identity}, 00000000-0000-0000-0000-000000000000]"
        if producer_kind.endswith("nested"):
            value = f"[{value}]"
        elif producer_kind.endswith("integer"):
            value = f"{original['object_id'].int:039d}"[-32:]
            identity = str(UUID(value))
        declaration = f"{key}: {value}\n"
    derived = "agent_maintained: true\nread_only: true\nauthority_role: derived\n" if producer_kind == "registry-derived" else ""
    other.write_text(f"---\n{declaration}{derived}trust: human\n---\nunrelated producer body\n")
    parsed, body, _ = parse_bounded_frontmatter(other.read_text())
    effective = producer.resolve_vault_note_identity(other, vault_root=root, frontmatter=parsed, body=body).note_uuid
    if producer_kind.startswith("registry-") or producer_kind == "filesystem-integer":
        from app.ingest.producer_policy import registry_producer_policy
        from app.services.note_uuid import ensure_note_uuid
        # Prove the real read-only derived branch, not alpha's applicability.
        if producer_kind == "registry-derived":
            effective = ensure_note_uuid(other, vault_root=root)
        elif producer_kind.startswith("registry-"):
            from app.workers.outbox_worker import _normalize_uuid_value
            effective = str(UUID(_normalize_uuid_value(parsed.get("uuid") or parsed.get("id"))))
            assert effective == identity
        else:
            from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter
            adapter = FilesystemVaultAdapter(vault_root=root, backend_writes_enabled=False)
            preserved = adapter.ensure_uuid(adapter.read_note(other))
            assert not preserved.wrote
            effective = str(UUID(preserved.uuid_value))
        (root / "Alpha").mkdir()
        (root / "⚙️ System" / "vault.layout.md").write_text("---\ninclude_folders: [Alpha]\n---\nLayout.\n")
        if producer_kind.startswith("registry-"):
            _enable_registry(monkeypatch, root, scope="Notes/*.md,Notes/**/*.md")
            assert registry_producer_policy(root).includes(other)
        else:
            monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
            monkeypatch.setenv("VAULT_DIR", str(root))
        assert other not in producer.select_source_backed_rebuild_candidates(root)
    else:
        assert other in producer.select_source_backed_rebuild_candidates(root)
    assert source not in producer.select_source_backed_rebuild_candidates(root)
    source.write_text(raw.decode().replace(str(original["object_id"]), effective))
    return effective


@pytest.mark.parametrize("producer_kind", ["alpha", "alpha-invalid", "registry-derived",
    "registry-uuid-multi", "registry-id-multi", "registry-uuid-nested", "registry-id-nested", "registry-uuid-integer", "filesystem-integer"])
@pytest.mark.parametrize("phase", ["discovery", "transaction"])
def test_effective_producer_identity_is_a_denial_claim_not_retirement_authority(monkeypatch, tmp_path, producer_kind, phase):
    from uuid import UUID

    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    effective = _effective_producer_collision(monkeypatch, root, source, raw, original, producer_kind)
    state.rows[0]["object_id"] = UUID(effective)
    other = next((root / "Notes").rglob("other.md"))
    other_bytes = other.read_bytes()
    if phase == "transaction":
        other.unlink()
        reconcile = binding.store.reconcile_legacy_source
        def racing(*args, **kwargs):
            other.write_bytes(other_bytes)
            return reconcile(*args, **kwargs)
        monkeypatch.setattr(binding.store, "reconcile_legacy_source", racing)
    before_rows = deepcopy(state.rows)
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    reason = "legacy_producer_policy_refused" if phase == "transaction" and (producer_kind.startswith("registry-") or producer_kind == "filesystem-integer") else "legacy_identity_ambiguous_refused"
    with pytest.raises(recovery.LegacySourceRefusal, match=f"^{reason}$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == before_rows and not state.calls and not state.vectors
    if phase != "transaction" or producer_kind != "filesystem-integer":
        assert not state.embedded
    if phase == "transaction":
        before[other] = other_bytes  # Only the simulated concurrent writer changed this source.
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_producer_claim_of_canonical_object_alias_refuses_before_reprojection(monkeypatch, tmp_path):
    from uuid import uuid4
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path, selected=True)
    source.write_text(raw.decode().replace(str(original["object_id"]), str(uuid4())))
    other = source.parent / "other.md"
    other.write_text(f"---\nuuid: {original['object_id']}\n---\nunrelated source\n")
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    with pytest.raises(recovery.LegacySourceRefusal, match="^legacy_identity_ambiguous_refused$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == [original] and not state.calls and not state.vectors and not state.embedded
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


@pytest.mark.parametrize("failure,reason", [
    ("missing", "legacy_identity_persistence_refused"),
    ("unpersisted-fingerprint", "legacy_identity_persistence_refused"),
    ("invalid-companion", "legacy_identity_persistence_refused"),
    ("invalid", "legacy_identity_persistence_refused"),
    ("invalid-with-companion", "legacy_identity_persistence_refused"),
    ("invalid-shape", "legacy_identity_persistence_refused"),
    ("mismatch", "legacy_identity_mismatch_refused"),
    ("stored-mismatch", "legacy_identity_mismatch_refused"),
    ("duplicate", "legacy_identity_ambiguous_refused"),
    ("companion-duplicate", "legacy_identity_ambiguous_refused"),
    ("legacy-companion-duplicate", "legacy_identity_ambiguous_refused"),
    ("companion-foreign-source", "legacy_identity_mismatch_refused"),
    ("companion-moved-source", "legacy_identity_mismatch_refused"),
    ("companion-symlink", "legacy_identity_persistence_refused"),
    ("companion-race", "legacy_race_refused"),
    ("companion-removed", "legacy_race_refused"),
])
def test_identity_retirement_preserves_all_authority_refusals(monkeypatch, tmp_path, failure, reason):
    from uuid import uuid4
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    companion = _persist_companion_identity(root, source, original["object_id"])
    if failure in {"missing", "invalid", "invalid-shape", "unpersisted-fingerprint"}:
        companion.unlink()
    if failure == "unpersisted-fingerprint":
        from app.ingest import vault_alpha
        monkeypatch.setattr(vault_alpha, "_find_companion_by_fingerprint", lambda *args: str(original["object_id"]))
    elif failure == "invalid-companion":
        companion.write_text(companion.read_text().replace(str(original["object_id"]), "not-a-valid-uuid"))
    elif failure.startswith("invalid"):
        marker = "{}" if failure == "invalid-shape" else "private-invalid-identity"
        source.write_text(source.read_text().replace("---\n", f"---\nuuid: {marker}\n", 1))
    elif failure == "mismatch":
        state.rows[0]["object_id"] = uuid4()
    elif failure == "stored-mismatch":
        state.rows[0]["payload"]["vault_uuid"] = str(uuid4())
    elif failure == "duplicate":
        (root / "duplicate.md").write_bytes(source.read_bytes())
    elif failure == "companion-duplicate":
        other = companion.with_name(f"{uuid4()}.md")
        other.write_bytes(companion.read_bytes())
    elif failure == "legacy-companion-duplicate":
        other = root / "_system/companions" / companion.name
        other.parent.mkdir(parents=True)
        other.write_bytes(companion.read_bytes())
    elif failure in {"companion-foreign-source", "companion-moved-source"}:
        destination = "/foreign-root/note.md" if failure == "companion-foreign-source" else "old-source.md"
        companion.write_text(companion.read_text().replace(source.relative_to(root).as_posix(), destination))
    elif failure == "companion-symlink":
        destination = tmp_path / "redirected-companion.md"
        companion.rename(destination)
        companion.symlink_to(destination)
    elif failure in {"companion-race", "companion-removed"}:
        reconcile = binding.store.reconcile_legacy_source
        def racing_companion(*args, **kwargs):
            if failure == "companion-race":
                companion.write_text(companion.read_text() + "changed")
            else:
                companion.unlink()
            reconcile(*args, **kwargs)
        monkeypatch.setattr(binding.store, "reconcile_legacy_source", racing_companion)
    before = deepcopy(state.rows)
    source_before = source.read_bytes()
    with pytest.raises(recovery.LegacySourceRefusal, match=f"^{reason}$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == before and not state.calls and not state.vectors and not state.embedded
    assert source.read_bytes() == source_before


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
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=branch == "origin")
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


@pytest.mark.parametrize("origin", ["external", "unknown", "", None, False, [], {"source": "vault"}])
def test_non_vault_origin_allows_only_exact_excluded_retirement(monkeypatch, tmp_path, origin):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    state.rows[0]["payload"]["origin"] = origin
    discovered = state.rows[0]
    before = deepcopy(discovered)
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 1
    assert state.rows == [] and state.vectors == {} and state.embedded == []
    assert len(state.calls) == 1
    assert state.calls[0]["replacement"] is None and state.calls[0]["vector"] is None
    # Retirement must not normalize the discovered payload, even transiently.
    assert discovered == before
    assert source.read_bytes() == raw
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0


@pytest.mark.parametrize("producer", ["alpha", "filesystem", "registry"])
@pytest.mark.parametrize("origin", ["external", "unknown", "", None, False, [], {"source": "vault"}])
def test_non_vault_origin_never_authorizes_reprojection(monkeypatch, tmp_path, producer, origin):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=producer == "alpha")
    if producer == "filesystem":
        monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
        monkeypatch.setenv("VAULT_DIR", str(root))
    elif producer == "registry":
        _enable_registry(monkeypatch, root)
    state.rows[0]["payload"]["origin"] = origin
    before = deepcopy(state.rows)
    with pytest.raises(recovery.LegacySourceRefusal, match="^legacy_origin_refused$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == before and not state.calls and not state.vectors and not state.embedded
    assert source.read_bytes() == raw


@pytest.mark.parametrize("failure,reason", [
    ("body", "legacy_race_refused"), ("source", "legacy_race_refused"),
    ("row", "legacy_write_failed"), ("identity", "legacy_identity_ambiguous_refused"),
    ("policy", "legacy_producer_policy_refused"), ("selection-race", "legacy_producer_policy_refused"),
    ("producer-race", "legacy_producer_policy_refused"),
    ("candidate", "legacy_candidate_refused"), ("profile", "legacy_profile_refused"),
])
def test_origin_retirement_preserves_all_existing_refusals(monkeypatch, tmp_path, failure, reason):
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, tmp_path)
    state.rows[0]["payload"]["origin"] = "external"
    if failure == "body":
        source.write_bytes(raw + b"changed")
    elif failure in ("source", "row"):
        state.fail = failure
    elif failure == "identity":
        (root / "duplicate.md").write_bytes(raw)
    elif failure == "policy":
        monkeypatch.setenv("FS_WATCHER_ENABLE", "ambiguous")
    elif failure == "selection-race":
        from app.ingest import vault_alpha
        select = vault_alpha.select_source_backed_rebuild_candidates
        selections = []

        def racing_inventory(vault_root):
            selections.append(True)
            return [source] if len(selections) > 2 else select(vault_root)

        monkeypatch.setattr(vault_alpha, "select_source_backed_rebuild_candidates", racing_inventory)
    elif failure == "producer-race":
        reconcile = binding.store.reconcile_legacy_source

        def racing_producer(*args, **kwargs):
            monkeypatch.setenv("FS_WATCHER_ENABLE", "1")
            monkeypatch.setenv("VAULT_DIR", str(root))
            reconcile(*args, **kwargs)

        monkeypatch.setattr(binding.store, "reconcile_legacy_source", racing_producer)
    elif failure == "candidate":
        state.rows[0]["payload"]["candidate_only"] = True
    else:
        monkeypatch.setattr(recovery, "assert_profile_note_ingestible", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private-canary")))
    before = deepcopy(state.rows)
    with pytest.raises(recovery.LegacySourceRefusal, match=f"^{reason}$"):
        recovery.reconcile_legacy_sources(binding, index, factory)
    assert state.rows == before and not state.calls and not state.vectors and not state.embedded
    assert source.read_bytes() == raw + (b"changed" if failure in ("body", "source") else b"")


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
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_producer_refused"):
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
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_ambiguous_refused"):
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
        with pytest.raises(recovery.LegacySourceRefusal, match="legacy_identity_producer_refused"):
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
    ("candidate", "legacy_candidate_refused"), ("identity", "legacy_identity_persistence_refused"),
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
