"""MVR-06B (#3864): the reactivation invalidation inventory against the migrated schema."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app.instance.binding_removal import (
    PG_BINDING_KEYED_DERIVED_TABLES,
    PG_BINDING_KEYED_RETAINED_TABLES,
    _invalidate_pg_tables,
)
from app.stores.pg import put_object_with_connection
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)

pytestmark = pytest.mark.pg


def test_invalidation_inventory_matches_migrated_binding_keyed_schema(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dsn = request.getfixturevalue("scratch_db_factory")()
    _upgrade(dsn, monkeypatch, "head")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    with psycopg.connect(dsn) as conn:
        keyed = {
            row[0]
            for row in conn.execute(
                "select table_name from information_schema.columns "
                "where table_schema = 'public' and column_name = 'vault_binding_id'"
            )
        }
        # Every inventoried derived table really is binding-keyed, so the DELETE scopes.
        assert set(PG_BINDING_KEYED_DERIVED_TABLES) <= keyed, (
            set(PG_BINDING_KEYED_DERIVED_TABLES) - keyed
        )
        # Every restricting FK between derived tables deletes the child first.
        order = {name: index for index, name in enumerate(PG_BINDING_KEYED_DERIVED_TABLES)}
        for child, parent in conn.execute(
            "select c.conrelid::regclass::text, c.confrelid::regclass::text from pg_constraint c "
            "where c.contype = 'f' and c.confdeltype in ('a', 'r')"
        ):
            child, parent = child.split(".")[-1], parent.split(".")[-1]
            if child in order and parent in order and child != parent:
                assert order[child] < order[parent], (child, parent)
        doomed, kept = uuid.uuid4(), uuid.uuid4()
        put_object_with_connection(
            conn, object_id=doomed, kind="note", source_ref="a", payload={}, vault_binding_id="binding-x"
        )
        put_object_with_connection(
            conn, object_id=kept, kind="note", source_ref="b", payload={}, vault_binding_id="binding-y"
        )
        conn.commit()

    receipt = _invalidate_pg_tables("binding-x", tmp_path)

    # All inventoried tables exist at head and were scoped to the one binding.
    assert set(receipt["tables"]) == set(PG_BINDING_KEYED_DERIVED_TABLES)
    assert not set(receipt["tables"]) & set(PG_BINDING_KEYED_RETAINED_TABLES)
    with psycopg.connect(dsn) as conn:
        rows = {
            row[0]
            for row in conn.execute("select vault_binding_id from store_objects")
        }
    assert rows == {"binding-y"}


@pytest.mark.usefixtures("product_model_access_gateway")
def test_reactivation_rebuilds_derived_rows_through_real_dispatch_before_healthy(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.stores import _pg_instances
    from tests._mvr06b_handoff_harness import mvr06b_instance, stub_settings_reload

    dsn = request.getfixturevalue("scratch_db_factory")()
    _upgrade(dsn, monkeypatch, "head")
    monkeypatch.setenv("DATABASE_URL", dsn)
    _pg_instances.cache_clear()
    runtime, first, (second,) = mvr06b_instance(tmp_path, monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    stub_settings_reload(monkeypatch)
    binding, root = second.vault_binding_id, Path(second.path)
    (root / "rebuilt-note.md").write_text("# Rebuilt\n\nderived source\n", encoding="utf-8")
    runtime.remove(binding)
    with psycopg.connect(dsn) as conn:
        put_object_with_connection(
            conn, object_id=uuid.uuid4(), kind="note", source_ref="stale", payload={},
            vault_binding_id=binding,
        )
        conn.commit()

    healthy = runtime.reactivate_removed(root)

    assert "lifecycleState" not in healthy.extensions
    with psycopg.connect(dsn) as conn:
        undelivered = conn.execute(
            "select count(*) from outbox where vault_binding_id = %s and delivered_at is null",
            (binding,),
        ).fetchone()[0]
        delivered = conn.execute(
            "select count(*) from outbox where vault_binding_id = %s and delivered_at is not null "
            "and topic = 'ingest.vault.changed'",
            (binding,),
        ).fetchone()[0]
        sources = {
            row[0]
            for row in conn.execute(
                "select source_ref from store_objects where vault_binding_id = %s", (binding,)
            )
        }
    assert undelivered == 0
    assert delivered >= 1
    assert "stale" not in sources  # the retired epoch's row was invalidated


@pytest.mark.usefixtures("product_model_access_gateway")
def test_watcher_db_rows_carry_the_durable_binding_after_rebind_and_after_removal(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.stores import _pg_instances
    from app.watcher import registry as watcher_registry
    from tests._mvr06b_handoff_harness import (
        bind_runtime_env,
        configure_watcher,
        drive_watcher_during_waits,
        handoff_through_cli,
        mvr06a_instance,
        pick,
        stub_settings_reload,
    )

    dsn = request.getfixturevalue("scratch_db_factory")()
    _upgrade(dsn, monkeypatch, "head")
    monkeypatch.setenv("DATABASE_URL", dsn)
    _pg_instances.cache_clear()
    runtime, first, (second,) = mvr06a_instance(tmp_path)
    bind_runtime_env(monkeypatch, runtime, watcher=True)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    config = configure_watcher(monkeypatch, tmp_path, runtime, Path(first.path))
    stub_settings_reload(monkeypatch)
    watcher_registry.run_registry_once(config)
    assert handoff_through_cli(runtime)["_exit_code"] == 0
    drive_watcher_during_waits(monkeypatch, config)
    pick(runtime, second.vault_binding_id)  # the boot env root stays the first binding
    note = Path(second.path) / "row-under-second.md"
    note.write_text("after rebind\n", encoding="utf-8")
    watcher_registry.run_registry_once(config)

    def row_binding(name: str) -> set[str]:
        with psycopg.connect(dsn) as conn:
            return {
                row[0]
                for row in conn.execute(
                    "select vault_binding_id from outbox where topic = 'ingest.vault.changed' "
                    "and payload::text like %s",
                    (f"%{name}%",),
                )
            }

    assert row_binding(note.name) == {second.vault_binding_id}

    # A write racing the removal's post-commit drain is stamped under the removed binding.
    from app.instance.runtime import open_default_vault_service
    from app.instance.settings_rebind import SettingsRebindActivation

    open_default_vault_service(runtime.layout.registry_path).set(second.vault_binding_id)
    direct = Path(second.path) / "racing-the-removal.md"
    original = SettingsRebindActivation._wait_for_stage

    def wait(activation, record, *, required_stage):
        original(activation, record, required_stage=required_stage)
        if required_stage == "acknowledged":
            direct.write_text("racing\n", encoding="utf-8")

    monkeypatch.setattr(SettingsRebindActivation, "_wait_for_stage", wait)
    runtime.remove(second.vault_binding_id, replacement_default_binding_id=first.vault_binding_id)
    assert row_binding(direct.name) == {second.vault_binding_id}
