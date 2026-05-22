"""Metadata compatibility tests for MemoryCandidate and the Contextualization Layer.

Verifies structural compatibility between MemoryCandidate artifacts and the
contracts defined in:
  - docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md §6
  - docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md §4.3.1

These are structural (field-presence, allowed-value, type-safety) checks.
Runtime activation enforcement is out of scope here (that is #1083).
"""
from __future__ import annotations

import pytest

from app.agent_memory.candidate import (
    ActivationPolicy,
    MemoryCandidate,
    MemoryType,
    ReviewState,
)

# ---------------------------------------------------------------------------
# Allowed value sets derived from ARTIFACT_METADATA_CONTRACT.md §6
# ---------------------------------------------------------------------------

ALLOWED_MEMORY_TYPES = {
    "working_context",
    "episodic_memory",
    "semantic_memory",
    "prospective_memory",
    "procedural_memory",
    "preference_memory",
    "policy_memory",
}

# Common artifact_type values for agentic memory (illustrative, not closed list)
# per ARTIFACT_METADATA_CONTRACT.md §6 "Common artifact_type values".
COMMON_ARTIFACT_TYPES = {
    "task_snapshot",
    "synthetic_summary",
    "reflection_record",
    "activation_trace",
    "preference_candidate",
    "procedural_hint",
}

# Canonical review_state values per ARTIFACT_METADATA_CONTRACT.md §4 and
# CONTEXT_ACTIVATION_SEMANTICS.md §7.3.
CANONICAL_REVIEW_STATES = {
    "unreviewed",
    "reviewed",
    "accepted",
    "rejected",
    "revised",
}


# ---------------------------------------------------------------------------
# AC 1: artifact_class is 'agentic_memory'
# ---------------------------------------------------------------------------


def test_memory_candidate_has_correct_artifact_class():
    """artifact_class must be 'agentic_memory' — not 'human_knowledge',
    'bridge_artifact', or 'machine_mirror'.

    ARTIFACT_METADATA_CONTRACT.md §4, §6.
    """
    candidate = MemoryCandidate(
        title="Prefers short answers",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:test-001"],
    )

    assert candidate.artifact_class == "agentic_memory", (
        f"Expected artifact_class 'agentic_memory', got {candidate.artifact_class!r}. "
        "Memory candidates must not be classified as human_knowledge, bridge_artifact, "
        "or machine_mirror."
    )

    # Confirm it is not accidentally one of the other umbrella classes.
    assert candidate.artifact_class not in {
        "human_knowledge",
        "bridge_artifact",
        "machine_mirror",
        "companion_metadata",
        "context_bundle",
    }


# ---------------------------------------------------------------------------
# AC 2: memory_type and artifact_type are independent axes
# ---------------------------------------------------------------------------


def test_memory_type_and_artifact_type_are_independent():
    """memory_type (cognitive class) and artifact_type (artifact form) are
    orthogonal and set independently.  A task_snapshot may carry different
    cognitive classes depending on intent.

    ARTIFACT_METADATA_CONTRACT.md §6, §4.1 "Dimension independence".
    """
    # Same form, different cognitive classes — all valid.
    episodic_snapshot = MemoryCandidate(
        title="What happened in yesterday's review session",
        memory_type=MemoryType.EPISODIC_MEMORY,
        artifact_type="task_snapshot",
        source_refs=["session:2026-05-20"],
    )
    prospective_snapshot = MemoryCandidate(
        title="Follow up on open action items",
        memory_type=MemoryType.PROSPECTIVE_MEMORY,
        artifact_type="task_snapshot",
        source_refs=["session:2026-05-20"],
    )

    # Same cognitive class, different forms — all valid.
    preference_candidate = MemoryCandidate(
        title="User prefers bullet-point summaries",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        artifact_type="preference_candidate",
        source_refs=["session:2026-05-21"],
    )
    preference_reflection = MemoryCandidate(
        title="Reflection: user consistently chooses shorter output",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        artifact_type="reflection_record",
        source_refs=["session:2026-05-21"],
    )

    # memory_type values are within the allowed set.
    for candidate in (
        episodic_snapshot,
        prospective_snapshot,
        preference_candidate,
        preference_reflection,
    ):
        assert candidate.memory_type.value in ALLOWED_MEMORY_TYPES, (
            f"memory_type {candidate.memory_type.value!r} is not in the allowed set "
            f"{ALLOWED_MEMORY_TYPES}"
        )

    # artifact_type values are within the common (non-closed) set.
    for candidate in (
        episodic_snapshot,
        prospective_snapshot,
        preference_candidate,
        preference_reflection,
    ):
        assert candidate.artifact_type in COMMON_ARTIFACT_TYPES, (
            f"artifact_type {candidate.artifact_type!r} is not in the common set "
            f"{COMMON_ARTIFACT_TYPES}"
        )

    # The two axes are independent — they are not the same field.
    assert episodic_snapshot.memory_type != episodic_snapshot.artifact_type
    assert (
        episodic_snapshot.memory_type.value != episodic_snapshot.artifact_type
    ), "memory_type and artifact_type must not be collapsed into a single field."

    # context_bundle is NOT a memory_type per ARTIFACT_METADATA_CONTRACT.md §6.
    with pytest.raises(ValueError):
        MemoryCandidate(
            title="Should fail — context_bundle is not a memory_type",
            memory_type="context_bundle",  # type: ignore[arg-type]
            source_refs=["session:invalid"],
        )


