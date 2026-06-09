"""Write-capable co-authoring cognition for the canvas surface.

This cognition is the missing *author* behind ``CanvasWriter``: given a
user's natural-language intent plus the current note body (and optional
retrieval context), it produces a generated **body revision** via the shared
``ReasoningFacade`` (``app/reasoning/facade.py``).

It is deliberately distinct from ``read_only_cognition.py``:

- ``read_only_cognition`` plans/reasons only and is execution-denied.
- ``CoAuthoringCognition`` is authorized to produce body text — and *only*
  body text. It never emits frontmatter and never writes to disk itself.

The generated body is meant to be handed to ``CanvasWriter.apply_edit``,
which enforces the remaining guards (active session, in-vault note,
frontmatter rejection). This module additionally rejects a generation that
carries a frontmatter block early, raising
``GovernanceBearingMutationError`` so the caller routes it through
``GovernanceRouter`` rather than the in-place co-authoring path.

This is the co-authoring intent class from
``docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md``:
authorized by user presence, bounded to the open note's body, reversible,
and audited by the session log. It does not loosen
``STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.chat.canvas_writer import GovernanceBearingMutationError, _body_contains_frontmatter
from app.reasoning.facade import ReasoningFacade, get_reasoning_facade

# Sentinel prefixes emitted by the mock/degraded reasoning backend. When the
# facade is not backed by an edit-capable provider, ``answer`` returns a
# diagnostic string (e.g. ``MOCK_ASK_ANSWER: ...``) rather than an edited note
# body. Applying that text would corrupt the note, so it must be rejected.
_DEGRADED_GENERATION_PREFIXES = ("MOCK_ASK_ANSWER:", "MOCK_")


class CoAuthoringUnavailableError(Exception):
    """Raised when no edit-capable provider produced a usable body revision.

    Distinct from ``GovernanceBearingMutationError``: nothing about the
    generation is governance-bearing; the generation simply cannot be trusted
    as a real edit (mock/degraded backend, or an empty/failed run). Callers
    should surface this as a transient unavailability and leave the note
    unchanged rather than writing diagnostic text into the body.
    """


@dataclass(frozen=True)
class CoAuthoredBody:
    """Result of a co-authoring generation.

    ``body`` is body-only text safe to hand to ``CanvasWriter.apply_edit``.
    ``generated`` is ``True`` for a successfully produced revision; a
    cognition that cannot produce a usable edit raises
    ``CoAuthoringUnavailableError`` instead of returning a degraded result.
    """

    body: str
    generated: bool
    trace_id: str | None = None


class CoAuthoringCognition:
    """Turn ``{intent, current_body}`` into a generated note-body revision.

    The reasoning provider is injectable via ``facade_factory`` so tests can
    supply a deterministic stub instead of a live LLM provider.
    """

    def __init__(
        self,
        *,
        facade_factory: Callable[[], ReasoningFacade] = get_reasoning_facade,
    ) -> None:
        self._facade_factory = facade_factory

    def generate_body(
        self,
        *,
        intent: str,
        current_body: str,
        retrieval_context: str | None = None,
        trace_id: str | None = None,
    ) -> CoAuthoredBody:
        """Generate a new note body from the user's intent.

        Raises ``GovernanceBearingMutationError`` if the generated body
        contains a frontmatter block — that is a governance-bearing mutation
        and must route through ``GovernanceRouter``, never the co-authoring
        in-place write path.
        """
        facade = self._facade_factory()
        question = _build_question(intent)
        context = _build_context(current_body, retrieval_context)
        run = facade.answer(question, context=context, trace_id=trace_id)

        body = _extract_body(run)
        if body is None:
            # Failed/empty run: no usable edit. Do not fabricate or write back
            # the unchanged body silently; surface unavailability instead.
            raise CoAuthoringUnavailableError(
                "Co-authoring generation produced no usable body — the "
                "reasoning provider returned a failed or empty result."
            )

        # Guard: a mock/degraded backend returns a diagnostic string, not a
        # real edit. Applying it would corrupt the note, so reject it.
        if _is_degraded_generation(body):
            raise CoAuthoringUnavailableError(
                "Co-authoring requires an edit-capable LLM provider; the "
                "active reasoning backend returned a mock/diagnostic response "
                "instead of an edited note body."
            )

        # Body-only invariant: a generation containing frontmatter is
        # governance-bearing and must not be applied as co-authoring.
        if _body_contains_frontmatter(body):
            raise GovernanceBearingMutationError(
                "Co-authoring generation produced a frontmatter block — "
                "frontmatter changes are governance-bearing and must route "
                "through GovernanceRouter, not the in-place co-authoring path."
            )

        return CoAuthoredBody(body=body, generated=True, trace_id=trace_id)


def _build_question(intent: str) -> str:
    return (
        "You are co-authoring a single note's body during an active editing "
        "session. Rewrite the note body to satisfy the user's intent. Return "
        "ONLY the revised note body as Markdown. Do not emit YAML frontmatter, "
        "delimiters (---), or any commentary.\n\n"
        f"User intent: {intent.strip()}"
    )


def _build_context(current_body: str, retrieval_context: str | None) -> str:
    parts = ["Current note body:\n" + current_body]
    if retrieval_context and retrieval_context.strip():
        parts.append("Retrieval context:\n" + retrieval_context.strip())
    return "\n\n".join(parts)


def _is_degraded_generation(body: str) -> bool:
    """Return True if ``body`` is a mock/diagnostic response, not a real edit."""
    stripped = body.lstrip()
    return any(stripped.startswith(prefix) for prefix in _DEGRADED_GENERATION_PREFIXES)


def _extract_body(run: Any) -> str | None:
    """Pull body text from a ReasoningRun result, or ``None`` on failure."""
    if getattr(run, "status", None) != "ok":
        return None
    result = getattr(run, "result", None)
    if isinstance(result, dict):
        for key in ("answer", "body", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    if isinstance(result, str) and result.strip():
        return result
    return None


__all__ = ["CoAuthoredBody", "CoAuthoringCognition", "CoAuthoringUnavailableError"]
