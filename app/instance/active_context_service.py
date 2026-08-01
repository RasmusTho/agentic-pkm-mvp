"""Server-owned assembly of an active-context selection (MVR-03).

This is the auth/GOV/WSP join point. It exists so the API router stays a thin transport
shell and so the *derivation* rules -- which are the security-bearing part -- live in one
typed, unit-testable place:

- **principal**: resolved from the private delegated-role record via the server-derived
  auth subject. Never from `appInstallId`, never from a client string, never from a path.
- **instance identity**: read from the registry's `app_install_id`. Carried separately and
  never allowed to derive, equal, or substitute for a principal.
- **workspace**: derived from the authenticated WSP workspace binding, or the typed
  `no_workspace` state when none exists. Never inferred from vault, path, scope, or
  principal.
- **scope / spheres / situated identity**: derived from the server-owned WSP context policy,
  with the canonical legal defaults `"default"`, `[]`, and `None`.
- **action / write class / permission**: *not* derived here at all. They belong to the
  endpoint contract and reach GOV as separate decision inputs per call.

A client can supply exactly one thing: which bindings to select -- either as an explicit
list of registered `vault_binding_id` values, or (MVR-04) as one `dimension_id` that already
exists in the instance registry, which the server resolves here into that same explicit
list. A dimension is a shorthand for bindings the operator already stored; it is never a
projection the client authors, and it changes none of the derivations above.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.governance.binding_authority import RegistryBindingAuthorizer
from app.instance.context_selection import (
    BindingFact,
    ContextSelectionRecord,
    ContextSelectionStore,
)
from app.instance.local_operator_principal import (
    AuthPosture,
    LocalOperatorPrincipalRecord,
    PrincipalPreflightError,
    verify_credential,
)
from app.instance.vault_dimensions import (
    DimensionResolution,
    VaultDimensionService,
)
from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore
from app.vault.active_context_v1 import (
    CANONICAL_DEFAULT_SCOPE,
    AuthSubject,
    PrincipalContext,
    WorkspaceState,
)

#: The selection-management commands' own actions. They are derived from the server-owned
#: endpoint contract, not from anything the client sends, and they are GOV inputs rather
#: than stored selection state.
ACTION_SELECTION_CREATE = "active_context.selection.create"
ACTION_SELECTION_REPLACE = "active_context.selection.replace"
ACTION_SELECTION_INSPECT = "active_context.selection.inspect"
ACTION_SELECTION_CLEAR = "active_context.selection.clear"

WRITE_CLASS_MECHANICAL_SESSION = "mechanical_session_state"
WRITE_CLASS_READ = "read"

PERMISSION_SELECTION_MANAGE = "wsp.active_context.manage_selection"
PERMISSION_SELECTION_READ = "wsp.active_context.read_selection"

#: The MVR-04 dimension-resolution command's own GOV decision inputs. They are exactly the
#: selection-management inputs above: resolving a dimension is not a distinct privilege and
#: must not acquire one, or grouping would have become an authority path after all.
ACTION_DIMENSION_RESOLVE = "active_context.dimension.resolve"


class ActiveContextServiceError(RuntimeError):
    """Fail-closed service error."""


class SelectionIntentError(ActiveContextServiceError):
    """The request combined two mutually exclusive forms of selection intent."""


def resolve_principal(
    record: LocalOperatorPrincipalRecord,
    subject: AuthSubject,
    *,
    presented_credential: str | None = None,
) -> PrincipalContext:
    """Map a server-derived auth subject onto the delegated role, or fail closed.

    A governed operation with no resolved principal/delegated role fails closed: there is
    no anonymous fallback and no "derive it from the instance" branch.
    """

    if subject == "api_key_credential":
        if not presented_credential:
            raise PrincipalPreflightError(
                "the api_key_credential subject requires the presented credential",
                provisioning_action="present the configured #2223 credential",
            )
        if not verify_credential(record.credential_fingerprint, presented_credential):
            raise PrincipalPreflightError(
                "presented credential does not match the bound delegated role",
                provisioning_action="rotate the credential through the governed command",
            )
    return record.principal_for(subject)


def derive_workspace_state(snapshot: RegistrySnapshot) -> WorkspaceState:
    """Derive workspace identity from the authenticated WSP workspace binding.

    The current runtime has no WSP workspace binding: workspaces are not yet a shipped
    concept, and the contract forbids inferring one from the vault, path, scope, or
    principal. So the truthful answer today is the *typed* `no_workspace` state -- which is
    explicitly a healthy state, not a missing value.

    When a workspace binding ships, it is read from registry extension state here and
    nowhere else.
    """

    workspaces = (snapshot.extensions or {}).get("workspaceBinding")
    if isinstance(workspaces, dict):
        workspace_id = workspaces.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            return WorkspaceState.bound(workspace_id)
    return WorkspaceState.none()


def derive_scope(snapshot: RegistrySnapshot) -> str:
    """Derive the cognitive operational scope from the server-owned WSP context policy.

    No narrower scope is declared by the current policy, so the canonical `"default"` value
    applies. A client-supplied scope string can never reach this function.
    """

    policy = (snapshot.extensions or {}).get("wspContextPolicy")
    if isinstance(policy, dict):
        scope = policy.get("scope")
        if isinstance(scope, str) and scope.strip():
            return scope.strip()
    return CANONICAL_DEFAULT_SCOPE


def derive_sphere_memberships(snapshot: RegistrySnapshot) -> tuple[str, ...]:
    """Canonical legal default `[]` until the WSP context supplies memberships."""

    policy = (snapshot.extensions or {}).get("wspContextPolicy")
    if isinstance(policy, dict):
        spheres = policy.get("sphere_memberships")
        if isinstance(spheres, list):
            return tuple(str(item) for item in spheres if isinstance(item, str))
    return ()


def derive_situated_identity(snapshot: RegistrySnapshot) -> str | None:
    """Canonical legal default `None` until the WSP context supplies one."""

    policy = (snapshot.extensions or {}).get("wspContextPolicy")
    if isinstance(policy, dict):
        situated = policy.get("situated_identity")
        if isinstance(situated, str) and situated.strip():
            return situated.strip()
    return None


def binding_revision_for(snapshot: RegistrySnapshot, vault_binding_id: str) -> int:
    """The monotonic path/device/authority-provenance revision of one binding.

    The registry carries one monotonic store revision plus per-entry provenance. A binding's
    own revision is the store revision at which its current path/device/provenance became
    true, recorded in its `extensions`. Entries written before MVR-03 have no recorded
    value, so they fall back to the registry revision -- monotonic and never decreasing,
    which is what the rotation check needs.
    """

    registration = snapshot.registrations.get(vault_binding_id)
    if registration is None:
        return 0
    recorded = (registration.extensions or {}).get("bindingRevision")
    if isinstance(recorded, int) and recorded > 0:
        return recorded
    return snapshot.revision


def binding_facts(snapshot: RegistrySnapshot) -> dict[str, BindingFact]:
    facts: dict[str, BindingFact] = {}
    for binding_id, registration in snapshot.registrations.items():
        facts[binding_id] = BindingFact(
            vault_binding_id=binding_id,
            binding_revision=binding_revision_for(snapshot, binding_id),
            vault_id=registration.vault_id,
            local_instance_id=registration.local_instance_id,
            label=registration.vault_name,
            available=Path(registration.path).is_dir(),
        )
    return facts


def build_authorizer(snapshot: RegistrySnapshot) -> RegistryBindingAuthorizer:
    """Seed the GOV authorizer with current registry truth for every known binding."""

    authorizer = RegistryBindingAuthorizer()
    for binding_id, fact in binding_facts(snapshot).items():
        authorizer.set_binding(
            binding_id,
            fact.binding_revision,
            available=fact.available,
        )
    return authorizer


@dataclass(frozen=True)
class DerivedContext:
    """Everything the server derived for one selection, with nothing client-authored."""

    principal: PrincipalContext
    instance_identity: str
    workspace: WorkspaceState
    scope: str
    sphere_memberships: tuple[str, ...]
    situated_identity: str | None


class ActiveContextSelectionService:
    """Production entrypoint for create / replace / inspect / clear.

    It drives the selection store and never mutates process-global `VaultManager` state --
    structurally, because it holds no reference to it.
    """

    def __init__(
        self,
        *,
        registry_store: VaultRegistryStore,
        principal_record: LocalOperatorPrincipalRecord,
        selection_store: ContextSelectionStore,
    ) -> None:
        self._registry = registry_store
        self._principal_record = principal_record
        self._selections = selection_store

    @property
    def selection_store(self) -> ContextSelectionStore:
        return self._selections

    def derive(
        self,
        subject: AuthSubject,
        *,
        presented_credential: str | None = None,
    ) -> DerivedContext:
        snapshot = self._registry.load()
        return DerivedContext(
            principal=resolve_principal(
                self._principal_record,
                subject,
                presented_credential=presented_credential,
            ),
            instance_identity=snapshot.app_install_id,
            workspace=derive_workspace_state(snapshot),
            scope=derive_scope(snapshot),
            sphere_memberships=derive_sphere_memberships(snapshot),
            situated_identity=derive_situated_identity(snapshot),
        )

    def validate_bindings(self, binding_ids: Sequence[str]) -> None:
        """Reject a selection naming a binding this instance does not know.

        This is an input-validation refusal, not an authorization decision: GOV still
        authorizes every member independently at resolution time.
        """

        snapshot = self._registry.load()
        unknown = [
            binding_id for binding_id in binding_ids if binding_id not in snapshot.registrations
        ]
        if unknown:
            raise ActiveContextServiceError(
                f"unknown vault binding id(s): {sorted(unknown)}"
            )

    def resolve_dimension(
        self,
        dimension_id: str,
        *,
        derived: DerivedContext,
    ) -> DimensionResolution:
        """Turn one stored dimension id into an explicit, authorized binding set.

        The client supplies an *id that must already exist in the instance registry*, and
        nothing else. The server loads the registry, builds the same GOV authorizer the
        normal selection path builds, and asks it about every member independently with
        the endpoint contract's own decision inputs. An unknown, stale, removed, or
        unauthorized member fails the whole call.

        Note what this method does not do: it does not accept a member list, a projection,
        a filter expression, or any dimension the registry does not already hold. There is
        no path from a client string to a binding set except through stored membership
        that an authenticated administrator previously validated.
        """

        snapshot = self._registry.load()
        return VaultDimensionService(self._registry).resolve(
            dimension_id,
            principal=derived.principal,
            action=ACTION_DIMENSION_RESOLVE,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_MANAGE,
            authorizer=build_authorizer(snapshot),
            snapshot=snapshot,
        )

    def create(
        self,
        *,
        derived: DerivedContext,
        binding_ids: Sequence[str] = (),
        dimension_id: str | None = None,
    ) -> tuple[str, ContextSelectionRecord]:
        resolved_ids, dimension_filter = self._resolve_selection_intent(
            derived=derived, binding_ids=binding_ids, dimension_id=dimension_id
        )
        return self._selections.create(
            principal=derived.principal,
            instance_identity=derived.instance_identity,
            workspace=derived.workspace,
            scope=derived.scope,
            sphere_memberships=derived.sphere_memberships,
            situated_identity=derived.situated_identity,
            binding_ids=resolved_ids,
            dimension_filter=dimension_filter,
        )

    def replace(
        self,
        raw_selection_id: str,
        *,
        derived: DerivedContext,
        binding_ids: Sequence[str] = (),
        dimension_id: str | None = None,
    ) -> ContextSelectionRecord:
        resolved_ids, dimension_filter = self._resolve_selection_intent(
            derived=derived, binding_ids=binding_ids, dimension_id=dimension_id
        )
        return self._selections.replace_bindings(
            raw_selection_id,
            principal=derived.principal,
            instance_identity=derived.instance_identity,
            binding_ids=resolved_ids,
            dimension_filter=dimension_filter,
        )

    def _resolve_selection_intent(
        self,
        *,
        derived: DerivedContext,
        binding_ids: Sequence[str],
        dimension_id: str | None,
    ) -> tuple[tuple[str, ...], Any]:
        """Turn selection intent into the validated explicit binding set that gets stored.

        Exactly one form of intent is accepted. Supplying both an explicit binding list and
        a dimension id is refused rather than merged: a union would be a client-authored
        projection wearing a stored dimension's name, and it is the one shape that could
        let a caller reach past what the dimension actually holds.

        Only the resolved explicit binding set plus the dimension revision is persisted.
        The dimension id is never stored as something to re-expand later.
        """

        target = (dimension_id or "").strip() or None
        if target is not None and binding_ids:
            raise SelectionIntentError(
                "selection intent is either explicit vault_binding_ids or one dimension_id, "
                "never both"
            )
        if target is None:
            self.validate_bindings(binding_ids)
            return tuple(binding_ids), None
        resolution = self.resolve_dimension(target, derived=derived)
        return resolution.binding_ids, resolution.as_filter()

    def inspect(
        self, raw_selection_id: str, *, derived: DerivedContext
    ) -> ContextSelectionRecord:
        return self._selections.inspect(
            raw_selection_id,
            principal=derived.principal,
            instance_identity=derived.instance_identity,
        )

    def clear(self, raw_selection_id: str, *, derived: DerivedContext) -> None:
        self._selections.clear(
            raw_selection_id,
            principal=derived.principal,
            instance_identity=derived.instance_identity,
        )


def current_auth_posture(*, loopback_listener_proven: bool) -> AuthPosture:
    """Read the deployment's real auth posture from server configuration.

    Exactly the sources `app/auth.py` itself reads, so the posture the bootstrap binds and
    the posture the request path admits cannot disagree: `settings.api_key` (env `API_KEY`)
    and `settings.companion_ui_proxy_hosts`.

    `configured_credentials` is therefore 0 or 1 today -- the runtime has one credential
    slot. `AuthPosture` can still *represent* an ambiguous multi-credential posture and
    `preflight_auth_posture` rejects it, because that is a real posture on a native install
    with more than one auth source; it is simply not reachable from this configuration
    reader. Inventing a second env var here would let an operator make bootstrap and the
    admission path disagree about what a credential is.
    """

    from app.settings import settings

    configured = [value for value in (settings.api_key,) if value]
    proxy_hosts = (settings.companion_ui_proxy_hosts or "").strip()
    return AuthPosture(
        configured_credentials=len(configured),
        credential=configured[0] if len(configured) == 1 else None,
        loopback_listener_proven=loopback_listener_proven,
        companion_proxy_configured=bool(proxy_hosts),
    )


__all__ = [
    "ACTION_DIMENSION_RESOLVE",
    "ACTION_SELECTION_CLEAR",
    "ACTION_SELECTION_CREATE",
    "ACTION_SELECTION_INSPECT",
    "ACTION_SELECTION_REPLACE",
    "PERMISSION_SELECTION_MANAGE",
    "PERMISSION_SELECTION_READ",
    "WRITE_CLASS_MECHANICAL_SESSION",
    "WRITE_CLASS_READ",
    "ActiveContextSelectionService",
    "ActiveContextServiceError",
    "SelectionIntentError",
    "DerivedContext",
    "binding_facts",
    "binding_revision_for",
    "build_authorizer",
    "current_auth_posture",
    "derive_scope",
    "derive_situated_identity",
    "derive_sphere_memberships",
    "derive_workspace_state",
    "resolve_principal",
]
