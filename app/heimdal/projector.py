"""Mimer-side content-quarantine projector (Epic #3019 slice A3, #3040).

The projector is the Heimdal->Mimer read-model seam. It consumes published
observations from the append-only observation log **via the A2 cursor
contract** (``app.heimdal.publish.read_observations_for_consumer`` /
``consume_observations``) -- never by importing the log/cursor *store* modules
or reaching into the table directly (issue Constraints: "no direct DB imports
across boundaries"; FABLE_COMPANION §4.2).

Its single responsibility is the **content quarantine** that closes red-team
F2 and enforces HEIM-9 (``heim_observed_content_is_not_instruction``): every
observation's content is framed as **untrusted evidence**, **fence-neutralized**
(``app.heimdal.quarantine``), and projected into the existing candidate/triage
substrate as a ``requires_review: true``, non-authoritative candidate artifact.

Why the quarantine lives *here* (the seam), not in each consumer: this is the
one place observed content crosses from "operational record of occurrence"
into "agent-visible candidate". If the neutralization sat in N downstream
consumers, one forgetful consumer would reopen the injection surface. By
neutralizing at the projector and only ever emitting :class:`QuarantinedCandidate`
objects (which carry no raw, directive-capable content), no consumer path can
route raw observed content into an auto-executing prompt (HEIM-9). The
projector emits candidates; it does not -- and structurally cannot -- execute,
mutate, or grant on the basis of observed content.

Boundary/ownership: this slice does NOT define event-topic constants (A4). It
reads whatever the log carries via the cursor contract and pulls content out of
the observation payload's ``content.content`` field (FABLE_COMPANION §1.3
content family). It projects into the *existing* candidate substrate shape
(``app.knowledge_acquisition.candidate_writeback`` posture: non-authoritative,
``requires_review: true``, ``triage_state: captured``) and adds no new
persistence -- projected candidates are derived and rebuildable from the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

from app.heimdal.publish import (
    advance_cursor_for_consumer,
    read_observations_for_consumer,
)
from app.heimdal.quarantine import (
    EVIDENCE_ROLE_OBSERVED,
    QuarantinedContent,
    quarantine_observed_content,
)

#: The projector's cursor identity in the A2 per-consumer cursor store. A stable
#: id so the projector rebuilds from event zero on first run and resumes from
#: its own durable position thereafter (FABLE_COMPANION §4.2).
PROJECTOR_CONSUMER_ID = "mimer.content_quarantine_projector"

#: Posture stamped on every projected candidate -- mirrors the existing
#: candidate substrate (``candidate_writeback``) so observed content lands in
#: the SAME triage path as any other candidate, never a privileged one.
TRIAGE_STATE_CAPTURED = "captured"
REVIEW_STATE_DRAFT = "draft"


class ProjectionError(RuntimeError):
    """Raised when an observation cannot be projected into a candidate."""


@dataclass(frozen=True)
class QuarantinedCandidate:
    """A projected candidate carrying quarantined (untrusted) observed content.

    This is the ONLY object the projector emits into the candidate/triage
    substrate. It exposes the neutralized, fenced evidence text and the
    mandatory non-authoritative posture; it has no accessor that returns raw,
    directive-capable observed content. Downstream triage/prompt consumers see
    a review candidate, never a directive (HEIM-9).
    """

    observation_id: str
    topic: str
    quarantined: QuarantinedContent
    #: Non-authoritative posture, structurally fixed (HEIM-8/HEIM-9).
    evidence_role: str = EVIDENCE_ROLE_OBSERVED
    requires_review: bool = True
    source_authoritative: bool = False
    triage_state: str = TRIAGE_STATE_CAPTURED
    review_state: str = REVIEW_STATE_DRAFT
    #: Pass-through, non-content provenance/attribution the candidate may carry.
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_role != EVIDENCE_ROLE_OBSERVED:
            raise ProjectionError(
                f"projected candidate must carry evidence_role={EVIDENCE_ROLE_OBSERVED!r} "
                f"(HEIM-9), got {self.evidence_role!r}"
            )
        if self.requires_review is not True:
            raise ProjectionError("projected candidate must be requires_review=True (HEIM-8/HEIM-9)")
        if self.source_authoritative is not False:
            raise ProjectionError("projected candidate is never source_authoritative (HEIM-8)")

    def evidence_text(self) -> str:
        """The neutralized, fenced evidence text safe to render for review.

        This is the projector's ONLY content accessor. It returns quarantined
        text -- directive-inert, fenced, framed as untrusted evidence. There is
        deliberately no method returning the raw observed content.
        """
        return self.quarantined.fenced_text


def _extract_observed_content(envelope: Mapping[str, Any]) -> str:
    """Pull the observed content string out of an observation envelope.

    Reads ``payload.content.content`` (FABLE_COMPANION §1.3 content family:
    the minimized, published transcript text). Missing/empty content projects
    an empty candidate rather than raising -- an observation with withheld or
    empty content is still a valid record of occurrence.
    """
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    content_block = payload.get("content")
    if not isinstance(content_block, Mapping):
        return ""
    text = content_block.get("content")
    return text if isinstance(text, str) else ""


def _observation_id(envelope: Mapping[str, Any]) -> str:
    payload = envelope.get("payload")
    if isinstance(payload, Mapping):
        obs_id = payload.get("observation_id")
        if isinstance(obs_id, str) and obs_id.strip():
            return obs_id
    ev_id = envelope.get("event_id")
    return str(ev_id) if ev_id else "unknown"


def _provenance(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = envelope.get("payload")
    if isinstance(payload, Mapping):
        prov = payload.get("provenance")
        if isinstance(prov, Mapping):
            # Content-free provenance only; content itself is quarantined
            # separately and never copied verbatim into metadata.
            return dict(prov)
    return {}


def project_observation(envelope: Mapping[str, Any], *, topic: str = "") -> QuarantinedCandidate:
    """Project ONE observation envelope into a quarantined candidate.

    This is the neutralization point: the observation's content is run through
    :func:`app.heimdal.quarantine.quarantine_observed_content` (fence-neutralized,
    framed as untrusted evidence) BEFORE it is placed in the candidate. The
    returned candidate is non-authoritative and ``requires_review``; no raw,
    directive-capable content leaves this function.
    """
    if not isinstance(envelope, Mapping):
        raise ProjectionError(f"observation envelope must be a mapping, got {type(envelope)!r}")
    observed = _extract_observed_content(envelope)
    quarantined = quarantine_observed_content(observed)
    resolved_topic = topic or str(envelope.get("event") or envelope.get("event_type") or "")
    return QuarantinedCandidate(
        observation_id=_observation_id(envelope),
        topic=resolved_topic,
        quarantined=quarantined,
        provenance=_provenance(envelope),
    )


def project_pending_observations(
    *,
    consumer_id: str = PROJECTOR_CONSUMER_ID,
    limit: int | None = None,
    advance: bool = True,
) -> List[QuarantinedCandidate]:
    """Read pending observations via the A2 cursor contract and quarantine each.

    THE production projector call site. Reads the next unread batch for
    ``consumer_id`` through ``app.heimdal.publish.read_observations_for_consumer``
    (the only sanctioned read path -- no store/table import), projects each into
    a :class:`QuarantinedCandidate`, and advances the projector's own cursor
    past the processed batch (unless ``advance=False``, e.g. dry-run/replay).

    Every returned candidate is fence-neutralized, ``requires_review``, and
    non-authoritative. There is no branch in this function that inspects the
    observed content and takes an action on its basis -- the projector cannot
    be commanded by what it projects (HEIM-9).
    """
    rows = read_observations_for_consumer(consumer_id, limit=limit)
    candidates = [project_observation(row.envelope, topic=row.topic) for row in rows]
    if advance and rows:
        advance_cursor_for_consumer(consumer_id, rows)
    return candidates


__all__ = [
    "PROJECTOR_CONSUMER_ID",
    "REVIEW_STATE_DRAFT",
    "TRIAGE_STATE_CAPTURED",
    "ProjectionError",
    "QuarantinedCandidate",
    "project_observation",
    "project_pending_observations",
]
