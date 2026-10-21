"""Exact, inert DEV repair mechanics for two independently classified identity cases.

The module does not select targets, allocate identities, load a controller, or dispatch a
native operation.  A separately governed host runner may pass a frozen private target set
through :func:`run_supportable_repair_batch`.  Every artifact is re-qualified from the
canonical source inventory inside the caller-owned fence immediately before its CAS.

Private proposals intentionally retain paths, identities, and original/candidate bytes so
that exact readback and rollback are possible.  Those objects have no serialization helper.
The only public result is the closed, content-free counter receipt validated below.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any, Protocol

from app.briefing.compose import (
    BriefingIdentityMigration,
    migrate_briefing_identity,
    prepare_briefing_identity_migration,
)
from app.knowledge.write_ops import write_note_from_absolute
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


RECEIPT_CONTRACT = "native-source-identity-supportable-repair.v1"
ACTION = "operator.repair-supportable-source-identity"
WRITER_IDENTITY = "operator.supportable-source-identity-repair"
EXPECTED_COMPANION_COUNT = 23
EXPECTED_BRIEFING_COUNT = 26
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_RESULTS = frozenset({"committed", "failed", "indeterminate"})
_REASONS = frozenset({
    "authority_refused",
    "context_refused",
    "write_refused",
    "readback_indeterminate",
})


class SupportableRepairRefusal(RuntimeError):
    """Fixed refusal without private exception text."""

    def __init__(self, reason: str) -> None:
        if reason not in _REASONS:
            reason = "context_refused"
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CompanionContinuityProposal:
    """Private exact-byte proposal for one already-established companion identity."""

    source_rel: str
    companion_rel: str
    identity: str
    observed_at: str
    original_text: str
    candidate_text: str
    original_sha256: str
    candidate_sha256: str


@dataclass(frozen=True)
class BriefingRepairProposal:
    """Private wrapper around the canonical composer migration proposal."""

    for_date: date
    migration: BriefingIdentityMigration
    original_text: str
    original_sha256: str
    candidate_sha256: str


@dataclass(frozen=True)
class RepairBatch:
    """Frozen private target set bound to one revision, image, and selection."""

    revision: str
    image_digest: str
    selection_sha256: str
    companion: tuple[CompanionContinuityProposal, ...]
    briefings: tuple[BriefingRepairProposal, ...]


@dataclass(frozen=True)
class RepairAuthoritySnapshot:
    """Fresh host facts read by the effects implementation inside its owned fence."""

    revision: str
    image_digest: str
    selection_sha256: str
    controller_unloaded: bool
    write_guard_healthy: bool
    writers_isolated: bool
    owned_operation_fences_healthy: bool


class RepairEffects(Protocol):
    """Host-owned proof seam; implementations must read facts, not accept booleans."""

    def owned_repair_fence(self) -> AbstractContextManager[None]: ...

    def read_repair_authority(self) -> RepairAuthoritySnapshot: ...


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vault_context_root(vault_context: Any) -> Path:
    value = getattr(vault_context, "active_vault_path", None)
    if not isinstance(value, str) or not value:
        raise SupportableRepairRefusal("context_refused")
    try:
        root = Path(value).expanduser().resolve(strict=True)
    except OSError:
        raise SupportableRepairRefusal("context_refused") from None
    if not root.is_dir():
        raise SupportableRepairRefusal("context_refused")
    return root


def _regular_nofollow_text(path: Path) -> tuple[str, str]:
    """Read one stable regular file through a no-follow descriptor."""

    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise SupportableRepairRefusal("authority_refused") from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SupportableRepairRefusal("authority_refused")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise SupportableRepairRefusal("authority_refused")
        raw = b"".join(chunks)
        return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeDecodeError):
        raise SupportableRepairRefusal("authority_refused") from None
    finally:
        os.close(descriptor)


def _companion_file(root: Path, identity: str) -> Path:
    from app.services.companion_note import companion_path

    canonical = root / companion_path(identity, root)
    legacy = root / "_system" / "companions" / f"{identity}.md"
    present = [path for path in (canonical, legacy) if path.exists() or path.is_symlink()]
    if len(present) != 1:
        raise SupportableRepairRefusal("authority_refused")
    return present[0]


def _companion_claim_counts(
    root: Path, *, identity: str, current_source_rel: str,
) -> tuple[int, int]:
    """Count exact companion UUID/current-locator claims across both supported trees."""

    from app.services.companion_note import companion_path

    canonical = (root / companion_path(identity, root)).parent
    legacy = root / "_system" / "companions"
    directories: list[Path] = []
    for directory in (canonical, legacy):
        if any(directory == existing for existing in directories):
            continue
        directories.append(directory)
    identity_claims = current_locator_claims = 0
    for directory in directories:
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise SupportableRepairRefusal("authority_refused")
        for candidate in sorted(directory.iterdir()):
            if candidate.suffix != ".md":
                continue
            raw, _version = _regular_nofollow_text(candidate)
            try:
                frontmatter, _body = load_frontmatter(raw)
            except Exception:
                raise SupportableRepairRefusal("authority_refused") from None
            if not isinstance(frontmatter, dict):
                raise SupportableRepairRefusal("authority_refused")
            identity_claims += frontmatter.get("uuid") == identity
            current_locator_claims += frontmatter.get("source_ref") == current_source_rel
    return identity_claims, current_locator_claims


def _canonical_inventory(root: Path) -> tuple[Any, ...]:
    from app.ops.native_source_identity_persistence import _registry_plan

    _policy, observations = _registry_plan(root)
    return observations


def _source_claims(root: Path, observations: tuple[Any, ...]) -> tuple[dict[str, int], set[str]]:
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability import parse_bounded_frontmatter

    claims: dict[str, int] = {}
    locators: set[str] = set()
    for observation in observations:
        relative = observation.path.relative_to(root).as_posix()
        if relative in locators:
            raise SupportableRepairRefusal("authority_refused")
        locators.add(relative)
        raw, _identity = read_recovery_snapshot_relative(relative, vault_root=root)
        frontmatter, _body, error = parse_bounded_frontmatter(raw)
        if error is not None:
            continue
        declared = _canonical_uuid(frontmatter.get("uuid"))
        if declared is not None:
            claims[declared] = claims.get(declared, 0) + 1
    return claims, locators


def _validated_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise SupportableRepairRefusal("context_refused") from None
    if parsed.tzinfo is None or not value:
        raise SupportableRepairRefusal("context_refused")
    return value


def prepare_companion_continuity_repair(
    *, vault_root: Path, source_rel: str, observed_at: str,
) -> CompanionContinuityProposal:
    """Compute one concrete Scenario-F proposal from fresh canonical reads."""

    from app.knowledge.profile_authority_store import is_profile_note_source
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability import canonical_product_body_text, parse_bounded_frontmatter
    from app.services.companion_note import (
        IDENTITY_HISTORY_MAX,
        find_duplicate_companions,
        is_companion_path,
        read_companion,
    )
    from app.services.note_uuid import is_read_only_derived_artifact

    root = vault_root.expanduser().resolve(strict=True)
    timestamp = _validated_timestamp(observed_at)
    try:
        relative = Path(source_rel)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != source_rel:
            raise ValueError
        source = root / relative
        if source.is_symlink():
            raise ValueError
        source.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise SupportableRepairRefusal("context_refused") from None

    observations = _canonical_inventory(root)
    selected = tuple(item.path.relative_to(root).as_posix() for item in observations)
    if selected.count(source_rel) != 1:
        raise SupportableRepairRefusal("authority_refused")
    claims, locators = _source_claims(root, observations)
    raw, _source_identity = read_recovery_snapshot_relative(source_rel, vault_root=root)
    frontmatter, body, error = parse_bounded_frontmatter(raw)
    declared = _canonical_uuid(frontmatter.get("uuid")) if error is None else None
    if (
        declared is None
        or claims.get(declared) != 1
        or is_profile_note_source(root, source_rel, declared)
        or is_read_only_derived_artifact(frontmatter)
    ):
        raise SupportableRepairRefusal("authority_refused")
    if any(item.uuid == declared for item in find_duplicate_companions(root)):
        raise SupportableRepairRefusal("authority_refused")
    companion = read_companion(root, declared)
    if companion is None or _canonical_uuid(companion.uuid) != declared:
        raise SupportableRepairRefusal("authority_refused")
    identity_claims, current_locator_claims = _companion_claim_counts(
        root,
        identity=declared,
        current_source_rel=source_rel,
    )
    if (
        identity_claims != 1
        or current_locator_claims != 0
        or companion.source_ref == source_rel
        or companion.source_ref in locators
        or not is_companion_path(Path(companion.source_ref), vault_root=root)
    ):
        raise SupportableRepairRefusal("authority_refused")
    current_hash = hashlib.sha256(
        canonical_product_body_text(body).encode("utf-8")
    ).hexdigest()
    if companion.content_hash == current_hash:
        raise SupportableRepairRefusal("authority_refused")

    companion_file = _companion_file(root, declared)
    original, original_sha256 = _regular_nofollow_text(companion_file)
    try:
        companion_fm, companion_body = load_frontmatter(original)
    except Exception:
        raise SupportableRepairRefusal("authority_refused") from None
    if not isinstance(companion_fm, dict):
        raise SupportableRepairRefusal("authority_refused")
    before = dict(companion_fm)
    if (
        before.get("uuid") != declared
        or before.get("source_ref") != companion.source_ref
        or before.get("content_hash") != companion.content_hash
    ):
        raise SupportableRepairRefusal("authority_refused")
    history = before.get("identity_history", [])
    if not isinstance(history, list):
        raise SupportableRepairRefusal("authority_refused")
    entry = {
        "timestamp": timestamp,
        "event": "path_change",
        "before": {
            "source_ref": companion.source_ref,
            "content_hash": companion.content_hash,
        },
        "after": {"source_ref": source_rel, "content_hash": current_hash},
        "reason": "canonical source continuity repair",
    }
    candidate_fm = dict(before)
    candidate_fm["source_ref"] = source_rel
    candidate_fm["content_hash"] = current_hash
    candidate_fm["identity_history"] = [*history, entry][-IDENTITY_HISTORY_MAX:]
    candidate = dump_frontmatter(candidate_fm, companion_body)
    after, after_body = load_frontmatter(candidate)
    unchanged_before = dict(before)
    unchanged_after = dict(after)
    for key in ("source_ref", "content_hash", "identity_history"):
        unchanged_before.pop(key, None)
        unchanged_after.pop(key, None)
    if unchanged_before != unchanged_after or companion_body != after_body:
        raise SupportableRepairRefusal("authority_refused")
    return CompanionContinuityProposal(
        source_rel=source_rel,
        companion_rel=companion_file.relative_to(root).as_posix(),
        identity=declared,
        observed_at=timestamp,
        original_text=original,
        candidate_text=candidate,
        original_sha256=original_sha256,
        candidate_sha256=_sha256_text(candidate),
    )


def commit_companion_continuity_repair(
    proposal: CompanionContinuityProposal,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> None:
    """Re-prove and publish exactly one companion proposal by canonical CAS."""

    root = vault_root.expanduser().resolve(strict=True)
    fresh = prepare_companion_continuity_repair(
        vault_root=root,
        source_rel=proposal.source_rel,
        observed_at=proposal.observed_at,
    )
    if fresh != proposal:
        raise SupportableRepairRefusal("authority_refused")
    target = root / proposal.companion_rel
    try:
        write_note_from_absolute(
            target,
            proposal.candidate_text,
            vault_root=root,
            action=ACTION,
            write_guard=write_guard,
            expected_version=proposal.original_sha256,
            writer_identity=WRITER_IDENTITY,
        )
    except Exception:
        raise SupportableRepairRefusal("write_refused") from None
    _text, version = _regular_nofollow_text(target)
    if version != proposal.candidate_sha256:
        raise SupportableRepairRefusal("readback_indeterminate")


def prepare_briefing_repair(
    *, vault_context: Any, for_date: date,
) -> BriefingRepairProposal:
    """Bind the existing composer-owned proposal to exact original bytes."""

    migration = prepare_briefing_identity_migration(
        vault_context=vault_context,
        for_date=for_date,
    )
    if migration is None:
        raise SupportableRepairRefusal("authority_refused")
    root = _vault_context_root(vault_context)
    target = root / migration.note_rel_path
    original, version = _regular_nofollow_text(target)
    if version != migration.expected_version:
        raise SupportableRepairRefusal("authority_refused")
    try:
        before, before_body = load_frontmatter(original)
        after, after_body = load_frontmatter(migration.content)
    except Exception:
        raise SupportableRepairRefusal("authority_refused") from None
    before_without_uuid = dict(before)
    after_without_uuid = dict(after)
    before_without_uuid.pop("uuid", None)
    after_without_uuid.pop("uuid", None)
    if (
        before.get("uuid") is not None
        or not isinstance(after.get("uuid"), str)
        or before_without_uuid != after_without_uuid
        or before_body != after_body
    ):
        raise SupportableRepairRefusal("authority_refused")
    return BriefingRepairProposal(
        for_date=for_date,
        migration=migration,
        original_text=original,
        original_sha256=version,
        candidate_sha256=_sha256_text(migration.content),
    )


def prepare_repair_batch(
    *,
    vault_root: Path,
    vault_context: Any,
    companion_sources: tuple[str, ...],
    briefing_dates: tuple[date, ...],
    observed_at: str,
    revision: str,
    image_digest: str,
    selection_sha256: str,
) -> RepairBatch:
    """Freeze the exact reviewed target set without publishing private material."""

    if (
        len(companion_sources) != EXPECTED_COMPANION_COUNT
        or len(set(companion_sources)) != EXPECTED_COMPANION_COUNT
        or len(briefing_dates) != EXPECTED_BRIEFING_COUNT
        or len(set(briefing_dates)) != EXPECTED_BRIEFING_COUNT
    ):
        raise SupportableRepairRefusal("context_refused")
    batch = RepairBatch(
        revision=revision,
        image_digest=image_digest,
        selection_sha256=selection_sha256,
        companion=tuple(
            prepare_companion_continuity_repair(
                vault_root=vault_root,
                source_rel=source_rel,
                observed_at=observed_at,
            )
            for source_rel in companion_sources
        ),
        briefings=tuple(
            prepare_briefing_repair(
                vault_context=vault_context,
                for_date=for_date,
            )
            for for_date in briefing_dates
        ),
    )
    _validate_batch(batch)
    return batch


def commit_briefing_repair(
    proposal: BriefingRepairProposal,
    *,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> None:
    """Re-prove and delegate exactly one write to the composer migration seam."""

    fresh = prepare_briefing_repair(
        vault_context=vault_context,
        for_date=proposal.for_date,
    )
    if fresh != proposal:
        raise SupportableRepairRefusal("authority_refused")
    try:
        receipt = migrate_briefing_identity(
            vault_context=vault_context,
            for_date=proposal.for_date,
            write_guard=write_guard,
        )
    except Exception:
        raise SupportableRepairRefusal("write_refused") from None
    if receipt is None:
        raise SupportableRepairRefusal("readback_indeterminate")
    target = _vault_context_root(vault_context) / proposal.migration.note_rel_path
    _text, version = _regular_nofollow_text(target)
    if version != proposal.candidate_sha256:
        raise SupportableRepairRefusal("readback_indeterminate")


def _rollback_exact(
    *,
    target: Path,
    root: Path,
    expected_candidate_sha256: str,
    original_text: str,
    original_sha256: str,
    write_guard: WriteGuard,
) -> str:
    """Rollback only exact repair bytes; mismatch is preserved and indeterminate."""

    try:
        _current, current_sha256 = _regular_nofollow_text(target)
    except SupportableRepairRefusal:
        return "indeterminate"
    if current_sha256 != expected_candidate_sha256:
        return "indeterminate"
    try:
        write_note_from_absolute(
            target,
            original_text,
            vault_root=root,
            action=ACTION,
            write_guard=write_guard,
            expected_version=expected_candidate_sha256,
            writer_identity=WRITER_IDENTITY,
        )
        _restored, restored_sha256 = _regular_nofollow_text(target)
    except Exception:
        return "indeterminate"
    return "committed" if restored_sha256 == original_sha256 else "indeterminate"


def rollback_companion_continuity_repair(
    proposal: CompanionContinuityProposal,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> str:
    root = vault_root.expanduser().resolve(strict=True)
    return _rollback_exact(
        target=root / proposal.companion_rel,
        root=root,
        expected_candidate_sha256=proposal.candidate_sha256,
        original_text=proposal.original_text,
        original_sha256=proposal.original_sha256,
        write_guard=write_guard,
    )


def rollback_briefing_repair(
    proposal: BriefingRepairProposal,
    *,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> str:
    root = _vault_context_root(vault_context)
    return _rollback_exact(
        target=root / proposal.migration.note_rel_path,
        root=root,
        expected_candidate_sha256=proposal.candidate_sha256,
        original_text=proposal.original_text,
        original_sha256=proposal.original_sha256,
        write_guard=write_guard,
    )


def _validate_batch(batch: RepairBatch) -> None:
    if (
        _REVISION.fullmatch(batch.revision) is None
        or _IMAGE_DIGEST.fullmatch(batch.image_digest) is None
        or _SHA256.fullmatch(batch.selection_sha256) is None
        or len(batch.companion) != EXPECTED_COMPANION_COUNT
        or len(batch.briefings) != EXPECTED_BRIEFING_COUNT
        or len({item.source_rel for item in batch.companion}) != len(batch.companion)
        or len({item.for_date for item in batch.briefings}) != len(batch.briefings)
    ):
        raise SupportableRepairRefusal("context_refused")


def _validate_authority(batch: RepairBatch, authority: RepairAuthoritySnapshot) -> None:
    if (
        authority.revision != batch.revision
        or authority.image_digest != batch.image_digest
        or authority.selection_sha256 != batch.selection_sha256
        or any(type(value) is not bool for value in (
            authority.controller_unloaded,
            authority.write_guard_healthy,
            authority.writers_isolated,
            authority.owned_operation_fences_healthy,
        ))
        or not all((
            authority.controller_unloaded,
            authority.write_guard_healthy,
            authority.writers_isolated,
            authority.owned_operation_fences_healthy,
        ))
    ):
        raise SupportableRepairRefusal("authority_refused")


def _public_receipt(
    *, result: str, planned: int, repaired: int, refused: int, indeterminate: int,
) -> dict[str, Any]:
    return validate_public_receipt({
        "contract": RECEIPT_CONTRACT,
        "channel": "dev",
        "result": result,
        "planned_count": planned,
        "repaired_count": repaired,
        "refused_count": refused,
        "indeterminate_count": indeterminate,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    })


def validate_public_receipt(payload: Any) -> dict[str, Any]:
    """Accept only fixed counts/booleans; private material has no schema slot."""

    keys = {
        "contract", "channel", "result", "planned_count", "repaired_count",
        "refused_count", "indeterminate_count", "automatic_producer_started",
        "automatic_deployment_started",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        raise SupportableRepairRefusal("context_refused")
    if (
        payload["contract"] != RECEIPT_CONTRACT
        or payload["channel"] != "dev"
        or payload["result"] not in _RESULTS
        or any(type(payload[key]) is not int or payload[key] < 0 for key in (
            "planned_count", "repaired_count", "refused_count", "indeterminate_count",
        ))
        or payload["planned_count"] != (
            payload["repaired_count"]
            + payload["refused_count"]
            + payload["indeterminate_count"]
        )
        or payload["automatic_producer_started"] is not False
        or payload["automatic_deployment_started"] is not False
        or (payload["result"] == "committed" and (
            payload["refused_count"] or payload["indeterminate_count"]
        ))
        or (payload["result"] == "failed" and payload["indeterminate_count"])
        or (payload["result"] == "indeterminate" and not payload["indeterminate_count"])
    ):
        raise SupportableRepairRefusal("context_refused")
    return dict(payload)


def _classify_readback(target: Path, *, original: str, candidate: str) -> str:
    try:
        _text, current = _regular_nofollow_text(target)
    except SupportableRepairRefusal:
        return "indeterminate"
    if current == candidate:
        return "committed"
    if current == original:
        return "refused"
    return "indeterminate"


def run_supportable_repair_batch(
    batch: RepairBatch,
    *,
    effects: RepairEffects,
    vault_root: Path,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Run one exact private batch inside a host-owned fence; never replay internally."""

    _validate_batch(batch)
    root = vault_root.expanduser().resolve(strict=True)
    planned = len(batch.companion) + len(batch.briefings)
    repaired = refused = indeterminate = 0
    before: RepairAuthoritySnapshot | None = None
    try:
        with effects.owned_repair_fence():
            before = effects.read_repair_authority()
            _validate_authority(batch, before)
            for proposal in batch.companion:
                try:
                    commit_companion_continuity_repair(
                        proposal,
                        vault_root=root,
                        write_guard=write_guard,
                    )
                    outcome = "committed"
                except Exception:
                    outcome = _classify_readback(
                        root / proposal.companion_rel,
                        original=proposal.original_sha256,
                        candidate=proposal.candidate_sha256,
                    )
                repaired += outcome == "committed"
                refused += outcome == "refused"
                indeterminate += outcome == "indeterminate"
            for briefing_proposal in batch.briefings:
                target = root / briefing_proposal.migration.note_rel_path
                try:
                    commit_briefing_repair(
                        briefing_proposal,
                        vault_context=vault_context,
                        write_guard=write_guard,
                    )
                    outcome = "committed"
                except Exception:
                    outcome = _classify_readback(
                        target,
                        original=briefing_proposal.original_sha256,
                        candidate=briefing_proposal.candidate_sha256,
                    )
                repaired += outcome == "committed"
                refused += outcome == "refused"
                indeterminate += outcome == "indeterminate"
            after = effects.read_repair_authority()
            _validate_authority(batch, after)
            if after != before:
                indeterminate += repaired + refused
                repaired = 0
                refused = 0
    except Exception:
        if repaired or refused or indeterminate:
            indeterminate += repaired + refused
            repaired = 0
            refused = 0
        else:
            raise SupportableRepairRefusal(
                "authority_refused" if before is not None else "context_refused"
            ) from None
    result = "indeterminate" if indeterminate else ("failed" if refused else "committed")
    return _public_receipt(
        result=result,
        planned=planned,
        repaired=repaired,
        refused=refused,
        indeterminate=indeterminate,
    )


__all__ = [
    "ACTION",
    "BriefingRepairProposal",
    "CompanionContinuityProposal",
    "EXPECTED_BRIEFING_COUNT",
    "EXPECTED_COMPANION_COUNT",
    "RECEIPT_CONTRACT",
    "RepairAuthoritySnapshot",
    "RepairBatch",
    "SupportableRepairRefusal",
    "commit_briefing_repair",
    "commit_companion_continuity_repair",
    "prepare_briefing_repair",
    "prepare_companion_continuity_repair",
    "prepare_repair_batch",
    "rollback_briefing_repair",
    "rollback_companion_continuity_repair",
    "run_supportable_repair_batch",
    "validate_public_receipt",
]
