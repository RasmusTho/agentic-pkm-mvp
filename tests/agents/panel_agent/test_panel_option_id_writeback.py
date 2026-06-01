from __future__ import annotations

from app.agents.panel.parser import parse_panel
from app.agents.panel_agent.runtime import _write_proposals_to_panel


def _panel() -> str:
    return (
        "# Note\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Do something.\n"
        "## AI-åtgärder\n"
        "%% AI:End %%\n"
    )


def test_generated_proposal_lines_include_option_id() -> None:
    updated = _write_proposals_to_panel(
        _panel(),
        [("promote.evergreen", "Make this note evergreen")],
        option_id_factory=lambda: "opt_test_1",
    )

    assert "<!--ai:option_id=opt_test_1-->" in updated
    assert "<!--ai:id=" in updated
    assert "<!--ai:proposed=979-->" in updated
    parsed = parse_panel(updated)
    assert parsed.actions[0].option_id == "opt_test_1"


def test_rerun_does_not_duplicate_existing_proposal() -> None:
    first = _write_proposals_to_panel(
        _panel(),
        [("promote.evergreen", "Make this note evergreen")],
        option_id_factory=lambda: "opt_first",
    )
    second = _write_proposals_to_panel(
        first,
        [("promote.evergreen", "Make this note evergreen")],
        option_id_factory=lambda: "opt_second",
    )

    assert second.count("Make this note evergreen") == 1
    assert "opt_first" in second
    assert "opt_second" not in second


def test_duplicate_labels_get_distinct_option_ids_when_generated() -> None:
    ids = iter(["opt_a", "opt_b"])

    updated = _write_proposals_to_panel(
        _panel(),
        [
            ("proposal.one", "Duplicate label"),
            ("proposal.two", "Duplicate label"),
        ],
        option_id_factory=lambda: next(ids),
    )

    assert "<!--ai:option_id=opt_a-->" in updated
    assert "<!--ai:option_id=opt_b-->" in updated
