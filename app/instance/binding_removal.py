"""MVR-06B production registration removal and tombstone reactivation engines.

Reached only through :meth:`app.instance.runtime.InstanceRegistryRuntime.remove` /
``reactivate_removed`` (and their ``recover_*`` restart paths). Both are sealed with
``capability_not_ready`` until the MVR-05 foreground and the MVR-06B background consumer
floors are proven (`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md`, MVR-06B
production protocol proof, and `ESTABLISH_INSTANCE_VAULT_REGISTRY.md`).

**Removal** is one recoverable journal (``binding-removal.json``)::

    intent -> reserved -> prepared -> drained -> final_scanned -> committed
           -> buffer_drained -> ownership_released -> resumed -> complete

``reserved`` commits the durable ``draining_removal`` reservation: every new
foreground/background shared effect is refused while old-root access stays with the
removal reconciler (the watcher's journal-bound old-root scans). ``prepared`` opens the
shared ``settings_rebind.v1`` phase journal toward the post-removal background binding
(the authorized replacement default, or truthful idle/no-vault), ``drained`` waits out
every holder through the exclusive binding-effect lease, and ``final_scanned`` records
the watcher's quiescent old-root scan/buffer acknowledgement. ``committed`` is the one
registry generation that replaces the registration with its immutable removal
tombstone and commits the MVR-02 default, the compatibility intent revision, and the
phase journal together. ``buffer_drained`` is the post-commit old-root scan/buffer
drain receipted under the removed binding; only then is ownership released to the
ledger tombstone and the replacement resumed.

A typed refusal before ``committed`` (watcher timeout, revision race, policy) is
compensated: the reservation and prepared revision are withdrawn and the source
registration/default/compatibility lifecycle stays authoritative. A process crash
instead leaves the durable journal; :meth:`BindingRemovalCoordinator.recover` resumes
from its phase without reopening ordinary access, and never releases ownership before
drain + commit.

**Reactivation** (``binding-reactivation.json``)::

    intent -> ownership_reactivated -> registered_reactivating -> derived_invalidated
           -> rescanned -> rebuild_receipted -> complete

The binding is restored from its tombstone in the sealed ``reactivating`` state with an
advanced content epoch; every binding-keyed derived projection family in
:data:`DERIVED_PROJECTION_FAMILIES` is invalidated, a production full rescan manifest is
taken, and a durable rebuild receipt is written before the reservation clears. Failure
leaves the binding ``reactivating`` (sealed, degraded). Historical receipts keep the
retired epoch through the registry ``bindingLineage`` record.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.instance._storage_boundary import (
    _STORAGE_MUTATION_CAPABILITY,
    CapabilityNotReadyError,
    RegistryError,
)
from app.instance.background_intent import (
    BACKGROUND_INTENT_KEY,
    INTENT_MODE_COMPATIBILITY,
    PROVENANCE_COMPATIBILITY_DEFAULT,
    PROVENANCE_COMPATIBILITY_HANDOFF,
)
from app.instance.background_supervisor import (
    LIFECYCLE_DRAINING_REMOVAL,
    LIFECYCLE_REACTIVATING,
    LIFECYCLE_STATE_KEY,
    durable_background_state,
    emit_background_intent_event,
    stored_intent,
)
from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.vault_registry import (
    DEFAULT_PROVENANCE_EXPLICIT,
    RegistrySnapshot,
    RemovalTombstone,
    VaultRegistration,
)

if TYPE_CHECKING:
    from app.instance.runtime import InstanceRegistryRuntime

REMOVAL_SCHEMA = "agentic-pkm.binding-removal.v1"
REMOVAL_PHASES = (
    "intent",
    "reserved",
    "prepared",
    "drained",
    "final_scanned",
    "committed",
    "buffer_drained",
    "ownership_released",
    "resumed",
    "complete",
)
REACTIVATION_SCHEMA = "agentic-pkm.binding-reactivation.v1"
REACTIVATION_PHASES = (
    "intent",
    "ownership_reactivated",
    "registered_reactivating",
    "derived_invalidated",
    "rescanned",
    "rebuild_receipted",
    "complete",
)
REBUILD_RECEIPT_SCHEMA = "agentic-pkm.binding-rebuild-receipt.v1"
BINDING_LINEAGE_KEY = "bindingLineage"
_FLOOR_REFUSAL = "MVR-06B consumer drain floor is required"


def _fault_point(phase: str) -> None:
    """Process-failure injection seam, deliberately after each durable phase."""

    del phase


def _require_consumer_floors(snapshot: RegistrySnapshot) -> None:
    """Both the MVR-05 foreground and MVR-06B background consumer floors."""

    if durable_background_state(snapshot) is None:
        raise CapabilityNotReadyError(_FLOOR_REFUSAL)


def _content_epoch(registration: VaultRegistration) -> int:
    value = registration.extensions.get("contentEpoch", 1)
    return value if isinstance(value, int) and value >= 1 else 1


def _lineage(snapshot: RegistrySnapshot) -> list[dict[str, Any]]:
    raw = snapshot.extensions.get(BINDING_LINEAGE_KEY) or []
    if not isinstance(raw, list):
        raise RegistryError("binding lineage is invalid")
    return [dict(item) for item in raw]


def binding_epoch_lineage(snapshot: RegistrySnapshot, binding_id: str) -> list[dict[str, Any]]:
    """The binding's retired/successor content epochs, for historical receipt audit."""

    return [item for item in _lineage(snapshot) if item.get("bindingId") == binding_id]


