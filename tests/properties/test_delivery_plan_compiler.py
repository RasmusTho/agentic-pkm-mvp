from __future__ import annotations

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings, strategies as st  # noqa: E402

from app.builderops.delivery_plan_compiler import (  # noqa: E402
    DeliveryDependency,
    compile_delivery_plan,
)
from tests.builderops.test_delivery_plan_compiler import (  # noqa: E402
    _fact,
    _initiation,
    _issue,
    _snapshot,
)


@settings(max_examples=30, deadline=None)
@given(
    issue_count=st.integers(min_value=1, max_value=8),
    max_parallel=st.integers(min_value=1, max_value=3),
    dependency_mask=st.lists(
        st.booleans(),
        min_size=7,
        max_size=7,
    ),
)
def test_compiled_waves_preserve_dependencies_and_budget(
    issue_count: int,
    max_parallel: int,
    dependency_mask: list[bool],
) -> None:
    issues = tuple(
        _issue(5500 + index, f"{index + 1:064x}")
        for index in range(issue_count)
    )
    facts = []
    declared_dependencies: list[tuple[int, int]] = []
    for index, issue in enumerate(issues):
        dependencies: tuple[DeliveryDependency, ...] = ()
        if index > 0 and dependency_mask[index - 1]:
            dependency = issues[index - 1]
            dependencies = (
                DeliveryDependency(
                    issue=dependency,
                    satisfied=False,
                ),
            )
            declared_dependencies.append((index - 1, index))
        facts.append(_fact(issue, dependencies=dependencies))

    result = compile_delivery_plan(
        _initiation(
            issues,
            max_parallel_workers=max_parallel,
        ),
        _snapshot(*facts),
    )

    assert result.plan is not None
    wave_by_issue = {
        issue.scope_key: wave.wave_index
        for wave in result.plan.dependency_waves
        for issue in wave.issues
    }
    assert all(
        len(wave.issues) <= max_parallel
        for wave in result.plan.dependency_waves
    )
    assert {
        issue.scope_key for issue in result.plan.final_scope
    } == set(wave_by_issue)
    for dependency_index, dependent_index in declared_dependencies:
        assert (
            wave_by_issue[issues[dependency_index].scope_key]
            < wave_by_issue[issues[dependent_index].scope_key]
        )
