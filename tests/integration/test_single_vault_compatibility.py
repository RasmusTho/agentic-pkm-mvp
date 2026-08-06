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


# --------------------------------------------------------------------------- #
# MVR-05A1 (#4560): retiring the runtime DDL path keeps single-vault behaviour
# --------------------------------------------------------------------------- #
#
# Epic #2143 makes single-vault and no-vault behaviour the reversible floor. Two
# things could break it here. First, `ensure_schema` no longer issues any DDL,
# so a database that was previously shaped at process boot must still be a
# working database when only `alembic upgrade head` has run. Second, `objects`
# moved from `PRIMARY KEY (id)` with a global `objects_uuid_idx` to
# `(vault_binding_id, id)` with `UNIQUE (vault_binding_id, uuid)`; with one
# binding value in every row those have identical semantics, and the vault-sync
# producer's create/update/delete outcomes must be unchanged.


def _mvr05a1_scratch_database(monkeypatch):
    """Create a scratch database at `alembic upgrade head`; yield its DSN."""
    import uuid as uuid_module

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

    name = f"scratch_mvr05a1_{uuid_module.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    return admin_dsn, name, dsn


def _drop_scratch_database(admin_dsn: str, name: str) -> None:
    import psycopg

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


@pytest.mark.pg
def test_fresh_database_boots_without_runtime_ddl(tmp_path, monkeypatch) -> None:
    """A fresh database serves after the bootstrap path stops issuing DDL.

    `scripts/run_migrations.sh` (`alembic upgrade head`) is the single migration
    authority and every runtime container gates on it, so this reproduces the
    real first-boot sequence: migrate, then boot a process with no
    `STORE_SCHEMA_AUTOCREATE` opt-in, then serve a real vault-sync write. Before
    #4560 the boot itself supplied schema; if anything still depended on that,
    this is where it surfaces.
    """
    import os
    import subprocess
    import sys
    import uuid as uuid_module
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    import psycopg
    from alembic import command
    from alembic.config import Config

    repo_root = _Path(__file__).resolve().parents[2]
    admin_dsn, name, dsn = _mvr05a1_scratch_database(monkeypatch)
    try:
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "app" / "alembic"))
        command.upgrade(cfg, "head")

        # Boot a genuinely new interpreter in production posture: no fixture
        # autocreate opt-in, nothing but the migrated schema underneath it.
        env = dict(os.environ)
        env["DATABASE_URL"] = dsn
        env.pop("DB_DSN", None)
        env.pop("STORE_SCHEMA_AUTOCREATE", None)
        env["PYTHONPATH"] = str(repo_root)
        booted = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.db.db import assert_file_state_schema, conn_rw\n"
                "conn = conn_rw()\n"
                "assert_file_state_schema(conn)\n"
                "conn.close()\n"
                "print('booted')\n",
            ],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert booted.returncode == 0, f"{booted.stdout}\n{booted.stderr}"
        assert "booted" in booted.stdout

        # And it serves: a real vault-sync write lands in every table the
        # retired bootstrap used to create.
        from app.db import db as db_module
        from app.services import vault_sync
        from app.stores import pg as pg_store

        monkeypatch.setattr(db_module, "_SCHEMA_INITIALIZED", False)
        monkeypatch.setattr(pg_store, "_TABLES_READY", False)

        note_uuid = str(uuid_module.UUID(int=4560))
        note = tmp_path / "fresh.md"
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Fresh\n---\n\nfresh body\n", encoding="utf-8"
        )
        # Past mtime: `active_edit` would otherwise defer the sync.
        past = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        os.utime(note, (past, past))
        result = vault_sync.sync_markdown(str(note.resolve()))
        assert result["status"] == "ok"

        with psycopg.connect(dsn) as conn:
            assert conn.execute(
                "SELECT count(*) FROM public.objects WHERE uuid = %s", (note_uuid,)
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM public.file_state WHERE uuid = %s", (note_uuid,)
            ).fetchone() == (1,)
            # `agent_memories` was bootstrap-only before #4560; a fresh database
            # that never ran the bootstrap must still have it.
            assert conn.execute("SELECT to_regclass('public.agent_memories')").fetchone() != (
                None,
            )
    finally:
        _drop_scratch_database(admin_dsn, name)


