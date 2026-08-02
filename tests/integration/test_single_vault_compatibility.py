"""MVR-02 (#3856): single-vault and no-vault compatibility around the new default.

Contract: docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md

Zero, one, and many bindings all stay valid. Adding an explicit instance default
must not turn an env bootstrap into a hidden default, and must not disturb the
truthful no-vault posture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.default_vault import (
    SELECTION_INSTANCE_DEFAULT,
    SELECTION_LEGACY_BOOTSTRAP,
    SELECTION_NO_VAULT,
    VaultSelectionError,
    resolve_vault_selection,
)
from app.instance.vault_registry import (
    DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING,
    KnownVaultRef,
    RegistryDefaultConflict,
)
from app.vault.markdown_settings import MarkdownSettingsStore
from tests._mvr_default_vault_harness import (
    activate,
    new_runtime,
    reopen_runtime,
)


def _initialize_root(root: Path, *, vault_id: str) -> Path:
    """Write the minimum Design Handoff identity that makes a folder a vault."""

    root.mkdir(parents=True, exist_ok=True)
    settings = root / "settings"
    settings.mkdir(exist_ok=True)
    store = MarkdownSettingsStore()
    store.write_frontmatter(
        settings / "vault.md",
        {"schema": "design-handoff.vault.v1", "vaultId": vault_id, "vaultName": root.name},
    )
    store.write_frontmatter(
        settings / "local.md",
        {
            "schema": "design-handoff.local.v1",
            "localInstanceId": f"local-{vault_id}",
            "machineRole": "primary",
        },
    )
    return root


def test_first_open_existing_materializes_restart_default_once(tmp_path) -> None:
    runtime = new_runtime(tmp_path)
    existing = _initialize_root(tmp_path / "existing-vault", vault_id="vault-existing")

    # A fresh no-vault instance opens its first existing root. The locked
    # transaction proves there were no prior registrations and no prior default,
    # so registration and default land together, exactly once.
    registration = runtime.register_first_vault(
        existing, provenance=DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING
    )
    snapshot = runtime.registry.load()
    assert snapshot.default_vault_binding_id == registration.vault_binding_id
    assert snapshot.default_vault_provenance == DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING
    assert snapshot.revision == 1

    # It survives restart with no reselection gesture at all.
    restarted = reopen_runtime(runtime, tmp_path)
    restored = restarted.registry.load()
    assert restored.default_vault_binding_id == registration.vault_binding_id
    selection = resolve_vault_selection(restored)
    assert selection.vault_binding_id == registration.vault_binding_id
    assert selection.provenance == SELECTION_INSTANCE_DEFAULT

    # A later open never replaces it, and neither does a later last-active write.
    activate(runtime, registration, tmp_path)
    later_root = _initialize_root(tmp_path / "later-vault", vault_id="vault-later")
    later = runtime.production_register(later_root, producer="picker")
    runtime.registry.remember_registration(
        later.vault_binding_id,
        KnownVaultRef(
            ref=later.ref,
            path=later.path,
            vault_id=later.vault_id,
            local_instance_id=later.local_instance_id,
        ),
        make_active=True,
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    after_later_open = runtime.registry.load()
    assert after_later_open.last_active_vault_ref == later.ref
    assert after_later_open.default_vault_binding_id == registration.vault_binding_id
    assert (
        after_later_open.default_vault_provenance
        == DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING
    )

    # And the first-open producer refuses to fire a second time.
    with pytest.raises(RegistryDefaultConflict):
        runtime.register_first_vault(
            later_root, provenance=DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING
        )


def test_first_open_existing_completes_provisional_identity_without_replacing_default(
    tmp_path,
) -> None:
    runtime = new_runtime(tmp_path)
    # An existing but uninitialized root: readable, provisional, no vault identity.
    provisional = tmp_path / "unadopted"
    provisional.mkdir()

    registration = runtime.register_first_vault(
        provisional, provenance=DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING
    )
    assert registration.vault_id is None
    assert registration.extensions["status"] == "uninitialized"
    assert (
        runtime.registry.load().default_vault_binding_id
        == registration.vault_binding_id
    )

    completed = runtime.complete_initialization(
        registration.vault_binding_id,
        vault_id="vault-adopted",
        local_instance_id=registration.local_instance_id,
    )

    snapshot = runtime.registry.load()
    assert completed.vault_binding_id == registration.vault_binding_id
    assert snapshot.registrations[registration.vault_binding_id].vault_id == (
        "vault-adopted"
    )
    # Explicit initialization completes identity; it replaces neither the binding
    # nor the default that first-open recorded.
    assert snapshot.default_vault_binding_id == registration.vault_binding_id
    assert snapshot.default_vault_provenance == DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING


def test_default_adapter_preserves_bootstrap_and_no_vault(tmp_path) -> None:
    runtime = new_runtime(tmp_path)

    # No-vault stays a truthful, valid result rather than an error or a guess.
    empty = runtime.registry.load()
    assert empty.registrations == {}
    assert empty.default_vault_binding_id is None
    assert resolve_vault_selection(empty).is_no_vault
    assert resolve_vault_selection(empty).provenance == SELECTION_NO_VAULT

    # The env bootstrap registers its binding but deliberately does NOT create a
    # default: `VAULT_ROOT` stays an explicit legacy bootstrap, not a hidden one.
    root = _initialize_root(tmp_path / "bootstrap-vault", vault_id="vault-bootstrap")
    registration = runtime.bootstrap_env_binding(
        vault_root=root, watcher_vault_path=root
    )
    bootstrapped = runtime.registry.load()
    assert bootstrapped.default_vault_binding_id is None
    assert bootstrapped.registrations[registration.vault_binding_id].extensions[
        "provenance"
    ] == "legacy_env_bootstrap"

    # The explicit adapter still reaches the same single binding, and says so.
    selection = resolve_vault_selection(bootstrapped, legacy_bootstrap_vault_root=root)
    assert selection.vault_binding_id == registration.vault_binding_id
    assert selection.provenance == SELECTION_LEGACY_BOOTSTRAP

    # The adapter never turns an env path into a new binding and never treats the
    # path itself as identity: an unregistered root fails closed.
    unregistered = _initialize_root(tmp_path / "not-registered", vault_id="vault-other")
    with pytest.raises(VaultSelectionError):
        resolve_vault_selection(
            bootstrapped, legacy_bootstrap_vault_root=unregistered
        )
    assert set(runtime.registry.load().registrations) == {
        registration.vault_binding_id
    }

    # Compatibility DEFAULT_VAULT_ID is an untrusted logical-ID lookup that must
    # resolve to exactly one local binding.
    assert (
        resolve_vault_selection(
            bootstrapped, compatibility_default_vault_id="vault-bootstrap"
        ).vault_binding_id
        == registration.vault_binding_id
    )
    with pytest.raises(VaultSelectionError):
        resolve_vault_selection(
            bootstrapped, compatibility_default_vault_id="vault-other"
        )

    # Restart keeps the bootstrap posture: still no default, still one binding.
    restarted = reopen_runtime(runtime, tmp_path).registry.load()
    assert restarted.default_vault_binding_id is None
    assert set(restarted.registrations) == {registration.vault_binding_id}


# --------------------------------------------------------------------------- #
# MVR-05A0 (#4543): the file_state rekey is invisible to a single-binding vault
# --------------------------------------------------------------------------- #
#
# Epic #2143 makes single-vault and no-vault behaviour the reversible floor, so
# rekeying `file_state` from `path` to `(vault_binding_id, path)` must not
# change a single-binding database's sync decisions. The risk is specific and
# silent: rows written by the pre-#4543 path-keyed code are attributed to the
# legacy compatibility binding by the adoption migration, and the new
# binding-scoped reads must still find them. If they did not, every already
# synced note would look unseen and silently re-sync; if the delete scoping were
# wrong, a note would silently be skipped instead.


@pytest.mark.pg
def test_file_state_rekey_preserves_single_vault_sync(tmp_path, monkeypatch) -> None:
    """A database populated before the rekey keeps skip/resync/delete outcomes."""
    import os
    import uuid as uuid_module
    from datetime import datetime, timezone

    import psycopg

    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    scratch = f"scratch_rekey_compat_{uuid_module.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{scratch}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{scratch}"
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.delenv("DB_DSN", raising=False)
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "app" / "alembic"))

        # 1. A deployed pre-#4543 database: lineage at the pre-adoption head and
        #    a bootstrap-created, path-keyed `file_state`.
        command.upgrade(cfg, "a9f3c2d7b6e1")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.file_state (
                  path text PRIMARY KEY,
                  uuid text,
                  fm_hash text,
                  body_hash text,
                  mtime timestamptz,
                  last_seen timestamptz DEFAULT now()
                )
                """
            )
            conn.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS uuid uuid")
            conn.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS path text")

        from app.services import vault_sync

        note_uuid = str(uuid_module.UUID(int=515))
        note = tmp_path / "already-synced.md"
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Already synced\n---\n\noriginal body\n",
            encoding="utf-8",
        )
        # Past mtime: `active_edit` would otherwise defer the sync.
        past = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        os.utime(note, (past, past))
        frontmatter, body = vault_sync._read_note(note)
        resolved = str(note.resolve())

        # 2. Seed the fully-materialized state the old code would have left.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO public.file_state (path, uuid, fm_hash, body_hash, mtime, last_seen) "
                "VALUES (%s, %s, %s, %s, to_timestamp(%s), now())",
                (
                    resolved,
                    note_uuid,
                    vault_sync._hash_dict(frontmatter),
                    vault_sync._hash_text(body),
                    past,
                ),
            )
            conn.execute(
                "INSERT INTO public.objects (id, uuid, kind, payload, path) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                (note_uuid, note_uuid, resolved),
            )
            conn.execute(
                "INSERT INTO store_objects (object_id, kind, source_ref, payload) "
                "VALUES (%s, 'note', %s, '{}'::jsonb)",
                (note_uuid, resolved),
            )

        # 3. Adopt and rekey.
        command.upgrade(cfg, "head")

        from app.db import db as db_module
        from app.stores import pg as pg_store

        monkeypatch.setattr(db_module, "_SCHEMA_INITIALIZED", False)
        monkeypatch.setattr(pg_store, "_TABLES_READY", False)

        def _outbox_topics() -> list[str]:
            with psycopg.connect(dsn) as conn:
                return [
                    row[0]
                    for row in conn.execute(
                        "SELECT topic FROM public.outbox ORDER BY created_at, id"
                    ).fetchall()
                ]

        def _file_state_rows() -> list[tuple]:
            with psycopg.connect(dsn) as conn:
                return [
                    tuple(row)
                    for row in conn.execute(
                        "SELECT vault_binding_id, path, body_hash FROM public.file_state "
                        "ORDER BY path"
                    ).fetchall()
                ]

        assert _outbox_topics() == []

        # SKIP: the pre-rekey row is still this binding's row, so an unchanged
        # note emits nothing. An invisible legacy row would re-sync here.
        unchanged = vault_sync.sync_markdown(resolved)
        assert unchanged["status"] == "ok"
        assert unchanged["reembedded"] is False
        assert _outbox_topics() == [], (
            "an already-synced note re-emitted after the rekey: the "
            "binding-scoped read did not find its pre-existing row"
        )
        assert len(_file_state_rows()) == 1, "the rekey duplicated a single-vault row"

        # RESYNC: a real body change still produces exactly one update event.
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Already synced\n---\n\nedited body\n",
            encoding="utf-8",
        )
        os.utime(note, (past + 60, past + 60))
        changed = vault_sync.sync_markdown(resolved)
        assert changed["reembedded"] is True
        assert _outbox_topics() == ["ingest.object.updated"]
        assert len(_file_state_rows()) == 1

        # DELETE: the tombstone still fires and the row is gone.
        assert vault_sync.delete_note(resolved, uuid_value=note_uuid) is True
        assert _outbox_topics() == ["ingest.object.updated", "ingest.object.deleted"]
        assert _file_state_rows() == []
    finally:
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        except Exception:
            pass
