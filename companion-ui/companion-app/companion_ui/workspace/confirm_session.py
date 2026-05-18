"""Panel confirm → artifact refresh session model (#1065).

Connects the Companion UI layer to the Panel confirm API and the artifact
read endpoint. The UI remains a pure API consumer — no vault file access.

Contracts consumed:
- POST /api/panel/confirm  (panel confirmation endpoint, #1053)
- GET  /api/artifacts/note (read-only artifact endpoint, #1063)

This module does NOT:
- read or write vault files directly
- implement proposal generation or staging UI
- add Canvas bounded suggestions or body-edit
- make real HTTP calls (requires an injected http_client)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


# ---------------------------------------------------------------------------
# HTTP client protocol — injected so tests can use stubs
# ---------------------------------------------------------------------------


class HttpClient(Protocol):
    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        ...

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Response / payload types
# ---------------------------------------------------------------------------


@dataclass
class ConfirmOutcome:
    """Typed result from POST /api/panel/confirm."""

    status: str           # "executed" | "blocked" | "rejected" | "logged"
    proposal_id: str
    artifact_id: str
    receipt: Optional[dict[str, Any]] = None
    block_reason: Optional[dict[str, Any]] = None
    events_emitted: list[str] = field(default_factory=list)

    @property
    def is_executed(self) -> bool:
        return self.status == "executed"

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def block_gate(self) -> Optional[str]:
        if self.block_reason:
            return self.block_reason.get("gate")
        return None


@dataclass
class ArtifactPayload:
    """Note payload received from GET /api/artifacts/note."""

    artifact_id: str
    note_path: str
    title: str
    body: str
    content_hash: str


# ---------------------------------------------------------------------------
# Workspace confirm session
# ---------------------------------------------------------------------------


class WorkspaceConfirmSession:
    """Companion UI session model for Panel confirm → artifact refresh flow.

    Call confirm() to:
    1. POST to /api/panel/confirm with the staged proposal
    2. Record the typed result
    3. Reload the artifact note payload via GET /api/artifacts/note

    After confirm(), inspect last_result and current_payload.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client
        self.last_result: Optional[ConfirmOutcome] = None
        self.current_payload: Optional[ArtifactPayload] = None

    def confirm(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
        action: str,
        idempotency_key: str,
    ) -> ConfirmOutcome:
        """Submit Panel confirm request and refresh artifact payload."""
        raw = self._http.post(
            "/api/panel/confirm",
            json={
                "proposal_id": proposal_id,
                "artifact_id": artifact_id,
                "action": action,
                "idempotency_key": idempotency_key,
            },
        )
        result = ConfirmOutcome(
            status=raw.get("status", ""),
            proposal_id=raw.get("proposal_id", proposal_id),
            artifact_id=raw.get("artifact_id", artifact_id),
            receipt=raw.get("receipt"),
            block_reason=raw.get("block_reason"),
            events_emitted=raw.get("events_emitted") or [],
        )
        self.last_result = result

        # Always reload artifact payload after any confirm response
        self._refresh_artifact(note_path=note_path, artifact_id=artifact_id)

        return result

    def _refresh_artifact(self, *, note_path: str, artifact_id: str) -> None:
        raw = self._http.get(
            "/api/artifacts/note",
            params={"note_path": note_path, "artifact_id": artifact_id},
        )
        self.current_payload = ArtifactPayload(
            artifact_id=raw.get("artifact_id", artifact_id),
            note_path=raw.get("note_path", note_path),
            title=raw.get("title", ""),
            body=raw.get("body", ""),
            content_hash=raw.get("content_hash", ""),
        )
