"""Doc-truth guard for #4320: MCP planning anchors name ADR-0061, not "ADR-0058".

The `docs/MIMER_MCP_CLIENT_ADAPTER/` specification directory historically named the
MCP client-adapter decision "ADR-0058", but that number belongs to event-horizon
closure decay (`docs/adr/ADR-0058-event-horizon-closure-decay.md`). The actual
proposed decision record is `docs/adr/ADR-0061-mimer-mcp-client-adapter.md` (see its
"Numbering note"). This test keeps the spec directory pointed at ADR-0061 while
preserving the proposed, owner-decision-pending gate — the renumbering must never be
read as the MCP decision having been accepted.
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


def test_mimer_mcp_specs_preserve_proposed_owner_gate() -> None:
    """Corrected specs still state ADR-0061 is proposed and owner-decision pending."""
    assert ADR_0061.exists(), f"missing decision record: {ADR_0061}"
    adr_text = ADR_0061.read_text(encoding="utf-8")
    assert adr_text.startswith("State: Proposed"), (
        "ADR-0061 no longer opens with 'State: Proposed'; this guard only covers the "
        "pre-acceptance posture and must be revisited together with the owner receipt."
    )

    readme = (SPEC_DIR / "README.md").read_text(encoding="utf-8")
    assert "owner-decision receipt" in readme and "not an admitted Mimer client transport" in readme, (
        "README.md lost the owner-decision gate wording: MCP must stay non-admitted "
        "until an explicit owner-decision receipt accepts the proposed ADR-0061."
    )

    ratify = (SPEC_DIR / "RATIFY_MCP_CLIENT_ADAPTER.md").read_text(encoding="utf-8")
    assert "State: Proposed" in ratify or "State=Proposed" in ratify, (
        "RATIFY_MCP_CLIENT_ADAPTER.md no longer requires ADR-0061 to stay in "
        "Proposed state pending the owner ruling."
    )

    blocker_phrase = (
        "stays blocked until ADR-0061 is Accepted and links the explicit "
        "owner-decision receipt"
    )
    for name in (
        "EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md",
        "PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md",
    ):
        text = (SPEC_DIR / name).read_text(encoding="utf-8")
        assert blocker_phrase in text, (
            f"{name} lost the downstream blocker: implementation issues stay blocked "
            "until ADR-0061 is owner-accepted with a linked decision receipt."
        )
