"""MVR-04: non-authoritative dimension grouping over registered vault bindings.

Task specification: `docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md`.
Owner contract: `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Dimensions`.

A dimension is an ordered, named list of `vault_binding_id` values stored in the instance
registry. That is the whole of it. The invariant this module exists to hold is negative:

    **A dimension never grants, upgrades, or implies authority.**

Three structural properties make that enforceable rather than merely documented.

1. **A dimension record has no authority-shaped field.** No action, no write class, no
   permission, no scope, no sphere, no principal. :data:`FORBIDDEN_DIMENSION_FIELDS` is
   asserted against the dataclass by
   `tests/integration/test_multi_vault_dimensions.py`, so adding one breaks a test.
2. **Resolution is a pure fan-out over the *same* GOV seam.** :meth:`VaultDimensionService
   .resolve` calls `app/governance/binding_authority.py` once per member with the decision
   inputs its *caller's* endpoint contract supplied. The dimension id is not one of them and
   never reaches GOV, so a verdict cannot depend on how a binding was reached. Resolving a
   dimension is therefore observably identical to naming its members explicitly --
   the equivalence a test pins directly.
3. **Resolution is all-or-nothing.** An unknown, stale, removed, or unauthorized member
   fails the whole resolution with a bounded member-specific error. There is no branch that
   returns an authorized subset, excludes a member, or substitutes another binding, so
   grouping cannot become a way to reach *some* of what you asked for.

Stored membership is deliberately allowed to go stale. A binding may be de-registered or
lose authorization while a dimension still lists it; that stored row is inert data, not a
grant. Authenticated instance administration may *inspect* and *repair* such membership --
:meth:`inspect`, :meth:`remove_member`, :meth:`delete` -- and that inspection is explicitly
not an ActiveContextSet and not a permission result. Additions and resolution still fail
closed.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.governance.binding_authority import (
    DENY_BINDING_UNKNOWN,
    BindingAuthorizationRequest,
    BindingAuthorizer,
    BindingVerdict,
)
from app.instance.vault_registry import (
    RegistryError,
    RegistrySnapshot,
    VaultRegistryStore,
)
from app.vault.active_context_v1 import DimensionFilter, PrincipalContext

#: Versioned durable schema for the registry's `dimensions` extension slot. MVR-01B
#: reserved that slot as opaque mechanical state; MVR-04 promotes it to a validated
#: first-class shape with its own producer, exactly as MVR-02 promoted the default.
DIMENSION_SCHEMA = "agentic-pkm.instance-vault-dimensions.v1"

#: Bounded so a dimension id can never look like a path, a host name, or a secret, and can
#: be echoed into an error or receipt without redaction.
_DIMENSION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

MAX_DISPLAY_NAME_LENGTH = 128
MAX_MEMBERS = 64
MAX_DIMENSIONS = 256

#: Names that must never appear on a dimension record. A dimension groups bindings; the
#: moment it carries one of these it has become a role or a policy object.
FORBIDDEN_DIMENSION_FIELDS = frozenset(
    {
        "action",
        "write_class",
        "required_permission",
        "permission",
        "permissions",
        "principal",
        "principal_id",
        "role",
        "roles",
        "scope",
        "sphere",
        "sphere_memberships",
        "confidentiality",
        "topology",
        "grants",
        "authority",
    }
)

#: Bounded, machine-readable failure reasons. A consumer branches on these; it never parses
#: prose, and none of them leaks a content root.
REASON_DIMENSION_UNKNOWN = "dimension_unknown"
REASON_MEMBER_UNREGISTERED = "dimension_member_unregistered"
REASON_MEMBER_UNAUTHORIZED = "dimension_member_unauthorized"


class VaultDimensionError(RegistryError):
    """Fail-closed dimension administration error."""


class DimensionResolutionError(VaultDimensionError):
    """One member failed, so the *whole* resolution failed.

    It carries the bounded reason and the offending opaque `vault_binding_id` so an operator
    can repair the dimension. It never carries a content root, a note, or a raw binding
    payload, and it never carries the authorized members that *did* pass -- exposing those
    would be the partial result the contract forbids.
    """

    def __init__(self, reason: str, *, dimension_id: str, vault_binding_id: str | None = None) -> None:
        detail = f"{reason}: dimension {dimension_id}"
        if vault_binding_id is not None:
            detail = f"{detail} member {vault_binding_id}"
        super().__init__(detail)
        self.reason = reason
        self.dimension_id = dimension_id
        self.vault_binding_id = vault_binding_id


@dataclass(frozen=True)
class VaultDimension:
    """One stored dimension.

    Every field here is grouping metadata. There is no authority field, and
    :data:`FORBIDDEN_DIMENSION_FIELDS` is asserted against this dataclass by test.

    `members` is ordered and the order is durable: it is the operator's stated order, not a
    ranking, a precedence, and never a settings-precedence input (see the lane's
    "binding iteration order is never settings precedence" invariant).
    """

    dimension_id: str
    display_name: str
    revision: int
    members: tuple[str, ...] = ()
    #: The last transactional membership repair applied by a registration removal, kept on
    #: the entry itself so the durable receipt is bounded by construction (one per
    #: dimension) rather than an ever-growing journal in instance state.
    last_repair: dict[str, Any] | None = None

    def redacted(self) -> dict[str, Any]:
        """A receipt-safe projection.

        Opaque server-minted ids and revisions only. No content root, no note content, and
        no raw binding payload ever passes through here.
        """

        payload: dict[str, Any] = {
            "dimension_id": self.dimension_id,
            "display_name": self.display_name,
            "dimension_revision": self.revision,
            "vault_binding_ids": list(self.members),
        }
        if self.last_repair is not None:
            payload["last_repair"] = copy.deepcopy(self.last_repair)
        return payload


@dataclass(frozen=True)
class ResolvedMember:
    """One resolved member: identity, provenance, and its own independent GOV verdict."""

    vault_binding_id: str
    binding_revision: int
    authorization_epoch: str
    vault_id: str | None = None
    local_instance_id: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class DimensionResolution:
    """The all-or-nothing result of resolving one dimension.

    It is a *list of bindings plus the revision they were read at*. It is not an
    ActiveContextSet, it is not a permission result, and it confers nothing: the caller
    still builds a snapshot through the normal MVR-03 resolver, which authorizes every
    binding again.
    """

    dimension_id: str
    dimension_revision: int
    members: tuple[ResolvedMember, ...]
    verdicts: tuple[BindingVerdict, ...] = ()

    @property
    def binding_ids(self) -> tuple[str, ...]:
        return tuple(member.vault_binding_id for member in self.members)

    def as_filter(self) -> DimensionFilter:
        return DimensionFilter(
            dimension_id=self.dimension_id, dimension_revision=self.dimension_revision
        )

    def redacted(self) -> dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "dimension_revision": self.dimension_revision,
            "vault_binding_ids": list(self.binding_ids),
        }


@dataclass(frozen=True)
class DimensionReceipt:
    """The redacted receipt every mutation emits, shared by the API and the CLI."""

    dimension_id: str
    changed: bool
    registry_revision: int
    dimension: VaultDimension | None = None
    previous_members: tuple[str, ...] = ()
    removed_members: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dimension_id": self.dimension_id,
            "changed": self.changed,
            "registry_revision": self.registry_revision,
            "previous_vault_binding_ids": list(self.previous_members),
        }
        if self.removed_members:
            payload["removed_vault_binding_ids"] = list(self.removed_members)
        if self.dimension is not None:
            payload.update(self.dimension.redacted())
        else:
            payload["deleted"] = True
        return payload


def _validate_dimension_id(value: str) -> str:
    normalized = (value or "").strip()
    if not _DIMENSION_ID_PATTERN.match(normalized):
        raise VaultDimensionError(
            "dimension_id must be 1-64 chars of [a-z0-9._-] starting alphanumeric"
        )
    return normalized


def _validate_display_name(value: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise VaultDimensionError("dimension display name is required")
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise VaultDimensionError(
            f"dimension display name exceeds {MAX_DISPLAY_NAME_LENGTH} characters"
        )
    if any(character < " " or character == "\x7f" for character in normalized):
        raise VaultDimensionError("dimension display name cannot contain control characters")
    return normalized


def _validate_members(members: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for raw in members:
        member = (raw or "").strip()
        if not member:
            raise VaultDimensionError("a dimension member must be a vault_binding_id")
        if member in ordered:
            raise VaultDimensionError(f"duplicate dimension member: {member}")
        ordered.append(member)
    if len(ordered) > MAX_MEMBERS:
        raise VaultDimensionError(f"a dimension holds at most {MAX_MEMBERS} members")
    return tuple(ordered)


def parse_dimensions(extensions: Mapping[str, Any] | None) -> dict[str, VaultDimension]:
    """Read the durable dimension set from the registry's extension slot.

    An absent or empty slot is an empty dimension set -- a pre-MVR-04 registry is a valid
    registry with no dimensions, not a broken one. A slot carrying a *different* schema is
    refused rather than reinterpreted: MVR-01B reserved this key as opaque mechanical
    state, and silently reading foreign content as membership is exactly the "guessing
    membership" the spec forbids.
    """

    raw = (extensions or {}).get("dimensions")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise VaultDimensionError("registry dimensions state must be a mapping")
    if not raw:
        return {}
    if raw.get("schema") != DIMENSION_SCHEMA:
        raise VaultDimensionError(
            "registry dimensions state carries an unsupported schema; "
            "explicit repair is required before dimension administration"
        )
    entries = raw.get("entries") or {}
    if not isinstance(entries, dict):
        raise VaultDimensionError("registry dimension entries must be a mapping")
    parsed: dict[str, VaultDimension] = {}
    for key, value in entries.items():
        dimension_id = _validate_dimension_id(str(key))
        if not isinstance(value, dict):
            raise VaultDimensionError(f"dimension {dimension_id} must be a mapping")
        revision = value.get("revision")
        if not isinstance(revision, int) or revision < 1:
            raise VaultDimensionError(f"dimension {dimension_id} revision must be a positive integer")
        raw_members = value.get("members") or []
        if not isinstance(raw_members, list):
            raise VaultDimensionError(f"dimension {dimension_id} members must be a list")
        last_repair = value.get("lastRepair")
        if last_repair is not None and not isinstance(last_repair, dict):
            raise VaultDimensionError(f"dimension {dimension_id} lastRepair must be a mapping")
        parsed[dimension_id] = VaultDimension(
            dimension_id=dimension_id,
            display_name=_validate_display_name(str(value.get("displayName") or dimension_id)),
            revision=revision,
            members=_validate_members([str(member) for member in raw_members]),
            last_repair=copy.deepcopy(last_repair) if last_repair is not None else None,
        )
    return parsed


def serialize_dimensions(dimensions: Mapping[str, VaultDimension]) -> dict[str, Any]:
    """Render the durable extension payload for a validated dimension set."""

    return {
        "schema": DIMENSION_SCHEMA,
        "entries": {
            dimension_id: {
                "displayName": dimension.display_name,
                "revision": dimension.revision,
                "members": list(dimension.members),
                **(
                    {"lastRepair": copy.deepcopy(dimension.last_repair)}
                    if dimension.last_repair is not None
                    else {}
                ),
            }
            for dimension_id, dimension in sorted(dimensions.items())
        },
    }


def repair_dimensions_for_removed_binding(
    extensions: dict[str, Any],
    *,
    vault_binding_id: str,
    registry_revision: int,
) -> tuple[str, ...]:
    """Strip one removed binding from every dimension, in place, inside a caller's lock.

    This is the transactional membership-repair hook MVR-04 installs in the shared registry
    service. The caller must already hold the registry writer lock and must be committing
    the registration removal in the *same* transaction, so a dangling member can never be
    observed between the two writes.

    Remaining member order is preserved exactly: repair removes one entry from an ordered
    list, it does not rebuild the list. Each affected dimension records a bounded repair
    receipt and advances its own revision, so a consumer holding an older dimension
    revision can tell that membership moved underneath it.

    Returns the ids of the dimensions that were repaired.
    """

    raw = extensions.get("dimensions")
    if not isinstance(raw, dict) or raw.get("schema") != DIMENSION_SCHEMA:
        # Nothing MVR-04 wrote is present. A foreign or absent slot is left untouched
        # rather than reinterpreted: repair never guesses membership.
        return ()
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return ()
    repaired: list[str] = []
    for dimension_id, value in entries.items():
        if not isinstance(value, dict):
            continue
        members = value.get("members")
        if not isinstance(members, list) or vault_binding_id not in members:
            continue
        value["members"] = [member for member in members if member != vault_binding_id]
        revision = value.get("revision")
        value["revision"] = (revision if isinstance(revision, int) and revision >= 1 else 1) + 1
        value["lastRepair"] = {
            "reason": "registration_removed",
            "removedVaultBindingId": vault_binding_id,
            "registryRevision": registry_revision,
        }
        repaired.append(str(dimension_id))
    return tuple(sorted(repaired))


class VaultDimensionService:
    """The one locked service behind the authenticated API and the headless CLI.

    Both production producers converge here, so they share one durable state, one
    validation path, and one redacted receipt. Like the MVR-02 default service it
    *receives* the sealed storage-mutation capability rather than holding it; constructed
    without one it is a read-only view whose mutators fail closed.
    """

    def __init__(
        self,
        store: VaultRegistryStore,
        *,
        capability: Any = None,
        emit_event: Any = None,
    ) -> None:
        self._store = store
        self._capability = capability
        self._emit_event = emit_event

    @property
    def store(self) -> VaultRegistryStore:
        return self._store

    # -- reads ---------------------------------------------------------------------

    def list(self) -> tuple[VaultDimension, ...]:
        """Stored membership, in stable id order.

        This is registry administration, not context resolution. It reports what is
        *stored*, including members that are stale or unauthorized, precisely so an
        operator can see and repair them. It is not an ActiveContextSet and not a
        permission result.
        """

        dimensions = parse_dimensions(self._store.load().extensions)
        return tuple(dimensions[key] for key in sorted(dimensions))

    def inspect(self, dimension_id: str) -> VaultDimension:
        target = _validate_dimension_id(dimension_id)
        dimensions = parse_dimensions(self._store.load().extensions)
        dimension = dimensions.get(target)
        if dimension is None:
            raise DimensionResolutionError(REASON_DIMENSION_UNKNOWN, dimension_id=target)
        return dimension

    def resolve(
        self,
        dimension_id: str,
        *,
        principal: PrincipalContext,
        action: str,
        write_class: str,
        required_permission: str,
        authorizer: BindingAuthorizer,
        snapshot: RegistrySnapshot | None = None,
    ) -> DimensionResolution:
        """Resolve one stored dimension into explicit, independently authorized bindings.

        `action`, `write_class`, and `required_permission` are the *caller's* GOV decision
        inputs for this call, derived from its server-owned endpoint/command contract. They
        are passed straight through. The dimension id is deliberately **not** among them:
        it never reaches GOV, so no verdict can differ because a binding was reached
        through a group.

        All-or-nothing, by construction: the first unknown, stale, removed, or unauthorized
        member raises. There is no `continue`, no partial accumulation returned to a
        caller, and no substitution.
        """

        target = _validate_dimension_id(dimension_id)
        current = snapshot if snapshot is not None else self._store.load()
        dimensions = parse_dimensions(current.extensions)
        dimension = dimensions.get(target)
        if dimension is None:
            raise DimensionResolutionError(REASON_DIMENSION_UNKNOWN, dimension_id=target)

        members: list[ResolvedMember] = []
        verdicts: list[BindingVerdict] = []
        for binding_id in dimension.members:
            # GOV is asked about every member *first* and unconditionally, matching the
            # MVR-03 resolver: a missing registry fact is put to GOV rather than
            # short-circuited, so the deny path stays the single place a member is
            # refused. Nothing about the dimension is passed in -- only the binding and
            # the caller's own decision inputs.
            verdict = authorizer.authorize(
                BindingAuthorizationRequest(
                    principal=principal,
                    vault_binding_id=binding_id,
                    action=action,
                    write_class=write_class,
                    required_permission=required_permission,
                )
            )
            if not verdict.allowed:
                # The whole resolution fails; members already authorized are discarded
                # with it. `binding_unknown` is the shipped policy's answer for a stale or
                # removed member, so it keeps its own bounded reason.
                raise DimensionResolutionError(
                    REASON_MEMBER_UNREGISTERED
                    if verdict.reason == DENY_BINDING_UNKNOWN
                    else REASON_MEMBER_UNAUTHORIZED,
                    dimension_id=target,
                    vault_binding_id=binding_id,
                )
            registration = current.registrations.get(binding_id)
            if registration is None:
                # GOV allowed a binding this registry snapshot does not hold. Refuse
                # rather than fabricate provenance for it.
                raise DimensionResolutionError(
                    REASON_MEMBER_UNREGISTERED,
                    dimension_id=target,
                    vault_binding_id=binding_id,
                )
            verdicts.append(verdict)
            members.append(
                ResolvedMember(
                    vault_binding_id=binding_id,
                    binding_revision=_binding_revision(current, binding_id),
                    authorization_epoch=verdict.epoch,
                    vault_id=registration.vault_id,
                    local_instance_id=registration.local_instance_id,
                    label=registration.vault_name,
                )
            )
        return DimensionResolution(
            dimension_id=target,
            dimension_revision=dimension.revision,
            members=tuple(members),
            verdicts=tuple(verdicts),
        )

    # -- mutations -----------------------------------------------------------------

    def create(
        self, dimension_id: str, *, display_name: str, members: Sequence[str] = ()
    ) -> DimensionReceipt:
        target = _validate_dimension_id(dimension_id)
        name = _validate_display_name(display_name)
        proposed = _validate_members(members)
        current, dimensions = self._load()
        if target in dimensions:
            raise VaultDimensionError(f"dimension already exists: {target}")
        if len(dimensions) >= MAX_DIMENSIONS:
            raise VaultDimensionError(f"an instance holds at most {MAX_DIMENSIONS} dimensions")
        self._require_registered(current, proposed)
        dimensions[target] = VaultDimension(
            dimension_id=target, display_name=name, revision=1, members=proposed
        )
        return self._commit(current, dimensions, dimension_id=target, previous_members=())

    def rename(self, dimension_id: str, *, display_name: str) -> DimensionReceipt:
        target = _validate_dimension_id(dimension_id)
        name = _validate_display_name(display_name)
        current, dimensions = self._load()
        existing = self._require_dimension(dimensions, target)
        if existing.display_name == name:
            return DimensionReceipt(
                dimension_id=target,
                changed=False,
                registry_revision=current.revision,
                dimension=existing,
                previous_members=existing.members,
            )
        dimensions[target] = VaultDimension(
            dimension_id=target,
            display_name=name,
            revision=existing.revision + 1,
            members=existing.members,
            last_repair=existing.last_repair,
        )
        return self._commit(
            current, dimensions, dimension_id=target, previous_members=existing.members
        )

    def set_members(self, dimension_id: str, members: Sequence[str]) -> DimensionReceipt:
        """Replace membership wholesale.

        Every proposed member must be a current registration. A replacement is an
        *addition* path, so it fails closed rather than accepting a stale id: only the
        explicit repair commands below may clear one.
        """

        target = _validate_dimension_id(dimension_id)
        proposed = _validate_members(members)
        current, dimensions = self._load()
        existing = self._require_dimension(dimensions, target)
        self._require_registered(current, proposed)
        if existing.members == proposed:
            return DimensionReceipt(
                dimension_id=target,
                changed=False,
                registry_revision=current.revision,
                dimension=existing,
                previous_members=existing.members,
            )
        dimensions[target] = VaultDimension(
            dimension_id=target,
            display_name=existing.display_name,
            revision=existing.revision + 1,
            members=proposed,
            last_repair=existing.last_repair,
        )
        return self._commit(
            current, dimensions, dimension_id=target, previous_members=existing.members
        )

    def remove_member(self, dimension_id: str, vault_binding_id: str) -> DimensionReceipt:
        """Instance-authorized repair: drop one stored member without resolving it.

        This is the path that lets an operator clear a stale or unauthorized row. It
        deliberately does **not** authorize or even look up the member: requiring a
        resolution here would make an unrepairable dimension permanent, and resolving a
        member in order to delete it would be the partial-resolution the contract forbids.
        Remaining order is preserved.
        """

        target = _validate_dimension_id(dimension_id)
        member = (vault_binding_id or "").strip()
        if not member:
            raise VaultDimensionError("vault_binding_id is required")
        current, dimensions = self._load()
        existing = self._require_dimension(dimensions, target)
        if member not in existing.members:
            raise VaultDimensionError(
                f"binding is not a member of dimension {target}: {member}"
            )
        dimensions[target] = VaultDimension(
            dimension_id=target,
            display_name=existing.display_name,
            revision=existing.revision + 1,
            members=tuple(item for item in existing.members if item != member),
            last_repair=existing.last_repair,
        )
        return self._commit(
            current,
            dimensions,
            dimension_id=target,
            previous_members=existing.members,
            removed_members=(member,),
        )

    def delete(self, dimension_id: str) -> DimensionReceipt:
        """Delete a dimension. Registrations and vault content are untouched.

        Deleting the *grouping* cannot delete the *things grouped*: this method never
        reaches a registration, a content root, or the ownership ledger. That is structural
        here, not a promise -- the only state it writes is the dimension extension slot.
        """

        target = _validate_dimension_id(dimension_id)
        current, dimensions = self._load()
        existing = self._require_dimension(dimensions, target)
        del dimensions[target]
        return self._commit(
            current,
            dimensions,
            dimension_id=target,
            previous_members=existing.members,
            removed_members=existing.members,
            deleted=True,
        )

    # -- internals -----------------------------------------------------------------

    def _load(self) -> tuple[RegistrySnapshot, dict[str, VaultDimension]]:
        current = self._store.load()
        return current, parse_dimensions(current.extensions)

    def _require_dimension(
        self, dimensions: Mapping[str, VaultDimension], dimension_id: str
    ) -> VaultDimension:
        dimension = dimensions.get(dimension_id)
        if dimension is None:
            raise DimensionResolutionError(REASON_DIMENSION_UNKNOWN, dimension_id=dimension_id)
        return dimension

    def _require_registered(
        self, snapshot: RegistrySnapshot, members: Iterable[str]
    ) -> None:
        unknown = [
            member for member in members if member not in snapshot.registrations
        ]
        if unknown:
            raise DimensionResolutionError(
                REASON_MEMBER_UNREGISTERED,
                dimension_id="<proposed>",
                vault_binding_id=sorted(unknown)[0],
            )

    def _commit(
        self,
        current: RegistrySnapshot,
        dimensions: Mapping[str, VaultDimension],
        *,
        dimension_id: str,
        previous_members: tuple[str, ...],
        removed_members: tuple[str, ...] = (),
        deleted: bool = False,
    ) -> DimensionReceipt:
        updated = self._store.set_dimension_state(
            serialize_dimensions(dimensions),
            expected_revision=current.revision,
            _capability=self._capability,
        )
        receipt = DimensionReceipt(
            dimension_id=dimension_id,
            changed=True,
            registry_revision=updated.revision,
            dimension=None if deleted else parse_dimensions(updated.extensions)[dimension_id],
            previous_members=previous_members,
            removed_members=removed_members,
        )
        if self._emit_event is not None:
            self._emit_event(receipt)
        return receipt


DIMENSION_MUTATION_EVENT_VERSION = 1
_DIMENSION_MUTATION_FINGERPRINT = "instance-vault-dimension-changed-v1"


def emit_dimension_mutation_event(receipt: DimensionReceipt) -> str:
    """Publish exactly one versioned, redacted dimension-mutation event.

    Only opaque ids, counts, and revisions leave the instance: no display name, no content
    root, no note content, and no raw binding payload. Keyed on the registry revision so a
    crash-retry of the same logical mutation cannot produce a second row.

    Durability classification matches MVR-02's default mutation (`required_db=False`): the
    committed registry revision written under the lock is the authority, and background
    supervisors reconcile durable revisions rather than event delivery, so a skipped mirror
    on an instance with no configured Postgres is survivable. Requiring the DB here would
    make the headless CLI unusable on a bare instance.
    """

    from app.events.models import new_event
    from app.events.types import INSTANCE_VAULT_DIMENSION_CHANGED
    from app.services.outbox import derive_idempotency_key, write_outbox_event

    payload = {
        "event_version": DIMENSION_MUTATION_EVENT_VERSION,
        "registry_revision": receipt.registry_revision,
        "dimension_id": receipt.dimension_id,
        "dimension_revision": (
            None if receipt.dimension is None else receipt.dimension.revision
        ),
        "deleted": receipt.dimension is None,
        "member_count": 0 if receipt.dimension is None else len(receipt.dimension.members),
    }
    idempotency_key = derive_idempotency_key(
        INSTANCE_VAULT_DIMENSION_CHANGED,
        f"{receipt.dimension_id}:{receipt.registry_revision}",
        _DIMENSION_MUTATION_FINGERPRINT,
    )
    event = new_event(
        event_type=INSTANCE_VAULT_DIMENSION_CHANGED,
        payload=payload,
        source="instance.vault_dimensions",
    )
    return write_outbox_event(event, idempotency_key=idempotency_key, required_db=False)


def _binding_revision(snapshot: RegistrySnapshot, vault_binding_id: str) -> int:
    """The same per-binding revision rule MVR-03 uses; imported lazily to avoid a cycle."""

    from app.instance.active_context_service import binding_revision_for

    return binding_revision_for(snapshot, vault_binding_id)


__all__ = [
    "DIMENSION_MUTATION_EVENT_VERSION",
    "DIMENSION_SCHEMA",
    "FORBIDDEN_DIMENSION_FIELDS",
    "MAX_DIMENSIONS",
    "MAX_DISPLAY_NAME_LENGTH",
    "MAX_MEMBERS",
    "REASON_DIMENSION_UNKNOWN",
    "REASON_MEMBER_UNAUTHORIZED",
    "REASON_MEMBER_UNREGISTERED",
    "DimensionReceipt",
    "DimensionResolution",
    "DimensionResolutionError",
    "ResolvedMember",
    "VaultDimension",
    "VaultDimensionError",
    "VaultDimensionService",
    "emit_dimension_mutation_event",
    "parse_dimensions",
    "repair_dimensions_for_removed_binding",
    "serialize_dimensions",
]