class _Journal:
    def __init__(self, path: Path, schema: str, phases: tuple[str, ...]) -> None:
        self.path = path
        self.schema = schema
        self.phases = phases

    @contextmanager
    def locked(self) -> Iterator[None]:
        lock = self.path.with_suffix(".lock")
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def save(self, intent: dict[str, Any], phase: str) -> None:
        from app.instance.instance_state import _atomic_private_write

        intent["phase"] = phase
        _atomic_private_write(self.path, json.dumps(intent, sort_keys=True).encode())
        _fault_point(f"{self.schema.rsplit('.', 2)[-2]}:{phase}")

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        from app.instance.instance_state import _read_private_json

        intent = _read_private_json(self.path)
        if intent.get("schema") != self.schema or intent.get("phase") not in self.phases:
            raise RegistryError("lifecycle journal is invalid")
        return intent

    def discard(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def before(self, intent: dict[str, Any], phase: str) -> bool:
        return self.phases.index(intent["phase"]) < self.phases.index(phase)


def _activation(runtime: InstanceRegistryRuntime) -> Any:
    from app.instance.settings_rebind import SettingsRebindActivation

    return SettingsRebindActivation.from_environment(runtime.registry)


class BindingRemovalCoordinator:
    """The production removal engine (crash-recoverable, compensating on refusal)."""

    def __init__(self, runtime: InstanceRegistryRuntime) -> None:
        self.runtime = runtime
        self.journal = _Journal(
            runtime.layout.root / "binding-removal.json", REMOVAL_SCHEMA, REMOVAL_PHASES
        )

    # -- entrypoints --------------------------------------------------------------------

    def remove(
        self, binding_id: str, *, replacement_default_binding_id: str | None = None
    ) -> RemovalTombstone:
        snapshot = self.runtime.registry.load()
        _require_consumer_floors(snapshot)
        with self.journal.locked():
            existing = self.journal.load()
            if existing is not None and existing["phase"] != "complete":
                if existing["binding_id"] != binding_id:
                    raise RegistryError("another binding removal requires recovery first")
                return self._resume(existing)
            intent = self._plan(snapshot, binding_id, replacement_default_binding_id)
            self.journal.save(intent, "intent")
            return self._resume(intent)

    def recover(self) -> RemovalTombstone | None:
        with self.journal.locked():
            intent = self.journal.load()
            if intent is None or intent["phase"] == "complete":
                return None
            return self._resume(intent)

    # -- planning -----------------------------------------------------------------------

    def _plan(
        self,
        snapshot: RegistrySnapshot,
        binding_id: str,
        replacement: str | None,
    ) -> dict[str, Any]:
        registration = snapshot.registrations.get(binding_id)
        if registration is None:
            raise RegistryError(f"unknown vault_binding_id: {binding_id}")
        if registration.extensions.get(LIFECYCLE_STATE_KEY) is not None:
            raise RegistryError("binding already has a lifecycle reservation")
        removes_default = snapshot.default_vault_binding_id == binding_id
        if replacement is not None:
            if not removes_default:
                raise RegistryError(
                    "a replacement default is only valid when removing the current default"
                )
            if replacement == binding_id or replacement not in snapshot.registrations:
                raise RegistryError("replacement default must be another current registration")
        post_default = (
            replacement if removes_default else snapshot.default_vault_binding_id
        )
        intent = stored_intent(snapshot)
        assert intent is not None
        background_bound = binding_id in intent.effective_binding_ids()
        if intent.mode == INTENT_MODE_COMPATIBILITY:
            # The post-removal MVR-02 default becomes the compatibility binding; with
            # no replacement the enabled watcher persists idle/no-vault.
            candidate = post_default if background_bound else None
        else:
            # Explicit mode keeps the removed member as loudly failed intent.
            candidate = None
        return {
            "schema": REMOVAL_SCHEMA,
            "removal_id": f"removal-{uuid4()}",
            "binding_id": binding_id,
            "channel_id": self.runtime.layout.channel_id,
            "source": asdict(registration),
            "removes_default": removes_default,
            "post_default": post_default,
            "background_bound": background_bound,
            "candidate_binding_id": candidate,
            "intent_mode": intent.mode,
        }

    # -- resume -------------------------------------------------------------------------

    def _resume(self, intent: dict[str, Any]) -> RemovalTombstone:
        from app.instance.binding_effect_lease import BindingEffectLeaseError

        try:
            return self._run(intent)
        except (RegistryError, BindingEffectLeaseError):
            # A typed refusal (watcher timeout, revision race, drain timeout) before
            # the commit leaves the source authoritative. Any other exception is a
            # process failure: the durable journal is the recovery authority.
            if self.journal.before(intent, "committed"):
                self._compensate(intent)
            raise

    def _run(self, intent: dict[str, Any]) -> RemovalTombstone:
        runtime = self.runtime
        binding_id: str = intent["binding_id"]
        source = VaultRegistration(**intent["source"])
        before = self.journal.before
        activation = _activation(runtime) if intent["background_bound"] else None
        if before(intent, "reserved"):
            self._reserve(intent, source)
            self.journal.save(intent, "reserved")
        if before(intent, "prepared"):
            if activation is not None:
                from app.instance.settings_rebind import compatibility_ingress_window

                intent["journal_before"] = activation.store.read().as_payload()
                with compatibility_ingress_window(runtime.registry, transition=True):
                    prepared = activation.store.prepare(
                        candidate_binding_id=intent["candidate_binding_id"]
                    )
                intent["journal_revision"] = prepared.desired_revision
                intent["journal_moves"] = prepared.phase == "prepared"
            self.journal.save(intent, "prepared")
        if before(intent, "drained"):
            self._drain(source)
            self.journal.save(intent, "drained")
        if before(intent, "final_scanned"):
            intent["final_scan"] = self._final_scan(intent, activation)
            self.journal.save(intent, "final_scanned")
        if before(intent, "committed"):
            self._commit(intent, source)
            self.journal.save(intent, "committed")
        if before(intent, "buffer_drained"):
            if activation is not None and intent.get("journal_moves"):
                record = activation.store.read()
                if activation.watcher_enabled:
                    activation._wait_for_stage(record, required_stage="completed")
            self.journal.save(intent, "buffer_drained")
        if before(intent, "ownership_released"):
            lease = runtime.ledger.load().leases.get(binding_id)
            if lease is not None:
                runtime.ledger.release_to_tombstone(
                    binding_id, _capability=_STORAGE_MUTATION_CAPABILITY
                )
            self.journal.save(intent, "ownership_released")
        if before(intent, "resumed"):
            if activation is not None and intent.get("journal_moves"):
                candidate = intent["candidate_binding_id"]
                root = (
                    Path(runtime.registry.load().registrations[candidate].path)
                    if candidate
                    else None
                )
                activation._reload_if_needed(activation.store.read(), root)
            self.journal.save(intent, "resumed")
        if before(intent, "complete"):
            emit_background_intent_event(runtime.registry.load(), reason="binding_removal")
            self.journal.save(intent, "complete")
        tombstone = runtime.registry.load().removal_tombstones.get(binding_id)
        if tombstone is None:
            raise RegistryError("binding removal completed without its tombstone")
        return tombstone

    def _reserve(self, intent: dict[str, Any], source: VaultRegistration) -> None:
        registry = self.runtime.registry
        snapshot = registry.load()
        current = snapshot.registrations.get(source.vault_binding_id)
        if current is None or current.extensions.get(LIFECYCLE_STATE_KEY) not in {
            None,
            LIFECYCLE_DRAINING_REMOVAL,
        }:
            raise RegistryError("the removed registration changed before its reservation")
        if current.extensions.get("removalId") == intent["removal_id"]:
            return
        if {k: v for k, v in current.extensions.items()} != source.extensions:
            raise RegistryError("the removed registration changed before its reservation")
        reserved = replace(
            current,
            extensions={
                **current.extensions,
                LIFECYCLE_STATE_KEY: LIFECYCLE_DRAINING_REMOVAL,
                "removalId": intent["removal_id"],
            },
        )
        registry.commit_state(
            registrations={**snapshot.registrations, source.vault_binding_id: reserved},
            expected_revision=snapshot.revision,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

    def _drain(self, source: VaultRegistration) -> None:
        from app.instance.binding_effect_lease import BindingEffectLeaseManager

        runtime = self.runtime
        if runtime.ledger.active_owner(source.vault_binding_id) is None:
            return
        leases = BindingEffectLeaseManager.for_runtime(
            registry_store=runtime.registry,
            ownership_root=runtime.ledger.root,
            state_root=runtime.layout.root / "binding-effect-leases",
        )
        with leases.exclusive_change(
            source.vault_binding_id,
            channel_id=runtime.layout.channel_id,
            root=Path(source.path),
            timeout=float(os.getenv("BINDING_REMOVAL_DRAIN_TIMEOUT_SECONDS", "30")),
        ):
            pass

    def _final_scan(self, intent: dict[str, Any], activation: Any) -> dict[str, Any]:
        """The watcher's quiescent old-root scan + buffer acknowledgement (or none)."""

        from app.instance.settings_rebind import compatibility_ingress_window

        if activation is None or not intent.get("journal_moves"):
            return {"scan": "not_background_bound"}
        record = activation.store.read()
        if activation.watcher_enabled:
            activation._wait_for_stage(record, required_stage="acknowledged")
            return {"scan": "watcher_pre_commit", "revision": record.desired_revision}
        if record.phase == "prepared":
            with compatibility_ingress_window(self.runtime.registry, transition=True):
                activation.store.acknowledge_no_lifecycle(
                    desired_revision=record.desired_revision
                )
        return {"scan": "no_lifecycle", "revision": record.desired_revision}

    def _commit(self, intent: dict[str, Any], source: VaultRegistration) -> None:
        from app.instance.settings_rebind import (
            SettingsRebindRecord,
            compatibility_ingress_window,
        )

        registry = self.runtime.registry
        binding_id = source.vault_binding_id
        with compatibility_ingress_window(registry, transition=True):
            snapshot = registry.load()
            if binding_id not in snapshot.registrations:
                if binding_id in snapshot.removal_tombstones:
                    return  # committed before a crash; roll forward
                raise RegistryError("the reserved registration vanished before commit")
            reserved = snapshot.registrations[binding_id]
            if reserved.extensions.get("removalId") != intent["removal_id"]:
                raise RegistryError("the removal reservation belongs to another removal")
            registrations = {
                key: value for key, value in snapshot.registrations.items() if key != binding_id
            }
            tombstones = dict(snapshot.removal_tombstones)
            epoch = _content_epoch(reserved)
            tombstones[binding_id] = RemovalTombstone(
                source.vault_binding_id,
                source.ref,
                source.path,
                source.vault_id,
                source.local_instance_id,
                epoch,
            )
            extensions = json.loads(json.dumps(snapshot.extensions))
            states = extensions.get("bindingEffectLeases")
            if isinstance(states, dict):
                states.pop(binding_id, None)
            lineage = _lineage(snapshot)
            lineage.append(
                {
                    "bindingId": binding_id,
                    "event": "removed",
                    "contentEpoch": epoch,
                    "removalId": intent["removal_id"],
                    "registryRevision": snapshot.revision + 1,
                }
            )
            extensions[BINDING_LINEAGE_KEY] = lineage
            stored = stored_intent(snapshot)
            assert stored is not None
            if stored.mode == INTENT_MODE_COMPATIBILITY and intent["background_bound"]:
                next_intent = replace(
                    stored,
                    revision=stored.revision + 1,
                    compatibility_binding_id=intent["candidate_binding_id"],
                    provenance=(
                        PROVENANCE_COMPATIBILITY_DEFAULT
                        if intent["removes_default"]
                        else PROVENANCE_COMPATIBILITY_HANDOFF
                    ),
                )
                extensions[BACKGROUND_INTENT_KEY] = next_intent.as_payload()
            journal_payload = None
            if intent.get("journal_moves"):
                record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
                if record.phase not in {"prepared", "no_lifecycle"} or (
                    record.desired_revision != intent["journal_revision"]
                ):
                    raise RegistryError("the removal phase journal changed before commit")
                journal_payload = replace(
                    record,
                    applied_revision=record.desired_revision,
                    phase="no_lifecycle" if record.phase == "no_lifecycle" else "committed",
                    lifecycle_posture=(
                        "no_lifecycle" if record.phase == "no_lifecycle" else "watcher"
                    ),
                ).as_payload()
            default = (
                (intent["post_default"], DEFAULT_PROVENANCE_EXPLICIT)
                if intent["removes_default"] and intent["post_default"] is not None
                else (None, None)
                if intent["removes_default"]
                else (snapshot.default_vault_binding_id, snapshot.default_vault_provenance)
            )
            registry.commit_background_transition(
                expected_revision=snapshot.revision,
                registrations=registrations,
                removal_tombstones=tombstones,
                extensions=extensions,
                settings_rebind=journal_payload,
                default=default,
                removed_binding_id=binding_id,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )

    def _compensate(self, intent: dict[str, Any]) -> None:
        """Withdraw a pre-commit removal: the source stays authoritative and unchanged."""

        from app.instance.settings_rebind import SettingsRebindRecord

        registry = self.runtime.registry
        binding_id = intent["binding_id"]
        source = VaultRegistration(**intent["source"])
        if intent.get("journal_moves") and intent.get("journal_before") is not None:
            activation = _activation(self.runtime)
            activation._cancel_before_commit(
                SettingsRebindRecord.from_payload(intent["journal_before"]),
                expected_candidate_binding_id=intent["candidate_binding_id"],
            )
        snapshot = registry.load()
        current = snapshot.registrations.get(binding_id)
        if current is not None and current.extensions.get("removalId") == intent["removal_id"]:
            registry.commit_state(
                registrations={**snapshot.registrations, binding_id: source},
                expected_revision=snapshot.revision,
                _capability=_STORAGE_MUTATION_CAPABILITY,
            )
        self.journal.discard()


# -- derived-state invalidation inventory ----------------------------------------------

#: Every binding-keyed derived table introduced by the MVR-05A binding-key migrations
#: (`app/alembic/versions/*mvr05a*`). Reactivation invalidates all of them before a
#: rebuilt binding may serve reads or effects.
PG_BINDING_KEYED_TABLES: tuple[str, ...] = (
    "store_vector_index",
    "store_relation_memberships",
    "store_relations",
    "vector_index_meta",
    "chunks",
    "embeddings",
    "relations",
    "membership",
    "store_objects",
    "objects",
    "agent_memories",
    "file_state",
    "episode_artifact_binding",
    "episode_engine_state",
    "episodes",
    "standing_questions",
    "decision_outcomes",
    "decisions",
    "sets",
    "heimdal_meeting_finalization_receipt",
)


def _invalidate_pg_tables(binding_id: str, root: Path) -> dict[str, Any]:
    del root
    from app.stores.pg import pg_available

    if not pg_available():
        # No database is configured for this runtime: nothing durable to invalidate.
        return {"tables": [], "skipped": "no_database"}
    from app.stores.pg import _connect

    cleared: list[str] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            for table in PG_BINDING_KEYED_TABLES:
                cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                row = cur.fetchone()
                if not row or row[0] is None:
                    continue
                cur.execute(
                    f"DELETE FROM public.{table} WHERE vault_binding_id = %s",  # noqa: S608
                    (binding_id,),
                )
                cleared.append(table)
    return {"tables": cleared}


def _invalidate_watcher_cursors(binding_id: str, root: Path) -> dict[str, Any]:
    """Forget per-file watcher/settings observation cursors for the retired epoch."""

    del binding_id
    state_dir_raw = os.getenv("WATCHER_STATE_DIR", "").strip()
    if not state_dir_raw:
        return {"cursors": 0}
    state_dir = Path(state_dir_raw).expanduser()
    removed = 0
    if state_dir.is_dir():
        identity = resolve_filesystem_root_identity(root)
        for item in sorted(state_dir.glob("*.json")):
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            vault_path = payload.get("vault_path") if isinstance(payload, dict) else None
            if not isinstance(vault_path, str):
                continue
            try:
                same = same_filesystem_root(
                    resolve_filesystem_root_identity(Path(vault_path)), identity
                )
            except Exception:
                continue
            if same:
                item.unlink()
                removed += 1
    return {"cursors": removed}


def _invalidate_context_caches(binding_id: str, root: Path) -> dict[str, Any]:
    """Rotate binding-keyed caches: their identity carries the binding revision."""

    del root
    return {"rotated_by": "binding_revision", "binding_id": binding_id}


#: (family, invalidator). Object/file/vector/index/retrieval/episode/standing-question
#: rows live in the binding-keyed PostgreSQL tables; watcher/settings cursors and
#: context caches are the process-side projections.
DERIVED_PROJECTION_FAMILIES: tuple[tuple[str, Callable[[str, Path], dict[str, Any]]], ...] = (
    ("binding_keyed_tables", _invalidate_pg_tables),
    ("watcher_cursors", _invalidate_watcher_cursors),
    ("context_caches", _invalidate_context_caches),
)


def _full_rescan(root: Path) -> dict[str, Any]:
    """The production full rescan manifest the rebuild receipt is bound to."""

    digest = hashlib.sha256()
    files = 0
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        digest.update(str(relative).encode())
        digest.update(b"\x00")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        files += 1
    return {"files": files, "manifest_sha256": digest.hexdigest()}


class BindingReactivationCoordinator:
    """Same-channel tombstone reactivation: no healthy read/effect before rebuild."""

    def __init__(self, runtime: InstanceRegistryRuntime) -> None:
        self.runtime = runtime
        self.journal = _Journal(
            runtime.layout.root / "binding-reactivation.json",
            REACTIVATION_SCHEMA,
            REACTIVATION_PHASES,
        )

    def reactivate_root(self, root: Path) -> VaultRegistration:
        snapshot = self.runtime.registry.load()
        _require_consumer_floors(snapshot)
        with self.journal.locked():
            existing = self.journal.load()
            if existing is not None and existing["phase"] != "complete":
                return self._run(existing)
            identity = resolve_filesystem_root_identity(root)
            matches = [
                tombstone
                for tombstone in snapshot.removal_tombstones.values()
                if same_filesystem_root(
                    resolve_filesystem_root_identity(Path(tombstone.path)), identity
                )
            ]
            if len(matches) != 1:
                raise RegistryError("root does not match exactly one removal tombstone")
            tombstone = matches[0]
            intent = {
                "schema": REACTIVATION_SCHEMA,
                "reactivation_id": f"reactivation-{uuid4()}",
                "binding_id": tombstone.vault_binding_id,
                "tombstone": asdict(tombstone),
                "retired_epoch": tombstone.content_epoch,
                "content_epoch": tombstone.content_epoch + 1,
            }
            self.journal.save(intent, "intent")
            return self._run(intent)

    def recover(self) -> VaultRegistration | None:
        with self.journal.locked():
            intent = self.journal.load()
            if intent is None or intent["phase"] == "complete":
                return None
            return self._run(intent)

    def _run(self, intent: dict[str, Any]) -> VaultRegistration:
        runtime = self.runtime
        before = self.journal.before
        binding_id: str = intent["binding_id"]
        tombstone = RemovalTombstone(**intent["tombstone"])
        root = Path(tombstone.path)
        if before(intent, "ownership_reactivated"):
            owner = runtime.ledger.active_owner(binding_id)
            if owner is None:
                runtime.ledger.reactivate(
                    binding_id,
                    channel_id=runtime.layout.channel_id,
                    root=root,
                    _capability=_STORAGE_MUTATION_CAPABILITY,
                )
            elif owner.channel_id != runtime.layout.channel_id:
                raise RegistryError("reactivated ownership diverged to another channel")
            self.journal.save(intent, "ownership_reactivated")
        if before(intent, "registered_reactivating"):
            self._register_reactivating(intent, tombstone)
            self.journal.save(intent, "registered_reactivating")
        if before(intent, "derived_invalidated"):
            receipts: dict[str, Any] = {}
            for family, invalidate in DERIVED_PROJECTION_FAMILIES:
                receipts[family] = invalidate(binding_id, root)
            intent["invalidated"] = receipts
            self.journal.save(intent, "derived_invalidated")
        if before(intent, "rescanned"):
            intent["rescan"] = _full_rescan(root)
            self.journal.save(intent, "rescanned")
        if before(intent, "rebuild_receipted"):
            intent["rebuild_receipt"] = self._write_rebuild_receipt(intent)
            self.journal.save(intent, "rebuild_receipted")
        if before(intent, "complete"):
            self._mark_healthy(intent)
            self.journal.save(intent, "complete")
        return runtime.registry.load().registrations[binding_id]

    def _register_reactivating(self, intent: dict[str, Any], tombstone: RemovalTombstone) -> None:
        registry = self.runtime.registry
        snapshot = registry.load()
        binding_id = tombstone.vault_binding_id
        existing = snapshot.registrations.get(binding_id)
        if existing is not None:
            if existing.extensions.get("reactivationId") == intent["reactivation_id"]:
                return
            raise RegistryError("the tombstoned binding was re-registered outside reactivation")
        if snapshot.removal_tombstones.get(binding_id) != tombstone:
            raise RegistryError("the removal tombstone changed before reactivation")
        registration = VaultRegistration(
            vault_binding_id=binding_id,
            ref=tombstone.ref,
            path=tombstone.path,
            vault_id=tombstone.vault_id,
            local_instance_id=tombstone.local_instance_id,
            extensions={
                "provenance": "tombstone_reactivation",
                "contentEpoch": intent["content_epoch"],
                "bindingRevision": snapshot.revision + 1,
                LIFECYCLE_STATE_KEY: LIFECYCLE_REACTIVATING,
                "reactivationId": intent["reactivation_id"],
            },
        )
        tombstones = {
            key: value for key, value in snapshot.removal_tombstones.items() if key != binding_id
        }
        extensions = json.loads(json.dumps(snapshot.extensions))
        lineage = _lineage(snapshot)
        lineage.append(
            {
                "bindingId": binding_id,
                "event": "reactivated",
                "predecessorEpoch": intent["retired_epoch"],
                "contentEpoch": intent["content_epoch"],
                "reactivationId": intent["reactivation_id"],
                "registryRevision": snapshot.revision + 1,
            }
        )
        extensions[BINDING_LINEAGE_KEY] = lineage
        registry.commit_background_transition(
            expected_revision=snapshot.revision,
            registrations={**snapshot.registrations, binding_id: registration},
            removal_tombstones=tombstones,
            extensions=extensions,
            settings_rebind=None,
            default=(snapshot.default_vault_binding_id, snapshot.default_vault_provenance),
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

    def _write_rebuild_receipt(self, intent: dict[str, Any]) -> dict[str, Any]:
        from app.instance.instance_state import _atomic_private_write

        receipt = {
            "schema": REBUILD_RECEIPT_SCHEMA,
            "binding_id": intent["binding_id"],
            "reactivation_id": intent["reactivation_id"],
            "retired_epoch": intent["retired_epoch"],
            "content_epoch": intent["content_epoch"],
            "invalidated_families": sorted(intent["invalidated"]),
            "rescan": intent["rescan"],
        }
        directory = self.runtime.layout.root / "rebuild-receipts"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{intent['binding_id']}-e{intent['content_epoch']}.json"
        payload = json.dumps(receipt, sort_keys=True).encode()
        _atomic_private_write(path, payload)
        return {"path": path.name, "sha256": hashlib.sha256(payload).hexdigest()}

    def _mark_healthy(self, intent: dict[str, Any]) -> None:
        registry = self.runtime.registry
        snapshot = registry.load()
        binding_id = intent["binding_id"]
        current = snapshot.registrations[binding_id]
        if current.extensions.get(LIFECYCLE_STATE_KEY) is None:
            return
        if current.extensions.get("reactivationId") != intent["reactivation_id"]:
            raise RegistryError("the reactivating registration belongs to another reactivation")
        extensions = {
            key: value
            for key, value in current.extensions.items()
            if key not in {LIFECYCLE_STATE_KEY, "reactivationId"}
        }
        extensions["rebuildReceiptSha256"] = intent["rebuild_receipt"]["sha256"]
        registry.commit_state(
            registrations={**snapshot.registrations, binding_id: replace(current, extensions=extensions)},
            expected_revision=snapshot.revision,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )


__all__ = [
    "BINDING_LINEAGE_KEY",
    "DERIVED_PROJECTION_FAMILIES",
    "PG_BINDING_KEYED_TABLES",
    "REACTIVATION_PHASES",
    "REMOVAL_PHASES",
    "BindingReactivationCoordinator",
    "BindingRemovalCoordinator",
    "binding_epoch_lineage",
]
