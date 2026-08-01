"""TTL-bound session selection store and the MVR-03 active-context resolver.

`docs/MULTI_VAULT_RUNTIME/VERSION_ACTIVE_CONTEXT_SELECTION.md`.

Two objects live here:

`ContextSelectionStore`
    An **ephemeral**, TTL-bound, in-process map keyed by a high-entropy opaque server-minted
    `context_selection_id`. V1 session selection is deliberately not durable: after expiry,
    process restart, or session loss an *omitted* selection resolves the instance default or
    no-vault, while a *presented* stale id returns an explicit reselection-required error.
    This is not an unrelated chat/canvas session map and no durable human-artifact store is
    reused for it.

`ActiveContextSelectionResolver`
    Turns explicit selection inputs into one immutable `ActiveContextSetV1`. It never
    consults mutable process-global selection state -- it has no reference to
    `VaultManager` at all, which is what makes
    `test_selection_resolution_is_immutable_and_global_free` a structural test rather than a
    behavioural hope.

What the selection id is, precisely: in the current single-user product it is an **expiring
bearer capability**, not a claim of multi-user identity. Every operation also passes the
existing #2223 Companion authentication gate, and the server independently resolves the
principal from the auth/GOV boundary. Possession of a different selection id is required to
reach a different session's selection.

What the selection record is **not**: it stores no operation authority. There is no action,
no write class, and no permission field. Each later request derives those independently from
the server-owned endpoint/command contract and passes them to GOV as separate decision
inputs.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.governance.binding_authority import (
    BindingAuthorizationError,
    BindingAuthorizationRequest,
    BindingAuthorizer,
    BindingVerdict,
    snapshot_authorization_epoch,
)
from app.vault.active_context_v1 import (
    ActiveContextBinding,
    ActiveContextSetV1,
    DimensionFilter,
    PrincipalContext,
    WorkspaceState,
    selection_capability_digest,
)

#: 256 bits of CSPRNG entropy. The raw value leaves the server exactly once, in the create
#: response body; it is never logged, receipted, or used as cache-key material.
_SELECTION_ID_BYTES = 32

DEFAULT_SELECTION_TTL_SECONDS = 30 * 60

SELECTION_PROVENANCE_SESSION = "session_selection"
SELECTION_PROVENANCE_INSTANCE_DEFAULT = "instance_default"
SELECTION_PROVENANCE_NO_VAULT = "no_vault"

#: The retained-session and one-request-override carriers reserved for MVR-05B. They are
#: named here so the store and the later ingress contract cannot drift into two vocabularies,
#: but MVR-03 ships no production request-path dependency on them.
HEADER_ACTIVE_CONTEXT_SESSION = "X-Active-Context-Session"
HEADER_ACTIVE_CONTEXT_OVERRIDE = "X-Active-Context-Override"


class ContextSelectionError(RuntimeError):
    """Base class for fail-closed selection errors."""


class ReselectionRequiredError(ContextSelectionError):
    """An explicitly presented selection id is expired, unknown, or pre-restart.

    It never falls through to a default, to last-active state, or to another session. The
    message deliberately contains no bearer material.
    """

    code = "reselection_required"

    def __init__(self, reason: str) -> None:
        super().__init__(f"{self.code}: {reason}")
        self.reason = reason


class SelectionPrincipalMismatchError(ContextSelectionError):
    """The bearer resolved, but to a different principal or instance."""

    code = "selection_principal_mismatch"

    def __init__(self) -> None:
        super().__init__(f"{self.code}: selection is bound to another principal or instance")


@dataclass(frozen=True)
class ContextSelectionRecord:
    """One session selection.

    It is bound to the server-resolved principal, the separate instance identity, the
    explicit workspace/no-workspace state, the selected binding set, and the validated
    cognitive dimensions. It is *not* bound to an endpoint permission or action.

    Note there is no raw-bearer field: the store keys on the raw id but the record itself
    carries only the non-reversible digest, so a record can be logged or receipted safely.
    """

    context_id: str
    generation: int
    selection_capability_digest: str
    principal: PrincipalContext
    instance_identity: str
    workspace: WorkspaceState
    scope: str
    sphere_memberships: tuple[str, ...]
    situated_identity: str | None
    binding_ids: tuple[str, ...]
    created_at: float
    expires_at: float
    #: MVR-04 provenance when the binding set above came from a stored dimension. The
    #: *bindings* remain the selection: this records which dimension produced them and at
    #: which revision, so a later resolution can tell that membership moved. It is never
    #: re-expanded, so it cannot widen the selection, and it stores no authority.
    dimension_filter: DimensionFilter | None = None

    def redacted(self) -> dict[str, object]:
        """A receipt-safe projection. The raw bearer is structurally absent."""

        return {
            "context_id": self.context_id,
            "generation": self.generation,
            "selection_capability_digest": self.selection_capability_digest,
            "principal_kind": self.principal.principal_kind,
            "principal_id": self.principal.principal_id,
            "instance_identity": self.instance_identity,
            "workspace": self.workspace.cache_component(),
            "scope": self.scope,
            "sphere_memberships": list(self.sphere_memberships),
            "situated_identity": self.situated_identity,
            "vault_binding_ids": list(self.binding_ids),
            "dimension_id": (
                None if self.dimension_filter is None else self.dimension_filter.dimension_id
            ),
            "dimension_revision": (
                None
                if self.dimension_filter is None
                else self.dimension_filter.dimension_revision
            ),
            "expires_at": self.expires_at,
        }


class ContextSelectionStore:
    """The single TTL-bound session-selection store.

    One store, reusable by the later MVR-05 ingress contract: a retained client session
    sends its bearer as `X-Active-Context-Session`, and a caller needing a one-request
    override mints a separately authorized selection and sends it as
    `X-Active-Context-Override`. No second store is invented for the override.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_SELECTION_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._clock = clock
        self._records: dict[str, ContextSelectionRecord] = {}
        #: FastAPI runs sync handlers in a thread pool, so two requests can execute against
        #: this process-wide store concurrently. Individual dict operations are atomic under
        #: the GIL, but every mutation here is a read-modify-write: without this lock a PUT
        #: could read a record, lose a race to a concurrent DELETE, and then write the
        #: replacement back -- resurrecting a bearer that was reported cleared. Two
        #: concurrent PUTs could likewise both publish the same generation.
        self._lock = threading.RLock()
        #: A fresh epoch per store instance. A process restart builds a new store, so a
        #: pre-restart bearer cannot resolve even if its raw value were replayed.
        self._process_epoch = uuid.uuid4().hex

    @property
    def process_epoch(self) -> str:
        return self._process_epoch

    def _prune(self) -> None:
        """Caller must hold `self._lock`."""

        now = self._clock()
        expired = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired:
            del self._records[key]

    def create(
        self,
        *,
        principal: PrincipalContext,
        instance_identity: str,
        workspace: WorkspaceState,
        scope: str,
        sphere_memberships: Sequence[str],
        situated_identity: str | None,
        binding_ids: Sequence[str],
        dimension_filter: DimensionFilter | None = None,
    ) -> tuple[str, ContextSelectionRecord]:
        """Mint a selection and return `(raw_selection_id, record)`.

        The raw id is returned to the creating caller and then forgotten by every other
        surface; only the digest is retained anywhere else.
        """

        raw_id = secrets.token_urlsafe(_SELECTION_ID_BYTES)
        now = self._clock()
        record = ContextSelectionRecord(
            context_id=f"ctx_{uuid.uuid4().hex}",
            generation=1,
            selection_capability_digest=selection_capability_digest(raw_id),
            principal=principal,
            instance_identity=instance_identity,
            workspace=workspace,
            scope=scope,
            sphere_memberships=tuple(sphere_memberships),
            situated_identity=situated_identity,
            binding_ids=tuple(binding_ids),
            created_at=now,
            expires_at=now + self._ttl,
            dimension_filter=dimension_filter,
        )
        with self._lock:
            self._prune()
            self._records[raw_id] = record
        return raw_id, record

    def _require(
        self,
        raw_id: str,
        *,
        principal: PrincipalContext,
        instance_identity: str,
    ) -> ContextSelectionRecord:
        """Caller must hold `self._lock`."""

        self._prune()
        record = self._records.get(raw_id)
        if record is None:
            # Expired, unknown, and pre-restart collapse to one indistinguishable answer.
            # Distinguishing them would turn the store into a bearer oracle.
            raise ReselectionRequiredError("selection is expired, unknown, or pre-restart")
        if (
            record.principal.principal_id != principal.principal_id
            or record.instance_identity != instance_identity
        ):
            raise SelectionPrincipalMismatchError()
        return record

    def inspect(
        self,
        raw_id: str,
        *,
        principal: PrincipalContext,
        instance_identity: str,
    ) -> ContextSelectionRecord:
        with self._lock:
            return self._require(
                raw_id, principal=principal, instance_identity=instance_identity
            )

    def replace_bindings(
        self,
        raw_id: str,
        *,
        principal: PrincipalContext,
        instance_identity: str,
        binding_ids: Sequence[str],
        dimension_filter: DimensionFilter | None = None,
    ) -> ContextSelectionRecord:
        """Switch a session's bindings, atomically advancing its generation.

        The previous record object is never mutated. In-flight work already holding a
        snapshot keeps that snapshot; only subsequent resolutions see the new generation.
        Only this session's generation moves -- no other session and no instance default is
        touched.
        """

        with self._lock:
            current = self._require(
                raw_id, principal=principal, instance_identity=instance_identity
            )
            updated = replace(
                current,
                generation=current.generation + 1,
                binding_ids=tuple(binding_ids),
                # A replace always restates provenance. Carrying a previous dimension
                # filter across an explicit binding replacement would leave the record
                # claiming a group it no longer reflects.
                dimension_filter=dimension_filter,
            )
            self._records[raw_id] = updated
            return updated

    def clear(
        self,
        raw_id: str,
        *,
        principal: PrincipalContext,
        instance_identity: str,
    ) -> None:
        with self._lock:
            self._require(raw_id, principal=principal, instance_identity=instance_identity)
            self._records.pop(raw_id, None)

    def invalidate_digest(self, digest: str) -> None:
        """Drop every selection matching a capability digest (deny-verdict path)."""

        with self._lock:
            for key, record in list(self._records.items()):
                if record.selection_capability_digest == digest:
                    del self._records[key]

    def __len__(self) -> int:
        with self._lock:
            self._prune()
            return len(self._records)


