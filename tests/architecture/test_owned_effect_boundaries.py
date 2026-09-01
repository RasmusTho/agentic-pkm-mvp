"""Fitness checks for explicitly owned durable and external effects.

The fixtures are deliberately small. They exercise the declaration contract
that future capabilities can adopt without requiring every pure helper to grow
an interface. A declaration is a boundary description, not a replacement for
the owner contract or the concrete port implementation.
"""

from __future__ import annotations

from app.architecture.owned_effects import (
    EffectDeclaration,
    validate_effect_declarations,
)


def test_durable_and_external_effects_require_named_owner_ports() -> None:
    """Durable/external effects fail the fitness boundary when hidden."""
    compliant = (
        EffectDeclaration(
            name="persist_object",
            effect_class="mechanical durable",
            owner_contract="docs/contracts/STORE_PORT.md",
            port="StorePort",
        ),
        EffectDeclaration(
            name="publish_external_result",
            effect_class="external",
            owner_contract="docs/contracts/EXECUTION_REQUEST.md",
            port="ExecutionRequest",
        ),
    )
    assert validate_effect_declarations(compliant) == {}

    hidden_direct_effect = EffectDeclaration(
        name="hidden_direct_publish",
        effect_class="external",
        owner_contract="docs/contracts/EXECUTION_REQUEST.md",
        direct_effects=("http_client.post",),
    )
    violations = validate_effect_declarations((hidden_direct_effect,))

    assert "hidden_direct_publish" in violations
    assert any("owner port" in message for message in violations["hidden_direct_publish"])


def test_pure_internal_functions_do_not_require_generic_wrappers() -> None:
    """Pure computation remains valid without an owner contract or port."""
    pure = EffectDeclaration(name="calculate_score", effect_class="none")

    assert validate_effect_declarations((pure,)) == {}
