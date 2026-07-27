"""The two reasoning facades must not share a name.

``app/reasoning/facade.py`` and ``app/components/reasoning/facade.py`` hold
unrelated classes with no method overlap: the former is a thin dispatcher over
``run_reasoning`` used by Chat/canvas, the latter is the LLM task client with
routing and telemetry used by the LangGraph agents. Both were once named
``ReasoningFacade`` and exposed by a factory named ``get_reasoning_facade``, so
``from ... import get_reasoning_facade`` silently returned a different object
depending on the module path and no import error ever fired.

That collision is not cosmetic. It is why the missing ``PLANNING`` branch (D1 in
``docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md``) went unnoticed: planning
*was* implemented on the components facade, so the dead ``plan()`` on the other
one looked covered. This guard keeps the names apart.
"""

from __future__ import annotations

import pytest

from app.components.reasoning import facade as components_facade
from app.reasoning import facade as mode_facade

pytestmark = pytest.mark.not_pg


def test_facade_class_and_factory_names_do_not_collide() -> None:
    mode_cls = mode_facade.ReasoningModeFacade
    components_cls = components_facade.ReasoningFacade

    assert mode_cls.__name__ != components_cls.__name__, (
        "the two reasoning facades share a class name again; an importer "
        "cannot tell them apart and gets a silently different object"
    )
    assert (
        mode_facade.get_reasoning_mode_facade.__name__
        != components_facade.get_reasoning_facade.__name__
    ), "the two reasoning facade factories share a name again"


def test_mode_facade_no_longer_exports_the_colliding_names() -> None:
    # A backward-compatible alias would reintroduce exactly the ambiguity this
    # guard exists to prevent, so absence is asserted, not just distinctness.
    for gone in ("ReasoningFacade", "get_reasoning_facade"):
        assert not hasattr(mode_facade, gone), (
            f"app/reasoning/facade.py re-exports {gone!r}; that restores the "
            "collision with app/components/reasoning/facade.py"
        )
        assert gone not in (mode_facade.__all__ or ()), (
            f"{gone!r} is still advertised in app/reasoning/facade.py __all__"
        )


def test_the_two_facades_remain_behaviourally_distinct() -> None:
    """Guard the premise: these are different objects, not duplicates.

    If the two ever converge on the same surface, the right fix is to merge
    them deliberately rather than to keep two names — so make that visible.
    """
    mode_methods = {m for m in dir(mode_facade.ReasoningModeFacade) if not m.startswith("_")}
    components_methods = {
        m for m in dir(components_facade.ReasoningFacade) if not m.startswith("_")
    }
    assert not (mode_methods & components_methods), (
        "the two reasoning facades now share public methods; revisit whether "
        "they should be one class instead of two names"
    )