@dataclass(frozen=True)
class CacheInvalidationDescriptor:
    """What a resolver rotation invalidates, so a consumer can act before the next lookup."""

    context_id: str
    previous_generation: int
    generation: int
    reason: str
    invalidated_identity: str


@dataclass(frozen=True)
class ResolutionResult:
    """One immutable snapshot plus the invalidation it implies for prior cached work."""

    snapshot: ActiveContextSetV1
    invalidation: CacheInvalidationDescriptor | None = None


@dataclass(frozen=True)
class BindingFact:
    """Current registry truth for one binding, as the resolver sees it."""

    vault_binding_id: str
    binding_revision: int
    vault_id: str | None = None
    local_instance_id: str | None = None
    label: str | None = None
    available: bool = True


class ActiveContextSelectionResolver:
    """Resolve explicit selection inputs into one immutable snapshot.

    Deliberately global-free: it holds a binding-fact lookup, a GOV authorizer, and the
    instance identity. It never imports or reads `VaultManager`, `get_vault_manager`, or any
    other mutable process-global selection state.
    """

    def __init__(
        self,
        *,
        binding_facts: Callable[[], dict[str, BindingFact]],
        registry_revision: Callable[[], int],
        authorizer: BindingAuthorizer,
        instance_identity: str,
        invalidate_selection: Callable[[str], None] | None = None,
    ) -> None:
        #: Called with the capability digest when GOV denies a member binding, so the denied
        #: selection is dropped rather than left resolvable. `ContextSelectionStore
        #: .invalidate_digest` is the production implementation.
        self._invalidate = invalidate_selection or (lambda _digest: None)
        self._binding_facts = binding_facts
        self._registry_revision = registry_revision
        self._authorizer = authorizer
        self._instance_identity = instance_identity
        #: (context_id, generation) -> the underlying identity last seen at that generation.
        #: Keying on the generation as well as the context is what separates the two kinds
        #: of change: a deliberate session switch mints a new generation and therefore a new
        #: key (the store already accounted for it, so the resolver must not rotate again),
        #: while drift *underneath* an unchanged generation hits an existing key and rotates.
        self._last_identity: dict[tuple[str, int], str] = {}
        #: context_id -> how many times underlying revision/authority drift has rotated this
        #: context. Added to the selection's own generation so the emitted generation is
        #: monotonic per context: a rotation can never be undone by a later steady-state
        #: resolution, which is what "monotonic generation" has to mean in practice.
        self._rotations: dict[str, int] = {}

    def resolve(
        self,
        *,
        selection: ContextSelectionRecord | None,
        principal: PrincipalContext,
        action: str,
        write_class: str,
        required_permission: str,
        default_binding_id: str | None = None,
    ) -> ResolutionResult:
        """Produce one snapshot for one request.

        `action`, `write_class`, and `required_permission` are the caller's separate GOV
        decision inputs for *this* call. They are never read from the selection, never
        stored, and never written into WSP `scope` -- which is exactly what lets the same
        selection serve a separately authorized read and a separately authorized write.
        """

        facts = self._binding_facts()
        registry_revision = self._registry_revision()

        if selection is not None:
            binding_ids = selection.binding_ids
            context_id = selection.context_id
            generation = selection.generation + self._rotations.get(selection.context_id, 0)
            workspace = selection.workspace
            scope = selection.scope
            spheres = selection.sphere_memberships
            situated = selection.situated_identity
            digest: str | None = selection.selection_capability_digest
            provenance = SELECTION_PROVENANCE_SESSION
            expires_at: float | None = selection.expires_at
            dimension_filter: DimensionFilter | None = selection.dimension_filter
        else:
            binding_ids = (default_binding_id,) if default_binding_id else ()
            context_id = f"ctx_default_{self._instance_identity}"
            generation = 1 + self._rotations.get(context_id, 0)
            workspace = WorkspaceState.none()
            scope = "default"
            spheres = ()
            situated = None
            digest = None
            provenance = (
                SELECTION_PROVENANCE_INSTANCE_DEFAULT
                if default_binding_id
                else SELECTION_PROVENANCE_NO_VAULT
            )
            expires_at = None
            # The instance default is a single explicit binding. A dimension is never a
            # default and never seeds one, so this branch has no filter by construction.
            dimension_filter = None

        bindings: list[ActiveContextBinding] = []
        verdicts: list[BindingVerdict] = []
        degraded_reason: str | None = None

        for binding_id in binding_ids:
            fact = facts.get(binding_id)
            # GOV is asked about every member independently. A missing registry fact is
            # still put to GOV rather than short-circuited, so the deny path is the single
            # place an unknown binding is refused.
            verdict = self._authorizer.authorize(
                BindingAuthorizationRequest(
                    principal=principal,
                    vault_binding_id=binding_id,
                    action=action,
                    write_class=write_class,
                    required_permission=required_permission,
                )
            )
            verdicts.append(verdict)
            if not verdict.allowed:
                # A deny invalidates the selection outright: the resolver drops it from the
                # store and attaches the cache-invalidation descriptor to the error, so no
                # caller has to remember to invalidate and no ActiveContextSet containing the
                # denied binding is reissued.
                if digest is not None:
                    self._invalidate(digest)
                error = BindingAuthorizationError(verdict)
                error.invalidation = CacheInvalidationDescriptor(  # type: ignore[attr-defined]
                    context_id=context_id,
                    previous_generation=generation,
                    generation=generation,
                    reason=f"binding_denied:{verdict.reason}",
                    invalidated_identity=self._last_identity.get(
                        (context_id, generation), ""
                    ),
                )
                self._last_identity.pop((context_id, generation), None)
                raise error
            if fact is None:
                degraded_reason = "binding_unavailable"
                continue
            if not fact.available:
                degraded_reason = "binding_unavailable"
            bindings.append(
                ActiveContextBinding(
                    vault_binding_id=fact.vault_binding_id,
                    binding_revision=fact.binding_revision,
                    authorization_epoch=verdict.epoch,
                    vault_id=fact.vault_id,
                    local_instance_id=fact.local_instance_id,
                    label=fact.label,
                )
            )

        epoch = snapshot_authorization_epoch(tuple(verdicts))
        snapshot = ActiveContextSetV1(
            context_id=context_id,
            generation=generation,
            workspace=workspace,
            scope=scope,
            sphere_memberships=spheres,
            situated_identity=situated,
            principal_context=principal,
            instance_identity=self._instance_identity,
            source_bindings=tuple(bindings),
            registry_revision=registry_revision,
            authorization_epoch=epoch,
            selection_provenance=provenance,
            posture="degraded" if degraded_reason else "healthy",
            degraded_reason=degraded_reason,
            selection_capability_digest=digest,
            expires_at=expires_at,
            dimension_filter=dimension_filter,
        )

        # Revision / verdict drift detection. The identity excludes `generation` on
        # purpose: we are asking "did anything *underneath* this generation move?", and
        # comparing a value that we are about to bump would answer itself.
        identity = "|".join(
            component
            for component in snapshot.context_identity_components()
            if not component.startswith("generation=")
        )
        previous = self._last_identity.get((context_id, generation))
        invalidation: CacheInvalidationDescriptor | None = None
        if previous is not None and previous != identity:
            self._rotations[context_id] = self._rotations.get(context_id, 0) + 1
            rotated = generation + 1
            snapshot = replace(snapshot, generation=rotated)
            invalidation = CacheInvalidationDescriptor(
                context_id=context_id,
                previous_generation=generation,
                generation=rotated,
                reason="binding_or_authority_revision_changed",
                invalidated_identity=previous,
            )
            # Drop the superseded key rather than accumulating one entry per
            # (context, generation) forever; nothing can resolve at the old generation again.
            self._last_identity.pop((context_id, generation), None)
            self._last_identity[(context_id, rotated)] = identity
        else:
            self._last_identity[(context_id, generation)] = identity
        return ResolutionResult(snapshot=snapshot, invalidation=invalidation)


__all__ = [
    "DEFAULT_SELECTION_TTL_SECONDS",
    "HEADER_ACTIVE_CONTEXT_OVERRIDE",
    "HEADER_ACTIVE_CONTEXT_SESSION",
    "SELECTION_PROVENANCE_INSTANCE_DEFAULT",
    "SELECTION_PROVENANCE_NO_VAULT",
    "SELECTION_PROVENANCE_SESSION",
    "ActiveContextSelectionResolver",
    "BindingFact",
    "CacheInvalidationDescriptor",
    "ContextSelectionError",
    "ContextSelectionRecord",
    "ContextSelectionStore",
    "ReselectionRequiredError",
    "ResolutionResult",
    "SelectionPrincipalMismatchError",
]
