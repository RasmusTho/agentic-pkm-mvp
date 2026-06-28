"""DRAFT #2585 — tests/invariants/test_invariant_residue.py

Honesty gate for the runtime slice: prove the targeted skeletons were converted FOR REAL and the
deliberately-left invariants remain xfail. The xfails are dynamic (require_future_runtime gates on a
missing yggdrasil_runtime.<module>), so we assert by calling each skeleton directly:
- a targeted invariant's module exists -> its body runs and passes (no raise);
- a residual invariant's module is absent -> require_future_runtime raises XFailed.

This catches both a silent regression (a target reverting to xfail) and an accidental conversion (a
"left for later" invariant passing without its runtime).
"""

from __future__ import annotations

import importlib

import pytest

# slug -> (test module, test function). Targeted = converted by this slice (must run+pass).
TARGETED: dict[str, tuple[str, str]] = {
    "capture_stamps_scope": ("tests.invariants.test_metadata_bundle", "test_capture_stamps_scope"),
    "provenance_survives_derivation": ("tests.invariants.test_metadata_bundle", "test_provenance_survives_derivation"),
    "retrieve_scope_prefilter": ("tests.invariants.test_cross_scope_flow", "test_retrieve_scope_prefilter"),
    "similarity_not_permission": ("tests.invariants.test_cross_scope_flow", "test_similarity_is_not_permission"),
    "cross_scope_only_via_flow": ("tests.invariants.test_cross_scope_flow", "test_cross_scope_only_via_flow"),
    "cross_scope_only_via_flow__general": ("tests.evals.test_general_knowledge_crosses_clean", "test_general_knowledge_crosses_clean"),
    "private_not_in_work_results": ("tests.evals.test_private_not_in_work_results", "test_private_not_in_work_results"),
    "rpg_not_confused_with_software": ("tests.evals.test_rpg_not_confused_with_software", "test_rpg_not_confused_with_software"),
    "retrieval_cannot_upgrade_intrinsic_non_evidence__runtime": ("tests.invariants.test_retrieval_result", "test_retrieval_full_evidence_monotonicity_runtime"),
}

# slug -> (test module, test function). Residual = deliberately left for a future slice (must xfail).
RESIDUAL: dict[str, tuple[str, str]] = {
    "authority_transition_required_for_durable_mutation": ("tests.invariants.test_authority_transition", "test_authority_transition_required_for_durable_mutation"),
    "storage_write_is_not_authority_transition": ("tests.invariants.test_authority_transition", "test_storage_write_is_not_authority_transition"),
    "execution_cannot_authorize_itself": ("tests.invariants.test_authority_transition", "test_execution_cannot_authorize_itself"),
    "promote_requires_governance": ("tests.invariants.test_authority_transition", "test_promote_requires_governance"),
    "propose_when_uncertain": ("tests.invariants.test_context_envelope", "test_propose_when_uncertain"),
    "parent_aggregation_not_sibling_sharing": ("tests.invariants.test_cross_scope_flow", "test_parent_aggregation_not_sibling_sharing"),
    "sync_preserves_boundaries": ("tests.invariants.test_cross_scope_flow", "test_sync_preserves_boundaries"),
    "projection_not_evidence": ("tests.invariants.test_projection_not_evidence", "test_projection_not_evidence"),
    "observability_not_policy": ("tests.invariants.test_projection_not_evidence", "test_observability_not_policy"),
}

# Future-runtime modules that MUST stay absent so the residual skeletons keep xfailing.
RESIDUAL_MODULES = (
    "authority", "storage", "execution", "memory", "agent", "scope", "sync", "projection", "observability",
)
# In-slice modules that MUST exist so the targeted skeletons run for real.
TARGETED_MODULES = ("metadata", "capture", "dri", "corpus", "cross_scope", "retrieval", "context")


def _load(ref: tuple[str, str]):
    module, func = ref
    return getattr(importlib.import_module(module), func)


def _is_xfail(exc: BaseException) -> bool:
    # require_future_runtime calls pytest.xfail(), which raises _pytest.outcomes.XFailed.
    return type(exc).__name__ in {"XFailed", "Skipped"}


@pytest.mark.parametrize("slug", sorted(TARGETED))
def test_targeted_invariants_are_runtime_passing(slug: str) -> None:
    # The module exists, so the skeleton runs its real assertions. It must pass (no raise) and must
    # NOT have xfailed — proving the conversion is real, not faked.
    fn = _load(TARGETED[slug])
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - we re-raise non-xfail failures explicitly
        if _is_xfail(exc):
            pytest.fail(f"targeted invariant {slug!r} unexpectedly xfailed (runtime module missing?)")
        raise


@pytest.mark.parametrize("slug", sorted(RESIDUAL))
def test_expected_xfail_set_is_unchanged(slug: str) -> None:
    # The residual invariant's runtime is deliberately absent, so its skeleton must still xfail.
    fn = _load(RESIDUAL[slug])
    with pytest.raises(BaseException) as ei:
        fn()
    assert _is_xfail(ei.value), (
        f"residual invariant {slug!r} did not xfail — its runtime may have been added prematurely"
    )


def test_targeted_modules_present() -> None:
    for mod in TARGETED_MODULES:
        importlib.import_module(f"yggdrasil_runtime.{mod}")


def test_residual_modules_absent() -> None:
    for mod in RESIDUAL_MODULES:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"yggdrasil_runtime.{mod}")


def test_residue_counts_are_pinned() -> None:
    # A bare count guard: 9 targeted invariant test nodes, 9 residual. Adding/removing either side
    # without updating this gate fails loud.
    assert len(TARGETED) == 9
    assert len(RESIDUAL) == 9
