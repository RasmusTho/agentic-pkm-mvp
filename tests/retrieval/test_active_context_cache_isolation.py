"""MVR-03 (#3857): full-context cache identity and settings-reload invalidation.

The failure this guards against is concrete: two bearer selections sharing a binding and a
generation, but carrying different workspace state / scope / spheres / situated identity /
capability digest, being served each other's cached retrieval context.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from app.retrieval.context_cache import ContextCacheIdentity, context_cache_identity
from app.vault.active_context_v1 import (
    ActiveContextBinding,
    ActiveContextSetV1,
    PrincipalContext,
    WorkspaceState,
    selection_capability_digest,
)
from app.vault.manager import VaultContext
from app.vault.settings_bundle import settings_bundle_digest
from app.vault.settings_service import SettingsService

pytestmark = pytest.mark.not_pg

PRINCIPAL_A = PrincipalContext(
    principal_id="lor_role_a",
    principal_kind="delegated_operator_role",
    subject="trusted_loopback",
)
PRINCIPAL_B = PrincipalContext(
    principal_id="lor_role_b",
    principal_kind="human",
    subject="trusted_loopback",
)

BINDING = ActiveContextBinding(
    vault_binding_id="bind-a", binding_revision=3, authorization_epoch="epoch-1"
)


def _snapshot(**overrides) -> ActiveContextSetV1:
    base = dict(
        context_id="ctx-1",
        generation=4,
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        principal_context=PRINCIPAL_A,
        instance_identity="app-install-1",
        source_bindings=(BINDING,),
        registry_revision=9,
        authorization_epoch="snap-epoch-1",
        selection_provenance="session_selection",
        selection_capability_digest=selection_capability_digest("bearer-one"),
    )
    base.update(overrides)
    return ActiveContextSetV1(**base)  # type: ignore[arg-type]


def test_cache_keys_include_full_context_identity() -> None:
    """Same binding + same generation, different context ⇒ different cache key.

    Each varied dimension is checked on its own, so a regression names the exact field that
    dropped out of the key rather than reporting one opaque mismatch.
    """

    baseline = _snapshot()
    baseline_key = context_cache_identity(baseline, settings_bundle_digest="bundle-1").key

    variants: dict[str, ActiveContextSetV1] = {
        "workspace": _snapshot(workspace=WorkspaceState.bound("workspace-1")),
        "scope": _snapshot(scope="private"),
        "sphere_memberships": _snapshot(sphere_memberships=("team",)),
        "situated_identity": _snapshot(situated_identity="on-call"),
        "principal": _snapshot(principal_context=PRINCIPAL_B),
        "selection_capability_digest": _snapshot(
            selection_capability_digest=selection_capability_digest("bearer-two")
        ),
        "registry_revision": _snapshot(registry_revision=10),
        "authorization_epoch": _snapshot(authorization_epoch="snap-epoch-2"),
        "binding_revision": _snapshot(
            source_bindings=(
                ActiveContextBinding(
                    vault_binding_id="bind-a",
                    binding_revision=4,
                    authorization_epoch="epoch-1",
                ),
            )
        ),
        "binding_authorization_epoch": _snapshot(
            source_bindings=(
                ActiveContextBinding(
                    vault_binding_id="bind-a",
                    binding_revision=3,
                    authorization_epoch="epoch-2",
                ),
            )
        ),
        "binding_set": _snapshot(
            source_bindings=(
                BINDING,
                ActiveContextBinding(
                    vault_binding_id="bind-b",
                    binding_revision=1,
                    authorization_epoch="epoch-3",
                ),
            )
        ),
        "generation": _snapshot(generation=5),
        "context_id": _snapshot(context_id="ctx-2"),
    }

    keys = {"baseline": baseline_key}
    for name, snapshot in variants.items():
        key = context_cache_identity(snapshot, settings_bundle_digest="bundle-1").key
        assert key != baseline_key, f"{name} did not enter the cache key"
        keys[name] = key
    # The settings bundle is a key input too.
    keys["settings_bundle"] = context_cache_identity(
        baseline, settings_bundle_digest="bundle-2"
    ).key
    assert keys["settings_bundle"] != baseline_key

    # Every variant is pairwise distinct: no two dimensions collapse into one key.
    for (left_name, left), (right_name, right) in itertools.combinations(keys.items(), 2):
        assert left != right, f"{left_name} and {right_name} collided"

    # Binding plus generation alone is explicitly insufficient. Two selections agreeing on
    # exactly those two, and differing only in the *cognitive* context, must not collide.
    session_one = _snapshot(scope="work", sphere_memberships=("work",))
    session_two = _snapshot(scope="private", sphere_memberships=("private",))
    assert session_one.binding_ids == session_two.binding_ids
    assert session_one.generation == session_two.generation
    assert (
        context_cache_identity(session_one, settings_bundle_digest="b").key
        != context_cache_identity(session_two, settings_bundle_digest="b").key
    )

    # The raw bearer is never key material -- only its digest.
    components = "|".join(baseline.context_identity_components())
    assert "bearer-one" not in components
    assert baseline.selection_capability_digest is not None
    assert baseline.selection_capability_digest in components

    # Workspace is never inferred from another field: two snapshots differing only in
    # workspace differ in the key, and a bound workspace never leaks a vault id into it.
    assert "workspace=no_workspace:" in components

    # Action / write class / permission stay separate GOV inputs and receipt fields; they
    # are not cache-key material and must not have crept in.
    for authority_token in ("action=", "write_class=", "permission="):
        assert authority_token not in components


def _init_vault(vault_root: Path) -> VaultContext:
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nscope: vault-shared\n"
        "vaultId: vault-cache-test\nvaultName: Cache Test\n---\n",
        encoding="utf-8",
    )
    (settings_dir / "local.md").write_text(
        "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
        "localInstanceId: l1\nmachineRole: primary\nenableAutoIndexing: true\n---\n",
        encoding="utf-8",
    )
    return VaultContext(
        status="selected",
        active_vault_id="vault-cache-test",
        active_vault_name="Cache Test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
        machine_role="primary",
    )


def test_settings_reload_changes_cache_identity_before_next_lookup(tmp_path: Path) -> None:
    """A hot reload that changes a behaviour-shaping setting invalidates before reuse.

    The reload is a real Settings Spine reload over a real settings file, not a stubbed
    digest: `SettingsService.reload` re-reads from disk, and the bundle digest is computed
    from the resolved effective settings.
    """

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    context = _init_vault(vault_root)
    service = SettingsService()

    before = service.reload(context)
    before_digest = settings_bundle_digest(before.settings)
    # `enableAutoIndexing` is a runtime-gating, behaviour-shaping effective setting: it
    # decides whether retrieval material is produced at all.
    assert before.settings["enableAutoIndexing"].value is True

    snapshot = _snapshot()
    identity_before = context_cache_identity(snapshot, settings_bundle_digest=before_digest)

    # A plain dict stands in for whatever cache a consumer keeps. The invariant belongs to
    # the *identity*, not to a bespoke cache class: if the key changes, a lookup under the
    # new bundle cannot reach the old entry, whatever the store is.
    cache: dict[str, str] = {identity_before.key: "computed-under-old-bundle"}
    assert cache.get(identity_before.key) == "computed-under-old-bundle"

    # A no-op reload must NOT invalidate: a digest changes if and only if a value changed.
    unchanged = settings_bundle_digest(service.reload(context).settings)
    assert unchanged == before_digest
    assert (
        context_cache_identity(snapshot, settings_bundle_digest=unchanged).key
        == identity_before.key
    )

    # Now change the behaviour-shaping setting on disk and hot-reload.
    (vault_root / "settings" / "local.md").write_text(
        "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
        "localInstanceId: l1\nmachineRole: primary\nenableAutoIndexing: false\n---\n",
        encoding="utf-8",
    )
    after = service.reload(context)
    assert after.settings["enableAutoIndexing"].value is False
    after_digest = settings_bundle_digest(after.settings)
    assert after_digest != before_digest

    identity_after = context_cache_identity(snapshot, settings_bundle_digest=after_digest)
    assert identity_after.key != identity_before.key

    # The next lookup under the new bundle misses -- no result computed under the old
    # bundle is reused, even though context id, generation, and bindings are identical.
    assert cache.get(identity_after.key) is None
    # Which is exactly why "invalidate before the next lookup" needs no separate mechanism:
    # a changed bundle digest makes the old entry unreachable rather than merely stale.
    assert identity_after.key not in cache

    assert isinstance(identity_after, ContextCacheIdentity)