@pytest.mark.pg
def test_objects_rekey_preserves_single_vault_behaviour(tmp_path, monkeypatch) -> None:
    """A single-binding database behaves identically across the `objects` rekey.

    Starts from the *bootstrap-shaped* table a deployed instance actually holds
    — lineage at the pre-adoption head with the historical bootstrap DDL applied
    — and drives the same create / no-op resync / edit / delete sequence the
    watcher does, asserting the continuity mirror and the emitted events are
    unchanged by `(id)` becoming `(vault_binding_id, id)`.
    """
    import os
    import uuid as uuid_module
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    import psycopg
    from alembic import command
    from alembic.config import Config

    repo_root = _Path(__file__).resolve().parents[2]
    admin_dsn, name, dsn = _mvr05a1_scratch_database(monkeypatch)
    try:
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "app" / "alembic"))

        # A deployed pre-#4560 database: lineage at the pre-adoption head, with
        # the runtime bootstrap's `objects` shape on top of it.
        command.upgrade(cfg, "c7f4b1a83d29")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE public.objects ADD COLUMN IF NOT EXISTS source_ref text")
            conn.execute("ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey")
            conn.execute(
                "ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id)"
            )
            conn.execute("DROP INDEX IF EXISTS public.objects_uuid_idx")
            conn.execute("CREATE UNIQUE INDEX objects_uuid_idx ON public.objects(uuid)")

        from app.services import vault_sync

        note_uuid = str(uuid_module.UUID(int=4561))
        note = tmp_path / "single-vault.md"
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Single vault\n---\n\noriginal body\n",
            encoding="utf-8",
        )
        past = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        os.utime(note, (past, past))
        frontmatter, body = vault_sync._read_note(note)
        resolved = str(note.resolve())

        # Seed the fully-materialized state the pre-rekey code would have left.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO public.file_state "
                "(vault_binding_id, path, uuid, fm_hash, body_hash, mtime, last_seen) "
                "VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), now())",
                (
                    "legacy-compatibility-binding",
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

        # Adopt and rekey.
        command.upgrade(cfg, "head")

        with psycopg.connect(dsn) as conn:
            assert conn.execute(
                "SELECT vault_binding_id FROM public.objects WHERE uuid = %s", (note_uuid,)
            ).fetchall() == [("legacy-compatibility-binding",)]

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

        def _objects_rows() -> list[tuple]:
            with psycopg.connect(dsn) as conn:
                return [
                    tuple(row)
                    for row in conn.execute(
                        "SELECT vault_binding_id, id::text, path FROM public.objects "
                        "ORDER BY id"
                    ).fetchall()
                ]

        assert _outbox_topics() == []

        # SKIP: an unchanged note emits nothing and does not duplicate the row.
        unchanged = vault_sync.sync_markdown(resolved)
        assert unchanged["status"] == "ok"
        assert unchanged["reembedded"] is False
        assert _outbox_topics() == []
        assert _objects_rows() == [("legacy-compatibility-binding", note_uuid, resolved)], (
            "the objects rekey duplicated or lost a single-vault continuity row"
        )

        # RESYNC: a real body change still produces exactly one update event.
        note.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Single vault\n---\n\nedited body\n",
            encoding="utf-8",
        )
        os.utime(note, (past + 60, past + 60))
        changed = vault_sync.sync_markdown(resolved)
        assert changed["reembedded"] is True
        assert _outbox_topics() == ["ingest.object.updated"]
        assert len(_objects_rows()) == 1

        # DELETE: the tombstone still fires and the mirror path is cleared.
        assert vault_sync.delete_note(resolved, uuid_value=note_uuid) is True
        assert _outbox_topics() == ["ingest.object.updated", "ingest.object.deleted"]
        assert _objects_rows() == [("legacy-compatibility-binding", note_uuid, None)]
    finally:
        _drop_scratch_database(admin_dsn, name)
