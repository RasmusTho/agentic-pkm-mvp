"""Supervised ordinary-producer identity persistence for DEV/TEST sources.

This module deliberately does not participate in legacy recovery.  It runs the
ordinary producer selected by the explicit request, then independently proves
that its complete inventory carries persisted identity evidence.  Public
results are a small, fixed-field receipt; paths, UUIDs and child output remain
private.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID

if TYPE_CHECKING:
    from app.ingest.producer_policy import RegistryProducerPolicy
    from app.watcher.registry import RegistryIngestObservation


RECEIPT_CONTRACT = "native-source-identity-persistence.v1"
REGISTRY_RECEIPT_CONTRACT = "native-source-identity-persistence.v2"
PRODUCER_KINDS = frozenset({"vault-alpha", "registry"})
TERMINAL_STATES = frozenset({"committed", "failed"})
REFUSAL_REASONS = frozenset({
    "source_context_refused",
    "source_producer_failed",
    "source_summary_incomplete",
    "source_identity_ineligible",
    "source_identity_ambiguous",
    "source_operation_conflict",
    "source_worker_failed",
    "source_lock_acquisition_failed",
    "source_locked_guard_failed",
    "source_writer_stop_failed",
    "source_worker_transport_failed",
    "source_worker_quiesce_failed",
    "source_worker_receipt_refused",
    "source_producer_receipt_write_failed",
    "source_writer_restore_failed",
    "source_lock_retirement_failed",
})
_COUNT_FIELDS = (
    "selected_count", "persisted_count", "missing_count", "invalid_count",
    "ambiguous_count", "producer_error_count",
)


class SourceIdentityPersistenceRefusal(RuntimeError):
    """A fixed content-free refusal class."""

    def __init__(self, reason: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError("unknown source identity persistence refusal")
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class IdentityInventory:
    selected_count: int
    persisted_count: int
    missing_count: int
    invalid_count: int
    ambiguous_count: int

    @property
    def eligible(self) -> bool:
        return (
            self.selected_count == self.persisted_count
            and self.missing_count == 0
            and self.invalid_count == 0
            and self.ambiguous_count == 0
        )


def _canonical_uuid(value: Any) -> str | None:
    from app.ingest.vault_alpha import _normalize_uuid, _sanitize_uuid

    try:
        candidate, invalid = _sanitize_uuid(_normalize_uuid(value))
    except (ValueError, TypeError, AttributeError):
        return None
    if invalid or not candidate:
        return None
    return candidate


def _identity_inventory_for_paths(
    vault_root: Path, selected: tuple[Path, ...], *, require_companion: bool = False,
) -> IdentityInventory:
    """Inspect one frozen path inventory without emitting private data."""
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.rebuildability import canonical_product_body_text
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.companion_note import find_duplicate_companions, read_companion

    root = vault_root.expanduser().resolve(strict=True)
    persisted = missing = invalid = ambiguous = 0
    claims: dict[str, int] = {}
    duplicate_companion_ids = (
        {duplicate.uuid for duplicate in find_duplicate_companions(root)}
        if require_companion else set()
    )
    snapshots: dict[str, tuple[str, tuple[Any, ...], str, Any]] = {}
    for path in selected:
        relative = path.relative_to(root).as_posix()
        try:
            raw, identity = read_recovery_snapshot_relative(
                relative, vault_root=root,
            )
            frontmatter, body, error = parse_bounded_frontmatter(raw)
        except Exception:
            invalid += 1
            continue
        if error is not None:
            invalid += 1
            continue
        declared = _canonical_uuid(frontmatter.get("uuid"))
        if declared is None:
            if frontmatter.get("uuid") not in (None, ""):
                invalid += 1
            else:
                missing += 1
            continue
        try:
            companion = read_companion(root, declared)
        except Exception:
            invalid += 1
            continue
        if companion is None and require_companion:
            missing += 1
            continue
        if declared in duplicate_companion_ids:
            invalid += 1
            continue
        if companion is not None and _canonical_uuid(companion.uuid) != declared:
            invalid += 1
            continue
        if require_companion and companion is not None:
            if (
                companion.source_ref != relative
                or companion.content_hash
                != hashlib.sha256(
                    canonical_product_body_text(body).encode("utf-8")
                ).hexdigest()
            ):
                invalid += 1
                continue
        snapshots[relative] = (raw, identity, declared, companion)
        persisted += 1
        claims[declared] = claims.get(declared, 0) + 1
    for relative, (raw, identity, declared, companion) in snapshots.items():
        try:
            current_raw, current_identity = read_recovery_snapshot_relative(
                relative, vault_root=root,
            )
            current_companion = read_companion(root, declared)
        except Exception:
            raise SourceIdentityPersistenceRefusal("source_operation_conflict") from None
        if (
            current_raw != raw
            or current_identity != identity
            or current_companion != companion
        ):
            raise SourceIdentityPersistenceRefusal("source_operation_conflict")
    ambiguous = sum(count for count in claims.values() if count > 1)
    return IdentityInventory(len(selected), persisted, missing, invalid, ambiguous)


def selected_identity_inventory(vault_root: Path) -> IdentityInventory:
    """Inspect the canonical vault-alpha inventory without private output."""
    from app.ingest.vault_alpha import select_source_backed_rebuild_candidates

    root = vault_root.expanduser().resolve(strict=True)
    selected = tuple(select_source_backed_rebuild_candidates(root))
    selected_rel = tuple(path.relative_to(root).as_posix() for path in selected)
    inventory = _identity_inventory_for_paths(root, selected)
    if tuple(
        path.relative_to(root).as_posix()
        for path in select_source_backed_rebuild_candidates(root)
    ) != selected_rel:
        raise SourceIdentityPersistenceRefusal("source_operation_conflict")
    return inventory


def _registry_plan(
    vault_root: Path,
) -> tuple[RegistryProducerPolicy, tuple[RegistryIngestObservation, ...]]:
    """Freeze canonical registry policy and exact ordinary source observations."""
    from app.ingest.producer_policy import registry_producer_policy
    from app.watcher.registry import (
        DEFAULT_REGISTRY_CONFIG_PATH,
        load_registry_config,
        source_backed_registry_observations,
    )
    from app.vault.paths import resolve_vault_system_dir_rel_or_default
    from app.watcher.settings_delta import is_settings_control_path

    root = vault_root.expanduser().resolve(strict=True)
    policy = registry_producer_policy(root)
    if not policy.enabled or policy.root != root or not policy.scopes:
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    config_snapshot = DEFAULT_REGISTRY_CONFIG_PATH.read_bytes()
    cfg = load_registry_config(DEFAULT_REGISTRY_CONFIG_PATH, read_only=True)
    specifications = tuple(
        (spec.name, spec.emit_event, spec.scope_glob) for spec in cfg.specs
    )
    if (
        not cfg.enable
        or cfg.vault_path.resolve(strict=True) != root
        or specifications != policy.specifications
        or hashlib.sha256(config_snapshot).hexdigest() != policy.registry_digest
    ):
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    observations = source_backed_registry_observations(cfg)
    if DEFAULT_REGISTRY_CONFIG_PATH.read_bytes() != config_snapshot:
        raise SourceIdentityPersistenceRefusal("source_operation_conflict")
    paths = tuple(observation.path for observation in observations)
    configured_system_dir = resolve_vault_system_dir_rel_or_default(root)
    expected_paths = frozenset(
        path for path in policy.sources
        if not is_settings_control_path(
            path.relative_to(root), configured_system_dir=configured_system_dir,
        )
    )
    if not paths or len(paths) != len(set(paths)):
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    if frozenset(paths) != expected_paths:
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    return policy, observations


def registry_identity_inventory(
    vault_root: Path, observations: tuple[RegistryIngestObservation, ...],
) -> IdentityInventory:
    return _identity_inventory_for_paths(
        vault_root, tuple(observation.path for observation in observations),
        require_companion=True,
    )


def _registry_semantic_fingerprints(
    vault_root: Path, observations: tuple[RegistryIngestObservation, ...],
) -> tuple[tuple[str, str], ...]:
    """Fingerprint private source meaning while excluding the allowed identity write."""
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.rebuildability import canonical_product_body_text, parse_bounded_frontmatter

    root = vault_root.expanduser().resolve(strict=True)
    result: list[tuple[str, str]] = []
    for observation in observations:
        relative = observation.path.relative_to(root).as_posix()
        raw, _identity = read_recovery_snapshot_relative(relative, vault_root=root)
        frontmatter, body, error = parse_bounded_frontmatter(raw)
        if error is not None:
            raise SourceIdentityPersistenceRefusal("source_operation_conflict")
        source_metadata = dict(frontmatter)
        source_metadata.pop("uuid", None)
        source_metadata.pop("id", None)
        payload = json.dumps(
            {
                "frontmatter": source_metadata,
                "body": canonical_product_body_text(body),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        result.append((relative, hashlib.sha256(payload).hexdigest()))
    return tuple(result)


def validate_receipt(payload: Any) -> dict[str, Any]:
    """Validate the complete public shape and reject accidental private fields."""
    required = {
        "contract", "operation_id", "channel", "revision", "terminal_state",
        "eligible", "reason", *_COUNT_FIELDS,
    }
    if not isinstance(payload, dict):
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    is_registry = payload.get("contract") == REGISTRY_RECEIPT_CONTRACT
    if set(payload) != (required | ({"producer_kind"} if is_registry else set())):
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    try:
        if (
            payload["contract"] not in {RECEIPT_CONTRACT, REGISTRY_RECEIPT_CONTRACT}
            or (is_registry and payload["producer_kind"] != "registry")
            or str(UUID(payload["operation_id"])) != payload["operation_id"]
            or payload["channel"] not in {"dev", "test"}
            or re.fullmatch(r"[0-9a-f]{40}", payload["revision"]) is None
            or payload["terminal_state"] not in TERMINAL_STATES
            or type(payload["eligible"]) is not bool
            or payload["reason"] not in ({None} | REFUSAL_REASONS)
            or any(type(payload[key]) is not int or payload[key] < 0 for key in _COUNT_FIELDS)
            or payload["persisted_count"] > payload["selected_count"]
            or payload["eligible"] != (
                payload["terminal_state"] == "committed"
                and payload["reason"] is None
                and payload["selected_count"] == payload["persisted_count"]
                and not any(payload[key] for key in (
                    "missing_count", "invalid_count", "ambiguous_count", "producer_error_count"
                ))
            )
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SourceIdentityPersistenceRefusal("source_context_refused") from None
    return payload


def _receipt(
    operation_id: str, channel: str, revision: str, inventory: IdentityInventory,
    *, producer_kind: str = "vault-alpha", producer_error_count: int = 0,
    reason: str | None = None,
) -> dict[str, Any]:
    eligible = inventory.eligible and producer_error_count == 0 and reason is None
    payload = {
        "contract": (
            REGISTRY_RECEIPT_CONTRACT if producer_kind == "registry"
            else RECEIPT_CONTRACT
        ),
        "operation_id": operation_id,
        "channel": channel,
        "revision": revision,
        "terminal_state": "committed" if eligible else "failed",
        "eligible": eligible,
        "reason": reason,
        "selected_count": inventory.selected_count,
        "persisted_count": inventory.persisted_count,
        "missing_count": inventory.missing_count,
        "invalid_count": inventory.invalid_count,
        "ambiguous_count": inventory.ambiguous_count,
        "producer_error_count": producer_error_count,
    }
    if producer_kind == "registry":
        payload["producer_kind"] = producer_kind
    return validate_receipt(payload)


def run_registry_persistence(
    *, operation_id: str, channel: str, revision: str, vault_root: Path,
    current_state: bool = False,
) -> dict[str, Any]:
    """Run the exact ordinary-registry metadata phase under live authority."""
    from app.events.topic_schema_registry import validate_topic_payload
    from app.events.types import INGEST_VAULT_CHANGED
    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
    from app.watcher.registry import ingest_vault_changed_payload
    from app.workers.outbox_binding_gate import current_binding_effect_window
    from app.workers.outbox_worker import persist_registry_source_identity

    empty = IdentityInventory(0, 0, 0, 0, 0)
    try:
        if (
            str(UUID(operation_id)) != operation_id
            or channel not in {"dev", "test"}
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SourceIdentityPersistenceRefusal("source_context_refused") from None
    root = vault_root.expanduser().resolve(strict=True)
    try:
        runtime = resolve_scalar_binding_runtime(vault_root=root)
        if runtime is None or runtime.root != root or runtime.channel_id != channel:
            raise SourceIdentityPersistenceRefusal("source_context_refused")
        with current_binding_effect_window(runtime):
            before_policy, observations = _registry_plan(root)
            admitted_inventory = tuple(
                (observation.relative_path, observation.watcher)
                for observation in observations
            )
            admitted_content = _registry_semantic_fingerprints(root, observations)
            if current_state:
                _admit_registry_selection(root, observations)
                # Full selection and policy, not a prior diagnostic's counts,
                # authorizes the ordinary producer at its actual effect fence.
                fresh_policy, fresh_observations = _registry_plan(root)
                if before_policy != fresh_policy or observations != fresh_observations:
                    raise SourceIdentityPersistenceRefusal('source_operation_conflict')
                _admit_registry_selection(root, fresh_observations)
            for observation in observations:
                payload = ingest_vault_changed_payload(
                    vault_root=root,
                    relative_path=observation.relative_path,
                    mtime=observation.mtime,
                    content_hash=observation.content_hash,
                    watcher=observation.watcher,
                )
                validate_topic_payload(INGEST_VAULT_CHANGED, payload)
                persisted = persist_registry_source_identity(
                    payload,
                    vault_root=root,
                    source_vault_binding_id=runtime.vault_binding_id,
                    allow_retry_enqueue=False,
                    require_persisted_evidence=True,
                )
                if persisted is None:
                    raise SourceIdentityPersistenceRefusal(
                        "source_summary_incomplete",
                    )
            after_policy, after_observations = _registry_plan(root)
            current_inventory = tuple(
                (observation.relative_path, observation.watcher)
                for observation in after_observations
            )
            current_content = _registry_semantic_fingerprints(root, after_observations)
            if (
                before_policy != after_policy
                or admitted_inventory != current_inventory
                or admitted_content != current_content
            ):
                raise SourceIdentityPersistenceRefusal("source_operation_conflict")
            inventory = registry_identity_inventory(root, after_observations)
    except SourceIdentityPersistenceRefusal as exc:
        return _receipt(
            operation_id, channel, revision, empty,
            producer_kind="registry", producer_error_count=1, reason=exc.reason,
        )
    except Exception:
        return _receipt(
            operation_id, channel, revision, empty,
            producer_kind="registry", producer_error_count=1,
            reason="source_producer_failed",
        )
    reason = None
    if inventory.ambiguous_count:
        reason = "source_identity_ambiguous"
    elif not inventory.eligible:
        reason = "source_identity_ineligible"
    return _receipt(
        operation_id, channel, revision, inventory,
        producer_kind="registry", reason=reason,
    )


def _admit_registry_selection(root: Path, observations: tuple[RegistryIngestObservation, ...]) -> None:
    """Read the whole fixed selection before any ordinary metadata effect."""
    from app.knowledge.profile_authority_store import is_profile_note_source_read_only
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.note_uuid import is_read_only_derived_artifact
    from app.workers.outbox_worker import _normalize_uuid_value

    inventory = registry_identity_inventory(root, observations)
    if inventory.invalid_count or inventory.ambiguous_count:
        raise SourceIdentityPersistenceRefusal('source_identity_ineligible')
    claims: set[str] = set()
    for observation in observations:
        relative = observation.path.relative_to(root).as_posix()
        raw, _identity = read_recovery_snapshot_relative(relative, vault_root=root)
        metadata, _body, error = parse_bounded_frontmatter(raw)
        declared = metadata.get('uuid')
        alternate = metadata.get('id')
        normalized = _normalize_uuid_value(declared)
        if (error is not None or is_profile_note_source_read_only(root, relative, _canonical_uuid(declared))
            or is_read_only_derived_artifact(metadata)):
            raise SourceIdentityPersistenceRefusal('source_identity_ineligible')
        if (declared not in (None, '') and (
                not normalized or _canonical_uuid(normalized) != normalized
            )
            or alternate not in (None, '', declared)):
            raise SourceIdentityPersistenceRefusal('source_identity_ineligible')
        if declared not in (None, ''):
            identity = _canonical_uuid(declared)
            if identity in claims:
                raise SourceIdentityPersistenceRefusal('source_identity_ambiguous')
            claims.add(str(identity))


def run_ordinary_persistence(
    *, operation_id: str, channel: str, revision: str, vault_root: Path,
    producer: Callable[[Path], Any] | None = None,
    inventory_reader: Callable[[Path], IdentityInventory] = selected_identity_inventory,
) -> dict[str, Any]:
    """Run the ordinary producer and require a fresh complete eligibility readback."""
    try:
        if (
            str(UUID(operation_id)) != operation_id
            or channel not in {"dev", "test"}
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise SourceIdentityPersistenceRefusal("source_context_refused") from None

    if producer is None:
        from app.ingest.vault_alpha import run_vault_alpha_ingest

        def producer(root: Path) -> Any:
            return run_vault_alpha_ingest(
                root, max_notes=0, include_test_note=False, force=True,
                source_backed_rebuild=False,
            )

    try:
        # The ordinary producer is noisy and may mention private paths.  Its
        # output never crosses this boundary; only typed counters are consumed.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            summary = producer(vault_root)
    except SourceIdentityPersistenceRefusal as exc:
        inventory = IdentityInventory(0, 0, 0, 1, 0)
        return _receipt(operation_id, channel, revision, inventory, reason=exc.reason)
    except Exception:
        empty = IdentityInventory(0, 0, 0, 0, 0)
        return _receipt(
            operation_id, channel, revision, empty,
            producer_error_count=1, reason="source_producer_failed",
        )

    try:
        from app.ops.native_source_bootstrap import source_rebuild_counts

        counters = source_rebuild_counts({
            key: getattr(summary, key, None)
            for key in (
                "scanned", "ingested", "errors", "malformed",
                "skipped_locked", "skipped_invalid",
            )
        })
        scanned, ingested, errors, malformed, locked, invalid = counters
        producer_errors = errors + malformed + locked + invalid
        if scanned != ingested or producer_errors:
            empty = IdentityInventory(0, 0, 0, 0, 0)
            return _receipt(
                operation_id, channel, revision, empty,
                producer_error_count=max(producer_errors, scanned - ingested, 1),
                reason="source_summary_incomplete",
            )
    except Exception:
        empty = IdentityInventory(0, 0, 0, 0, 0)
        return _receipt(
            operation_id, channel, revision, empty,
            producer_error_count=1, reason="source_summary_incomplete",
        )

    try:
        inventory = inventory_reader(vault_root)
    except Exception:
        inventory = IdentityInventory(0, 0, 0, 1, 0)
        return _receipt(
            operation_id, channel, revision, inventory,
            reason="source_identity_ineligible",
        )
    reason = None
    if inventory.ambiguous_count:
        reason = "source_identity_ambiguous"
    elif not inventory.eligible:
        reason = "source_identity_ineligible"
    return _receipt(operation_id, channel, revision, inventory, reason=reason)


def worker_main(argv: list[str]) -> int:
    """Private container entrypoint; stdout is one validated fixed receipt."""
    if len(argv) not in {4, 5, 6}:
        return 78
    operation_id, channel, revision, root_value, *kind_value = argv
    producer_kind = kind_value[0] if kind_value else "vault-alpha"
    current_state = len(kind_value) == 2 and kind_value[1] == 'current-state'
    try:
        if (
            str(UUID(operation_id)) != operation_id
            or channel not in {"dev", "test"}
            or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            or producer_kind not in PRODUCER_KINDS
            or (len(kind_value) == 2 and (not current_state or producer_kind != 'registry'))
        ):
            return 78
    except (ValueError, TypeError, AttributeError):
        return 78

    try:
        # Imports, preflight, producer and inventory code are private and may
        # be noisy.  Discard both streams across the complete boundary, then
        # emit exactly one validated fixed receipt after leaving it.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                try:
                    from app.ops.native_source_bootstrap import preflight

                    selected = preflight(f"{channel}:{revision}")
                    root = Path(root_value).resolve(strict=True)
                    if selected is None or selected != root:
                        raise SourceIdentityPersistenceRefusal("source_context_refused")
                except SourceIdentityPersistenceRefusal:
                    raise
                except Exception:
                    raise SourceIdentityPersistenceRefusal(
                        "source_context_refused",
                    ) from None
                receipt = (
                    run_registry_persistence(
                        operation_id=operation_id, channel=channel,
                        revision=revision, vault_root=root,
                        **({'current_state': True} if current_state else {}),
                    )
                    if producer_kind == "registry"
                    else run_ordinary_persistence(
                        operation_id=operation_id, channel=channel,
                        revision=revision, vault_root=root,
                    )
                )
            except SourceIdentityPersistenceRefusal as exc:
                receipt = _receipt(
                    operation_id, channel, revision, IdentityInventory(0, 0, 0, 1, 0),
                    producer_kind=producer_kind,
                    reason=exc.reason,
                )
            except Exception:
                receipt = _receipt(
                    operation_id, channel, revision, IdentityInventory(0, 0, 0, 0, 0),
                    producer_kind=producer_kind,
                    producer_error_count=1, reason="source_worker_failed",
                )
            receipt = validate_receipt(receipt)
    except Exception:
        return 78

    print(json.dumps(receipt, sort_keys=True))
    # A validated failed receipt is a successfully observed terminal
    # operation.  Transport exit 78 is reserved for an unobservable/crashed
    # worker so the supervisor never discards a finite refusal receipt.
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(worker_main(sys.argv[1:]))
