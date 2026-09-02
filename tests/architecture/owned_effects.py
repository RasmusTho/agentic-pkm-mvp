"""Declaration contract used by the owned-effect architecture fitness rail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EffectClass = Literal[
    "authority-bearing durable",
    "mechanical durable",
    "derived/rebuildable",
    "external",
    "none",
]

_EFFECTFUL_CLASSES = frozenset(
    {
        "authority-bearing durable",
        "mechanical durable",
        "derived/rebuildable",
        "external",
    }
)
_KNOWN_EFFECT_CLASSES = _EFFECTFUL_CLASSES | {"none"}


@dataclass(frozen=True)
class EffectDeclaration:
    """Describe the effect boundary of one capability."""

    name: str
    effect_class: EffectClass
    owner_contract: str | None = None
    port: str | None = None
    direct_effects: tuple[str, ...] = ()


def validate_effect_declarations(
    declarations: tuple[EffectDeclaration, ...],
) -> dict[str, tuple[str, ...]]:
    """Return fail-loud boundary violations keyed by capability name."""
    violations: dict[str, tuple[str, ...]] = {}
    for declaration in declarations:
        messages: list[str] = []
        if declaration.effect_class not in _KNOWN_EFFECT_CLASSES:
            messages.append(f"unsupported effect class: {declaration.effect_class!r}")
        effectful = declaration.effect_class in _EFFECTFUL_CLASSES
        if effectful and not _non_empty(declaration.owner_contract):
            messages.append("effectful capability requires a named owner contract")
        if effectful and not _non_empty(declaration.port):
            messages.append("effectful capability requires a named port")
        if declaration.effect_class == "none":
            if declaration.owner_contract or declaration.port:
                messages.append("pure capability must not claim an owner contract or port")
            if declaration.direct_effects:
                messages.append("pure capability must not contain direct effects")
        if declaration.direct_effects:
            messages.append("direct effects must be performed by the owner port")
        if messages:
            violations[declaration.name] = tuple(messages)
    return violations


def _non_empty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = ["EffectClass", "EffectDeclaration", "validate_effect_declarations"]
