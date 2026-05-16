"""Canvas Core active artifact body shell contract.

The active note/artifact body is the primary Canvas working surface.
The session transcript/provenance is subordinate to the note.

Layout regions are declared here at the model/contract level so future
rendering implementations have a stable surface contract to target.
Region names are authoritative across desktop and portrait/mobile layouts.

This module does NOT implement:
- Panel rendering or Panel confirmation.
- Canvas bounded suggestion flow components.
- Body-edit mutation or undo stack.
- Session provenance write/read.
"""

from __future__ import annotations


# Canonical layout region identifiers for Canvas Core.
# These become data-testid values in the HTML shell and CSS selector anchors.
REGION_ARTIFACT_BODY = "canvas-artifact-body"          # primary surface
REGION_SESSION_CONTROLS = "canvas-session-controls"    # future session UX (start/pause/close)
REGION_PROVENANCE = "canvas-provenance"                # subordinate transcript/intent trail
REGION_ESCAPE_HATCH = "canvas-escape-hatch"            # governance-bearing action routing


class CanvasArtifactShell:
    """Model contract for the active artifact body shell.

    Carries:
    - artifact identity (id + display title) so Canvas session state can bind to it,
    - artifact body text (the canonical working surface),
    - layout region declarations for session controls, provenance, and escape hatch,
    - portrait anchor flag asserting the artifact body remains the cognitive anchor
      on narrow/mobile layouts.
    """

    def __init__(
        self,
        *,
        artifact_id: str,
        artifact_title: str,
        body: str = "",
    ) -> None:
        self.artifact_id = artifact_id
        self.artifact_title = artifact_title
        self.body = body

        # Layout regions declared at model level — rendering is deferred.
        self.regions: dict[str, str] = {
            REGION_ARTIFACT_BODY:    "primary",
            REGION_SESSION_CONTROLS: "slot",
            REGION_PROVENANCE:       "subordinate",
            REGION_ESCAPE_HATCH:     "slot",
        }

        # Portrait/mobile: artifact body is the cognitive anchor.
        # A portrait layout must keep REGION_ARTIFACT_BODY visible when the
        # session controls / provenance sheet is in a collapsed or peek snap.
        self.portrait_artifact_anchor = True

    @property
    def identity(self) -> dict[str, str]:
        """Minimal identity payload for Canvas session binding."""
        return {"artifact_id": self.artifact_id, "artifact_title": self.artifact_title}

    def region_role(self, region: str) -> str:
        """Return the declared role for a layout region."""
        if region not in self.regions:
            raise KeyError(f"Unknown Canvas layout region: {region!r}")
        return self.regions[region]
