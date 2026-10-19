"""Supervised ordinary-producer identity persistence for DEV/TEST sources.

This module deliberately does not participate in legacy recovery.  It runs the
ordinary ``vault-alpha`` producer, then independently proves that the complete
selected inventory carries persisted identity evidence.  Public results are a
small, fixed-field receipt; paths, UUIDs and child output remain private.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import UUID


RECEIPT_CONTRACT = "native-source-identity-persistence.v1"
TERMINAL_STATES = frozenset({"committed", "failed"})
REFUSAL_REASONS = frozenset({
    "source_context_refused",
    "source_producer_failed",
    "source_summary_incomplete",
    "source_identity_ineligible",
    "source_identity_ambiguous",
    "source_operation_conflict",
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


def selected_identity_inventory(vault_root: Path) -> IdentityInventory:
    """Inspect the canonical selected inventory without emitting private data."""
    from app.ingest.vault_alpha import select_source_backed_rebuild_candidates
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from app.services.companion_note import read_companion

    root = vault_root.expanduser().resolve(strict=True)
    selected = select_source_backed_rebuild_candidates(root)
    selected_rel = tuple(path.relative_to(root).as_posix() for path in selected)
    persisted = missing = invalid = ambiguous = 0
    claims: dict[str, int] = {}
    snapshots: dict[str, tuple[str, tuple[Any, ...], str, Any]] = {}
    for path in selected:
        relative = path.relative_to(root).as_posix()
        try:
            raw, identity = read_recovery_snapshot_relative(
                relative, vault_root=root,
            )
            frontmatter, _body, error = parse_bounded_frontmatter(raw)
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
        if companion is not None and _canonical_uuid(companion.uuid) != declared:
            invalid += 1
            continue
        snapshots[relative] = (raw, identity, declared, companion)
        persisted += 1
        claims[declared] = claims.get(declared, 0) + 1
    if tuple(
        path.relative_to(root).as_posix()
        for path in select_source_backed_rebuild_candidates(root)
    ) != selected_rel:
        raise SourceIdentityPersistenceRefusal("source_operation_conflict")
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


def validate_receipt(payload: Any) -> dict[str, Any]:
    """Validate the complete public shape and reject accidental private fields."""
    required = {
        "contract", "operation_id", "channel", "revision", "terminal_state",
        "eligible", "reason", *_COUNT_FIELDS,
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise SourceIdentityPersistenceRefusal("source_context_refused")
    try:
        if (
            payload["contract"] != RECEIPT_CONTRACT
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
    *, producer_error_count: int = 0, reason: str | None = None,
) -> dict[str, Any]:
    eligible = inventory.eligible and producer_error_count == 0 and reason is None
    payload = {
        "contract": RECEIPT_CONTRACT,
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
    return validate_receipt(payload)


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
    if len(argv) != 4:
        return 78
    operation_id, channel, revision, root_value = argv
    try:
        from app.ops.native_source_bootstrap import preflight

        selected = preflight(f"{channel}:{revision}")
        root = Path(root_value).resolve(strict=True)
        if selected is None or selected != root:
            raise SourceIdentityPersistenceRefusal("source_context_refused")
        receipt = run_ordinary_persistence(
            operation_id=operation_id, channel=channel, revision=revision, vault_root=root,
        )
        print(json.dumps(receipt, sort_keys=True))
        # A validated failed receipt is a successfully observed terminal
        # operation.  Transport exit 78 is reserved for an unobservable/crashed
        # worker so the supervisor never discards a finite refusal receipt.
        return 0
    except Exception:
        return 78


if __name__ == "__main__":
    import sys

    raise SystemExit(worker_main(sys.argv[1:]))
