"""Governance coverage for the Autonomous Operations Companion handoff."""

from pathlib import Path


HANDOFF = Path("companion-ui/docs/design-handoffs/autonomous-operations/README.md")


def _read_handoff() -> str:
    return HANDOFF.read_text(encoding="utf-8")


def test_handoff_maps_human_flow_and_components() -> None:
    handoff = _read_handoff()

    assert "## Human-flow and Companion-surface map" in handoff
    for stage in (
        "Discover and select",
        "State an outcome",
        "Inspect scope",
        "Delegate once",
        "Execute and observe",
        "Review outcome",
        "Recover or correct",
    ):
        assert stage in handoff
    for surface in ("Workspace shell", "Vault Browser", "Panel", "Chat"):
        assert surface in handoff
    assert "server declares; UI renders" in handoff


def test_handoff_covers_failure_and_recovery_states() -> None:
    handoff = _read_handoff()

    assert "## Failure and recovery states" in handoff
    for state in (
        "Loading",
        "Empty",
        "Denial",
        "Conflict",
        "Partial failure",
        "Cancellation",
        "Restart",
        "Recovery",
    ):
        assert state in handoff
    assert "convergence_pending" in handoff
    assert "must not imply success" in handoff


def test_handoff_covers_accessibility_and_responsive_behavior() -> None:
    handoff = _read_handoff()

    assert "## Accessibility and responsive behavior" in handoff
    for behavior in (
        "keyboard",
        "focus",
        "screen reader",
        "200% zoom",
        "narrow viewport",
        "wide viewport",
    ):
        assert behavior in handoff
    assert "## Review evidence" in handoff


def test_handoff_records_validation_without_shipped_claim() -> None:
    handoff = _read_handoff()

    assert "## Design validation receipt" in handoff
    assert "yggdrasil-design-handoff" in handoff
    assert "No runtime delivery is claimed" in handoff
    assert "Live design-system gate: not invoked" in handoff
