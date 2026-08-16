"""MVR-03 (#3857): the selection store and resolver at unit level.

`tests/api/test_active_context_resolution.py` drives the same machinery through the
production endpoints. This file pins the two properties that are structural rather than
behavioural, and that a request-level test cannot see: that resolution never reaches mutable
global selection, and that a changed binding revision or authority verdict rotates the
generation before the next snapshot is issued.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import app.instance.context_selection as context_selection
from app.governance.binding_authority import (
    BindingAuthorizationError,
    RegistryBindingAuthorizer,
    _test_revocation_capability,
)
from app.instance.context_selection import (
    ActiveContextSelectionResolver,
    BindingFact,
    ContextSelectionError,
    ContextSelectionStore,
    ReselectionRequiredError,
)
from app.vault.active_context_v1 import (
    ACTIVE_CONTEXT_SET_V1,
    ActiveContextSetV1,
    PrincipalContext,
    WorkspaceState,
)

PRINCIPAL = PrincipalContext(
    principal_id="lor_test_role",
    principal_kind="delegated_operator_role",
    subject="trusted_loopback",
)


def _resolver(facts: dict[str, BindingFact], authorizer, *, revision: int = 7, invalidate=None):
    state = {"facts": facts, "revision": revision}
    return (
        ActiveContextSelectionResolver(
            binding_facts=lambda: state["facts"],
            registry_revision=lambda: state["revision"],
            authorizer=authorizer,
            instance_identity="app-install-abc",
            invalidate_selection=invalidate,
        ),
        state,
    )


def test_selection_resolution_is_immutable_and_global_free() -> None:
    """One immutable, versioned snapshot from explicit inputs, with no global read.

    Three independent claims, because "global-free" is easy to assert loosely:

    1. *Structural*: neither the resolver module nor the store module references
       `VaultManager` / `get_vault_manager` / `active_context` at all. A future edit that
       reached for process-global selection would fail here before any behaviour changed.
    2. *Immutable*: the returned snapshot is a frozen dataclass and rejects mutation.
    3. *Explicit*: the snapshot's binding set is exactly the explicitly selected set, and a
       binding that exists in the registry but was not selected does not appear.

    Production HTTP carrier propagation stays sealed until MVR-05B: the carrier header names
    are declared here, but nothing in the request path depends on them yet.
    """

    # AST rather than raw text, so the module may *name* the forbidden globals in prose
    # while proving it never references them in code.
    tree = ast.parse(inspect.getsource(context_selection))
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Import):
            referenced.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            referenced.add(node.module or "")
            referenced.update(alias.name for alias in node.names)
    for forbidden in (
        "VaultManager",
        "get_vault_manager",
        "app.vault.manager",
        "active_context",
    ):
        assert (
            forbidden not in referenced
        ), f"the selection resolver must not reach mutable global selection ({forbidden})"

    facts = {
        "bind-a": BindingFact(vault_binding_id="bind-a", binding_revision=3, vault_id="v-a"),
        "bind-b": BindingFact(vault_binding_id="bind-b", binding_revision=4, vault_id="v-b"),
    }
    authorizer = RegistryBindingAuthorizer({"bind-a": 3, "bind-b": 4})
    resolver, _ = _resolver(facts, authorizer)

    store = ContextSelectionStore()
    raw_id, record = store.create(
        principal=PRINCIPAL,
        instance_identity="app-install-abc",
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        binding_ids=("bind-a",),
    )

    result = resolver.resolve(
        selection=record,
        principal=PRINCIPAL,
        action="read",
        write_class="read",
        required_permission="wsp.read",
    )
    snapshot = result.snapshot

    assert isinstance(snapshot, ActiveContextSetV1)
    assert snapshot.version == ACTIVE_CONTEXT_SET_V1
    assert snapshot.generation == 1
    # Only the explicitly selected binding, never the other registered one.
    assert snapshot.binding_ids == ("bind-a",)
    assert snapshot.registry_revision == 7
    assert snapshot.posture == "healthy"
    # The raw bearer never reaches the snapshot; only its non-reversible digest.
    assert snapshot.selection_capability_digest == record.selection_capability_digest
    assert raw_id not in str(snapshot)

    with pytest.raises(Exception):
        snapshot.generation = 2  # type: ignore[misc]

    # Sealed until MVR-05B: the carriers are named, but no production request path reads
    # them in this slice.
    assert context_selection.HEADER_ACTIVE_CONTEXT_SESSION == "X-Active-Context-Session"
    assert context_selection.HEADER_ACTIVE_CONTEXT_OVERRIDE == "X-Active-Context-Override"


def test_binding_revision_rotates_resolver_generation() -> None:
    """A changed binding revision or verdict rotates generation before the next snapshot.

    Three branches, all in one place because they share the rotation mechanism:

    - a **changed binding revision** under a still-authorizing verdict rotates to a new
      immutable generation and emits a cache-invalidation descriptor;
    - a **changed authority epoch** (still allow) does the same;
    - a **deny** verdict instead invalidates the selection and raises an explicit
      authorization error -- no ActiveContextSet containing the denied binding is reissued.

    Neither branch touches the still-sealed HTTP carrier or the relocation production gate;
    MVR-05B/06C own those call sites.
    """

    facts = {"bind-a": BindingFact(vault_binding_id="bind-a", binding_revision=3)}
    authorizer = RegistryBindingAuthorizer({"bind-a": 3})
    store = ContextSelectionStore()
    resolver, state = _resolver(facts, authorizer, invalidate=store.invalidate_digest)

    raw_id, record = store.create(
        principal=PRINCIPAL,
        instance_identity="app-install-abc",
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        binding_ids=("bind-a",),
    )

    kwargs = dict(
        principal=PRINCIPAL,
        action="read",
        write_class="read",
        required_permission="wsp.read",
    )
    first = resolver.resolve(selection=record, **kwargs)  # type: ignore[arg-type]
    assert first.snapshot.generation == 1
    assert first.invalidation is None
    assert first.snapshot.source_bindings[0].binding_revision == 3

    # -- branch 1: the binding revision moved (relocation / provenance change) ----------
    state["facts"] = {"bind-a": BindingFact(vault_binding_id="bind-a", binding_revision=4)}
    authorizer.set_binding("bind-a", 4)
    second = resolver.resolve(selection=record, **kwargs)  # type: ignore[arg-type]
    assert second.snapshot.generation == 2, "a changed binding revision must rotate generation"
    assert second.invalidation is not None
    assert second.invalidation.previous_generation == 1
    assert second.invalidation.generation == 2
    assert second.invalidation.context_id == record.context_id
    assert second.snapshot.source_bindings[0].binding_revision == 4
    # The authorization epoch is bound to the revision, so it moved too.
    assert (
        second.snapshot.source_bindings[0].authorization_epoch
        != first.snapshot.source_bindings[0].authorization_epoch
    )

    # A steady state does not keep rotating: rotation is a change signal, not a counter.
    # It also never goes backwards -- the rotated generation is retained.
    third = resolver.resolve(selection=record, **kwargs)  # type: ignore[arg-type]
    assert third.snapshot.generation == 2
    assert third.invalidation is None

    # -- branch 2: a deny verdict invalidates instead of reissuing -----------------------
    # The resolver performs the invalidation itself rather than leaving it to the caller,
    # and attaches the descriptor to the error, so a denied selection cannot survive because
    # someone forgot to call an invalidation helper.
    assert len(store) == 1
    authorizer.set_binding(
        "bind-a",
        4,
        revoked=True,
        _revocation_capability=_test_revocation_capability(),
    )
    with pytest.raises(BindingAuthorizationError) as denied:
        resolver.resolve(selection=record, **kwargs)  # type: ignore[arg-type]
    assert denied.value.verdict.status == "deny"
    assert denied.value.verdict.reason == "binding_revoked"
    invalidation = denied.value.invalidation  # type: ignore[attr-defined]
    assert invalidation.reason == "binding_denied:binding_revoked"
    assert invalidation.context_id == record.context_id

    # The selection is gone: a bearer holding it now needs reselection rather than being
    # served an ActiveContextSet containing the denied binding.
    assert len(store) == 0
    with pytest.raises(ReselectionRequiredError):
        store.inspect(raw_id, principal=PRINCIPAL, instance_identity="app-install-abc")


def test_concurrent_store_mutations_are_serialized() -> None:
    """A replace racing a clear cannot resurrect a cleared bearer.

    FastAPI runs sync handlers in a thread pool, so two requests really can execute against
    the process-wide store at once. Each mutation is a read-modify-write, so without a lock
    a PUT could read a record, lose the race to a concurrent DELETE, and then write the
    replacement back over the deletion — reporting a bearer cleared while leaving it live.
    """

    import threading

    store = ContextSelectionStore()
    bearers = []
    for _ in range(40):
        raw_id, _record = store.create(
            principal=PRINCIPAL,
            instance_identity="app-install-abc",
            workspace=WorkspaceState.none(),
            scope="default",
            sphere_memberships=(),
            situated_identity=None,
            binding_ids=("bind-a",),
        )
        bearers.append(raw_id)

    kwargs = dict(principal=PRINCIPAL, instance_identity="app-install-abc")
    barrier = threading.Barrier(2)
    survivors: list[str] = []
    errors: list[BaseException] = []

    def _clear(raw_id: str) -> None:
        barrier.wait()
        try:
            store.clear(raw_id, **kwargs)  # type: ignore[arg-type]
        except ContextSelectionError:
            pass
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def _replace(raw_id: str) -> None:
        barrier.wait()
        try:
            store.replace_bindings(raw_id, binding_ids=("bind-b",), **kwargs)  # type: ignore[arg-type]
        except ContextSelectionError:
            pass
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    for raw_id in bearers:
        barrier.reset()
        threads = [
            threading.Thread(target=_clear, args=(raw_id,)),
            threading.Thread(target=_replace, args=(raw_id,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        try:
            store.inspect(raw_id, **kwargs)  # type: ignore[arg-type]
            survivors.append(raw_id)
        except ContextSelectionError:
            pass

    assert not errors, errors
    # Every bearer was cleared. A surviving one means a replace wrote back over a completed
    # clear, which is exactly the resurrection this lock exists to prevent.
    assert survivors == [], f"{len(survivors)} cleared bearer(s) were resurrected"

    # Concurrent replaces on one bearer publish strictly increasing generations rather than
    # two handlers both returning the same one.
    raw_id, _ = store.create(
        principal=PRINCIPAL,
        instance_identity="app-install-abc",
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        binding_ids=("bind-a",),
    )
    generations: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def _bump() -> None:
        start.wait()
        record = store.replace_bindings(raw_id, binding_ids=("bind-b",), **kwargs)  # type: ignore[arg-type]
        with lock:
            generations.append(record.generation)

    workers = [threading.Thread(target=_bump) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert sorted(generations) == list(range(2, 10)), generations
