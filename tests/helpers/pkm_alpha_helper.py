# Reasoning entrypoint: app/agents/pipeline.py:ingest_and_chunk() → _run_reasoning_if_enabled()
# Reviewer entrypoint: app/agents/reviewer/agent.py:run(...) (graph wrapper in app/agents/reviewer/graph.py:invoke)
# pkm-alpha path: app/ingest/config.DEFAULT_VAULT_ROOT (local repo mirror under vault/)
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Dict
from uuid import UUID

import app.store.object_store as legacy_store
from app.ingest.vault_root import _ingest_file
from app.obs.log import with_trace_id
from app.stores import get_object_store, reset_store_backends

PKM_ALPHA_ROOT = Path(os.getenv("PKM_ALPHA_ROOT", "vault"))

NOTE_PATHS: Dict[str, Path] = {
    "research": Path("@Inbox/Desicion science for data scientists 2.md"),
    "concept": Path("settings/Overview.md"),
    "project": Path("@Desk/galaxy-test.md"),
}

# Stable ids to keep tests deterministic even though the normalizer generates UUID4 values.
DETERMINISTIC_UUIDS: Dict[str, str] = {
    "research": "457c42f8-3fbf-5c67-bcdf-356e8bbc0b01",
    "concept": "a819878a-e2e4-537c-8b07-0f7609dadeef",
    "project": "ebf45c3c-2c5e-50b2-8718-2f92eec8dfd4",
}

_NOTE_ORDER = ("research", "concept", "project")


@contextmanager
def _patched_normalizer_uuids(sequence: list[UUID]):
    """
    Temporarily override the normalizer's uuid4 generator so we can assign
    deterministic object ids for the selected pkm-alpha notes.
    """
    import app.agents.normalizer.agent as normalizer_agent

    original_uuid4 = normalizer_agent._uuid.uuid4
    seq_iter = iter(sequence)

    def _fake_uuid4():
        try:
            return next(seq_iter)
        except StopIteration:
            return original_uuid4()

    normalizer_agent._uuid.uuid4 = _fake_uuid4
    try:
        yield
    finally:
        normalizer_agent._uuid.uuid4 = original_uuid4


def reset_memory_stores() -> None:
    """
    Clear cached store backends and the legacy ObjectStore shim so each test
    run starts with a fresh in-memory state.
    """
    reset_store_backends()
    try:
        legacy_store._MEMORY_STORE.clear()
    except Exception:
        pass


def load_pkm_alpha_subset_for_reasoning(object_store=None) -> dict[str, str]:
    """
    Ingest a small, stable subset of the pkm-alpha vault into the memory
    ObjectStore. Returns a mapping of semantic labels to deterministic ids.
    """
    os.environ.setdefault("STORE_BACKEND", "memory")

    # Ensure the caller's store is materialized for downstream lookups.
    if object_store is None:
        reset_memory_stores()
        store = get_object_store()
    else:
        store = object_store
    _ = store  # keep lints happy while relying on get_object_store() inside _ingest_file

    uuid_sequence = [UUID(DETERMINISTIC_UUIDS[key]) for key in _NOTE_ORDER]
    with _patched_normalizer_uuids(uuid_sequence):
        ids: dict[str, str] = {}
        for key in _NOTE_ORDER:
            rel_path = NOTE_PATHS[key]
            path = (PKM_ALPHA_ROOT / rel_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"pkm-alpha note missing: {path}")
            obj_id = _ingest_file(path, trace_id=with_trace_id(None))
            target_id = DETERMINISTIC_UUIDS[key]
            if obj_id != target_id:
                try:
                    stored = get_object_store().get(UUID(obj_id))
                except Exception:
                    stored = None
                if stored:
                    get_object_store().put(
                        UUID(target_id),
                        kind=stored.get("kind", "note"),
                        source_ref=stored.get("source_ref") or str(path),
                        payload=stored.get("payload") or {},
                    )
                legacy_obj = legacy_store._MEMORY_STORE.get(obj_id)
                if legacy_obj:
                    legacy_store._MEMORY_STORE[target_id] = legacy_store.DomainObject(
                        uuid=target_id,
                        kind=legacy_obj.kind,
                        payload=legacy_obj.payload,
                        source_ref=legacy_obj.source_ref,
                        created_at=legacy_obj.created_at,
                    )
                ids[key] = target_id
            else:
                ids[key] = obj_id
    return ids


__all__ = ["load_pkm_alpha_subset_for_reasoning", "reset_memory_stores"]
