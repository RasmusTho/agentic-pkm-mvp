"""GOV revalidation inside the production cross-process binding effect window."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import time

from app.governance.binding_authority import BindingAuthorizationRequest
from app.governance.governed_write import (
    DecisionToken,
    GovernedWriteAdapter,
    InvalidDecisionTokenError,
)
from app.instance.active_context_service import build_authorizer
from app.instance.context_bound_read import context_bound_read_window
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import ActiveContextSetV1
from app.vault.manager import nearest_enclosing_vault_root


_WRITE_BOUNDARY: ContextVar[tuple[Path, str, Callable[[], None]] | None] = ContextVar(
    "governed_write_boundary", default=None
)


class ContextBoundSourceRefused(InvalidDecisionTokenError):
    """The state-owner admission hook refused before publishing source bytes."""


def require_effect_locator(root: Path, resource: str) -> None:
    boundary = _WRITE_BOUNDARY.get()
    if boundary is None:
        return
    expected_root, expected_resource, check = boundary
    if (
        root.resolve() != expected_root
        or resource != expected_resource
        or nearest_enclosing_vault_root(root / resource, search_root=expected_root) != expected_root
    ):
        raise ContextBoundSourceRefused("write locator changed at the state-owner seam")
    try:
        check()
    except InvalidDecisionTokenError as exc:
        raise ContextBoundSourceRefused(str(exc)) from exc


def require_selected_targets(context: ActiveContextSetV1, targets: tuple[str, ...]) -> None:
    if (
        not targets
        or len(set(targets)) != len(targets)
        or not set(targets).issubset(context.binding_ids)
    ):
        raise InvalidDecisionTokenError(
            "write targets must be a nonempty subset of selected bindings"
        )


@contextmanager
def context_bound_write_window(
    context: ActiveContextSetV1,
    *,
    target_binding_id: str,
    token: DecisionToken,
    registry_store: VaultRegistryStore,
    action: str,
    write_class: str,
    actor: str,
    resource: str,
    effect_check: Callable[[], None] | None = None,
) -> Iterator[Path]:
    """Hold ownership → shared binding lease through effect and durable receipt.

    The selected set is never widened by target lookup. Legacy/unbound tokens
    cannot pass this gate. Live GOV/revision checks happen after lock acquisition.
    """
    if context.expires_at is not None and context.expires_at <= time.time():
        raise InvalidDecisionTokenError("active context expired before write")
    require_selected_targets(context, (target_binding_id,))
    adapter = GovernedWriteAdapter()
    adapter.validate_decision_token(
        decision_token=token,
        action=action,
        write_class=write_class,
        actor=actor,
        resource=resource,
    )
    adapter.validate_context(token, context=context, target_binding_id=target_binding_id)
    with context_bound_read_window(context, registry_store=registry_store) as roots:
        # Lock acquisition may wait past the bearer snapshot's expiry. The
        # pre-lock check is only early refusal; this is final authorization.
        if context.expires_at is not None and context.expires_at <= time.time():
            raise InvalidDecisionTokenError("active context expired before write")
        binding = next(
            b for b in context.source_bindings if b.vault_binding_id == target_binding_id
        )
        verdict = build_authorizer(registry_store.load()).authorize(
            BindingAuthorizationRequest(
                principal=context.principal_context,
                vault_binding_id=target_binding_id,
                action=action,
                write_class=write_class,
                required_permission="write",
            )
        )
        if not verdict.allowed or verdict.epoch != binding.authorization_epoch:
            raise InvalidDecisionTokenError("binding authorization changed before write")
        root = next(r.root for r in roots if r.vault_binding_id == target_binding_id)
        if nearest_enclosing_vault_root(root / resource, search_root=root) != root:
            raise InvalidDecisionTokenError("write locator belongs to another vault boundary")
        from app.instance.scalar_binding_runtime import (
            frozen_binding_effect,
            resolve_scalar_binding_runtime,
        )

        runtime = resolve_scalar_binding_runtime(
            requested_binding_id=target_binding_id, vault_root=root
        )
        if runtime is None:
            raise InvalidDecisionTokenError("governed write requires a binding runtime")

        def check() -> None:
            # An authorized window does not extend the frozen selection's TTL.
            # State owners call this again after their own waits, immediately
            # before publishing source bytes.
            if context.expires_at is not None and context.expires_at <= time.time():
                raise InvalidDecisionTokenError("active context expired at the source seam")
            if effect_check is not None:
                effect_check()
            adapter.validate_decision_token(
                decision_token=token,
                action=action,
                write_class=write_class,
                actor=actor,
                resource=resource,
            )
            adapter.validate_context(token, context=context, target_binding_id=target_binding_id)
            # The owner callback may itself wait on approval or source I/O.
            # Observe expiry after that work, immediately before publication.
            if context.expires_at is not None and context.expires_at <= time.time():
                raise InvalidDecisionTokenError("active context expired at the source seam")

        from app.services.outbox_producers import active_context_emission

        boundary = _WRITE_BOUNDARY.set((root, resource, check))
        try:
            # MVR-05D: outbox emissions inside this window carry the request
            # ActiveContextSet identity and may only route to this target.
            with frozen_binding_effect(runtime), active_context_emission(
                context_id=context.context_id,
                context_generation=context.generation,
                target_binding_id=target_binding_id,
            ):
                yield root
        finally:
            _WRITE_BOUNDARY.reset(boundary)
