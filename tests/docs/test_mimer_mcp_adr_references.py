"""Doc-truth guard for #4320: MCP planning anchors name ADR-0061, not "ADR-0058".

The `docs/MIMER_MCP_CLIENT_ADAPTER/` specification directory historically named the
MCP client-adapter decision "ADR-0058", but that number belongs to event-horizon
closure decay (`docs/adr/ADR-0058-event-horizon-closure-decay.md`). The actual
decision record is `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` (see its
"Numbering note"). This test keeps the spec directory pointed at ADR-0061 and pins
the owner-accepted A2/B1/C1 contract without treating acceptance as implementation.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO_ROOT / "docs" / "MIMER_MCP_CLIENT_ADAPTER"
ADR_0061 = REPO_ROOT / "docs" / "adr" / "ADR-0061-mimer-mcp-client-adapter.md"


def _spec_files() -> list[Path]:
    files = sorted(SPEC_DIR.glob("*.md"))
    assert files, f"missing MCP specification directory or files: {SPEC_DIR}"
    return files


def test_mimer_mcp_specs_reference_adr_0061() -> None:
    """No spec file may point at the nonexistent MCP "ADR-0058" record."""
    offenders: list[str] = []
    for path in _spec_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "ADR-0058" in line or "adr-0058" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "MCP specification files still reference the stale 'ADR-0058' name for the "
        "MCP client-adapter decision; the actual record is ADR-0061 "
        "(docs/adr/ADR-0061-mimer-mcp-client-adapter.md :: Numbering note):\n"
        + "\n".join(offenders)
    )

    # The decision references must resolve to the real ADR-0061 record.
    referencing = [
        path
        for path in _spec_files()
        if "ADR-0061" in path.read_text(encoding="utf-8")
    ]
    assert referencing, (
        "No MCP specification file references ADR-0061; the decision anchor was "
        "removed instead of corrected."
    )
    assert ADR_0061.exists(), f"missing decision record: {ADR_0061}"


def test_mimer_mcp_specs_preserve_accepted_owner_decision() -> None:
    """Accepted specs pin A2/B1/C1 while keeping runtime availability unclaimed."""
    assert ADR_0061.exists(), f"missing decision record: {ADR_0061}"
    adr_text = ADR_0061.read_text(encoding="utf-8")
    assert adr_text.startswith("State: Accepted"), (
        "ADR-0061 must open with the owner-accepted state after the #3371 decision."
    )
    assert "issuecomment-5375222455" in adr_text
    assert "A2 + B1 + C1 for v1" in adr_text
    assert "does not claim that an MCP server is shipped" in adr_text

    readme = (SPEC_DIR / "README.md").read_text(encoding="utf-8")
    assert (
        "owner-decision receipt" in readme
        and "the decision alone does not claim a running server" in readme
    ), (
        "README.md must preserve the decision receipt and keep runtime availability unclaimed."
    )

    ratify = (SPEC_DIR / "RATIFY_MCP_CLIENT_ADAPTER.md").read_text(encoding="utf-8")
    for selected_option in ("A2", "B1", "C1"):
        assert selected_option in ratify
    assert "runtime:  not implemented" in ratify

    for name in (
        "EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md",
        "PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md",
    ):
        text = (SPEC_DIR / name).read_text(encoding="utf-8")
        assert "stays blocked until #3371's Accepted ADR/client-contract writeback lands" in text, (
            f"{name} lost the downstream blocker: implementation issues stay blocked "
            "until the accepted docs contract lands and readiness is reconciled."
        )

    package = (SPEC_DIR / "PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md").read_text(
        encoding="utf-8"
    )
    assert "B1 stdio only" in package
    assert "opens no network listener" in package
    assert "Streamable HTTP over tailnet/LAN" in package
    assert "separately gated follow-ons" in package
