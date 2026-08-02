"""Fitness gate: PR test selection must not open a false-green window on the
shared agent-state authority/trace spine.

`tests/architecture/test_agent_state_spine.py` and `tests/agents/test_runtime_state_contract.py`
are the only two suites in the repo that assert every class in `_KNOWN_AGENT_STATE_CLASSES`
carries the `RuntimeStateModel` authority/trace spine. `scripts/select_pr_tests.py` decides which
suites a scoped PR actually runs. A subsystem that OWNS the module defining one of these classes
but omits both spine gates from its test targets creates a false-green window: a PR that drops the
spine from that class selects a green suite and merges, because the one gate that would catch the
regression never runs.

This is different from an UNOWNED path, which already fails closed (`select_tests` returns it in
`unowned_paths`, and `scripts/select_pr_tests.py::main` exits 2) and is therefore noisy but safe.

Fixed for `promotion_panel` in #4501 (the same defect class closed for `ask` in PR #4495 / #2921).

Source anchors:
    scripts/select_pr_tests.py -- SUBSYSTEMS, select_tests
    tests/architecture/test_agent_state_spine.py -- _KNOWN_AGENT_STATE_CLASSES
    Issue #4501
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from scripts.select_pr_tests import select_tests
from tests.architecture.test_agent_state_spine import _KNOWN_AGENT_STATE_CLASSES

REPO_ROOT = Path(__file__).resolve().parents[2]

# The only two suites in the repo that assert the shared RuntimeStateModel
# authority/trace spine (see module docstring above and the `ask` subsystem's
# inline rationale in scripts/select_pr_tests.py).
SPINE_GATES = (
    "tests/architecture/test_agent_state_spine.py",
    "tests/agents/test_runtime_state_contract.py",
)


def _module_source_path(cls: type) -> str:
    """Return the repo-relative source path of the module that defines ``cls``."""

    module = importlib.import_module(cls.__module__)
    module_file = getattr(module, "__file__", None)
    assert module_file, f"{cls.__module__} has no __file__; cannot resolve its owning path"
    return str(Path(module_file).resolve().relative_to(REPO_ROOT))


def _assert_state_class_is_gated_or_fail_closed(cls: type) -> None:
    """A state class's defining module must either:

    - be owned by a subsystem whose PR-scoped selection includes BOTH spine gates, or
    - be unowned, which already fails closed (exit 2) and needs no gate.

    Raises ``AssertionError`` (with a diagnostic naming the class, its module, the resolved
    subsystem, and the missing gate(s)) when neither condition holds -- this is the mechanism
    that makes a future omission detectable instead of silently passing.
    """

    path = _module_source_path(cls)
    selection = select_tests([path])

    if selection.unowned_paths:
        assert path in selection.unowned_paths
        return

    missing = [gate for gate in SPINE_GATES if gate not in selection.targets]
    assert not missing, (
        f"{cls.__module__}.{cls.__qualname__} is defined in {path!r}, owned by subsystem(s) "
        f"{selection.subsystems!r}, but that subsystem's PR test selection omits spine gate(s) "
        f"{missing!r}. A change dropping the RuntimeStateModel authority/trace spine from this "
        "class would merge with a green selection. Add the missing gate(s) to the owning "
        "subsystem's test targets in scripts/select_pr_tests.py."
    )


def test_state_owning_subsystems_select_the_spine_gates() -> None:
    """A diff touching app/agents/panel_agent/state.py must select both spine gates."""

    selection = select_tests(["app/agents/panel_agent/state.py"])

    assert not selection.unowned_paths
    assert "promotion_panel" in selection.subsystems
    for gate in SPINE_GATES:
        assert gate in selection.targets, (
            f"promotion_panel selection is missing spine gate {gate!r}; a PR touching "
            "app/agents/panel_agent/state.py can drop the authority/trace spine and merge green."
        )


def test_every_known_agent_state_class_is_gated_or_fail_closed() -> None:
    """Every class in `_KNOWN_AGENT_STATE_CLASSES` is either gated by its owning subsystem's PR
    selection or provably unowned (fail-closed)."""

    for cls in _KNOWN_AGENT_STATE_CLASSES:
        _assert_state_class_is_gated_or_fail_closed(cls)


def test_new_state_class_without_selector_coverage_fails() -> None:
    """Recurrence guard: a state class whose module is OWNED by a subsystem that omits the spine
    gates must fail `_assert_state_class_is_gated_or_fail_closed`, not pass silently.

    `app.episodes.closure.EpisodeCloseCandidate` is not itself a runtime agent-state class; it
    stands in for a hypothetical future addition to `_KNOWN_AGENT_STATE_CLASSES` whose module
    (`app/episodes/closure.py`) is owned by the `episodes` subsystem, whose PR test targets do not
    include either spine gate. This proves the fitness mechanism above -- the same one
    `test_every_known_agent_state_class_is_gated_or_fail_closed` runs over the real class list --
    actually catches an unwired omission instead of passing it through.
    """

    from app.episodes.closure import EpisodeCloseCandidate

    path = _module_source_path(EpisodeCloseCandidate)
    selection = select_tests([path])
    assert not selection.unowned_paths, (
        f"{path} became unowned; pick a different owned-but-ungated stand-in module for this test"
    )
    assert not any(gate in selection.targets for gate in SPINE_GATES), (
        f"{path}'s owning subsystem now selects a spine gate; pick a different stand-in module "
        "that still demonstrates the omission this test guards against"
    )

    with pytest.raises(AssertionError):
        _assert_state_class_is_gated_or_fail_closed(EpisodeCloseCandidate)