# ---------------------------------------------------------------------------
# AC 3: review_state defaults to 'unreviewed'
# ---------------------------------------------------------------------------


def test_review_state_defaults_to_unreviewed():
    """review_state must default to 'unreviewed' for newly created candidates
    and must follow the canonical value set.

    ARTIFACT_METADATA_CONTRACT.md §4 (review_state field).
    CONTEXT_ACTIVATION_SEMANTICS.md §7.3.
    """
    candidate = MemoryCandidate(
        title="Newly observed preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:new-001"],
    )

    assert candidate.review_state == ReviewState.UNREVIEWED
    assert candidate.review_state.value == "unreviewed"

    # All canonical values must be representable.
    for value in CANONICAL_REVIEW_STATES:
        state = ReviewState(value)
        assert state.value == value, (
            f"ReviewState does not support canonical value {value!r}"
        )


# ---------------------------------------------------------------------------
# AC 4: unreviewed candidate has restrictive activation_policy
# ---------------------------------------------------------------------------


def test_unreviewed_candidate_has_restrictive_activation_policy():
    """An unreviewed candidate must carry activation_policy: review_queue_only
    by default.  This prevents the artifact from entering agent task working
    context even if retrieval surfaces it.

    CONTEXT_ACTIVATION_SEMANTICS.md §4.3.1.
    """
    candidate = MemoryCandidate(
        title="Unreviewed preference observation",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:unreviewed-001"],
    )

    assert candidate.review_state == ReviewState.UNREVIEWED
    assert candidate.activation_policy == ActivationPolicy.REVIEW_QUEUE_ONLY, (
        f"Unreviewed candidate must have activation_policy 'review_queue_only', "
        f"got {candidate.activation_policy!r}."
    )
    assert candidate.activation_policy.value == "review_queue_only"

    # The ActivationPolicy enum must include all values from §4.3.1.
    required_policy_values = {
        "explicit_only",
        "explicit_or_contextual",
        "on_resume",
        "review_queue_only",
        "blocked",
    }
    actual_policy_values = {p.value for p in ActivationPolicy}
    assert required_policy_values <= actual_policy_values, (
        f"ActivationPolicy is missing values from §4.3.1: "
        f"{required_policy_values - actual_policy_values}"
    )

    # An accepted (promoted) candidate may hold a less restrictive policy.
    accepted_candidate = MemoryCandidate(
        title="Accepted preference: prefers weekly digest",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=["session:reviewed-001"],
        review_state=ReviewState.ACCEPTED,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
    )
    assert accepted_candidate.activation_policy != ActivationPolicy.REVIEW_QUEUE_ONLY


# ---------------------------------------------------------------------------
# AC 5: provenance fields are present for system-generated candidates
# ---------------------------------------------------------------------------


def test_memory_candidate_provenance_fields_are_present():
    """source_refs / derived_from and generated_by must be present and
    non-empty for system-generated candidates.

    ARTIFACT_METADATA_CONTRACT.md §11 "Provenance and Derivation".
    """
    system_candidate = MemoryCandidate(
        title="Agent-inferred: user avoids multi-level nesting",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        artifact_type="preference_candidate",
        source_refs=["session:2026-05-22T10:00:00Z"],
        derived_from="conversation:session-abc",
        generated_by="companion_agent_v1",
        confidence="medium",
    )

    # source_refs must be present and non-empty.
    assert system_candidate.source_refs, (
        "source_refs must be non-empty for system-generated candidates"
    )

    # derived_from must be present and non-empty.
    assert system_candidate.derived_from, (
        "derived_from must be present for system-generated candidates"
    )

    # generated_by must be present and non-empty.
    assert system_candidate.generated_by, (
        "generated_by must be present for system-generated candidates"
    )

    # Confirm the fields carry the values we set.
    assert system_candidate.source_refs == ["session:2026-05-22T10:00:00Z"]
    assert system_candidate.derived_from == "conversation:session-abc"
    assert system_candidate.generated_by == "companion_agent_v1"

    # confidence is a recommended provenance field per §11.
    assert system_candidate.confidence == "medium"

    # The fields are first-class model attributes (not buried in a nested dict).
    assert hasattr(system_candidate, "source_refs")
    assert hasattr(system_candidate, "derived_from")
    assert hasattr(system_candidate, "generated_by")
    assert hasattr(system_candidate, "confidence")
