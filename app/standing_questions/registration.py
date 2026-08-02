"""Friction-free registration of standing questions (SQ-02).

Two paths into the SQ-01 store, per
``docs/STANDING_QUESTIONS/REGISTER_QUESTIONS_FRICTION_FREE.md``:

- **Path (a) — capture intent.** :func:`propose_question_registration` classifies a
  capture with the fenced capture-intent cognition and, on a validated
  ``question_registration``, writes **one unchecked suggested checkbox** into the
  capture note's own ``AI-åtgärder`` section through the existing PanelAgent
  write-back (PA2-SUGGESTED-CHECKBOXES). It never creates a Question note.
  :func:`confirm_question_registrations` is the other half: it reads the capture
  note back and registers only the proposals a **human has checked**.
- **Path (b) — explicit.** :func:`register_question_explicitly` writes straight
  through the SQ-01 guarded seam. Taking the companion-UI action *is* the human
  confirmation, so there is nothing to propose.

Invariants held here (each covered by a test that fails when the guard is removed):

- **The classifier can never bypass the checkbox.** There is no code path in this
  module from a classification to :meth:`QuestionStore.create_question`. Path (a)'s
  only write is an unchecked ``- [ ]`` line; the only function that creates a note
  from a capture is :func:`confirm_question_registrations`, and it registers a
  proposal only when :func:`~app.agents.panel.writeback.parse_action_line` reports
  it checked.
- **Question text is never fabricated.** The cognition already refuses a
  non-verbatim extraction; confirmation re-checks the label against the live
  capture text, so a hand-edited or tampered label cannot become a Question note
  either. Path (b) stores the human's own words unchanged.
- **Idempotent proposals and registrations.** The proposal is keyed by
  ``sha256(capture_id, extracted_text)``, embedded in the checkbox label, so the
  panel write-back's own dedupe makes re-classification a no-op. The Question note
  minted on confirmation carries a UUIDv5 derived from the same key, so a repeated
  confirmation lands on SQ-01's existing ``FileExistsError`` backstop instead of a
  duplicate note.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.panel.parser import is_ai_fence
from app.agents.panel.writeback import parse_action_line
from app.agents.panel_agent.runtime import _write_proposals_to_panel
from app.components.llm.constrained import CompletionFn
from app.components.llm.question_intent_classifier import (
    QuestionIntentClass,
    QuestionIntentClassification,
    QuestionIntentClassifierCognition,
)
from app.knowledge.contracts import WriteReceipt
from app.standing_questions.question_store import QuestionStore
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

_LOGGER = logging.getLogger(__name__)

#: Named WriteGuard action for path (a)'s proposal write seam — auditable, not a
#: silent absence of a guard. Dotted ``<module>.<verb>`` convention, mirroring
#: ``curation.propose_write`` and SQ-01's ``standing_questions.write_note``.
REGISTRATION_PROPOSE_WRITE_ACTION = "standing_questions.propose_registration"

#: Swedish label prefix, matching the `AI-åtgärder` surface convention. It is also
#: the selector confirmation uses to find this task's proposals among any other
#: checkboxes on the capture note.
REGISTRATION_LABEL_PREFIX = "Registrera stående fråga: "

#: Stable namespace for the deterministic Question id minted on confirmation.
#: Fixed forever: changing it would let an already-registered capture register a
#: second time.
_REGISTRATION_NAMESPACE = uuid.UUID("6f9a1c2e-4d3b-4a55-9c7e-2b8f1d0a7e34")


@dataclass(frozen=True)
class RegistrationProposalResult:
    """Outcome of one path (a) classification pass over one capture note.

    ``written`` is ``False`` both when nothing was proposed and when the proposal
    was already present (the idempotent rerun), so a caller can distinguish "no
    intent" from "already offered" through ``proposal_id``.
    """

    classification: QuestionIntentClassification
    proposal_id: str | None = None
    extracted_text: str | None = None
    label: str | None = None
    written: bool = False


@dataclass(frozen=True)
class RegistrationConfirmResult:
    """Outcome of one confirmation pass over one capture note."""

    created: tuple[dict[str, Any], ...] = ()
    unchecked: int = 0
    already_registered: int = 0
    refused_non_verbatim: int = 0


def capture_human_text(markdown: str) -> str:
    """Return the capture with every ``%% AI:… %%`` panel block removed.

    The panel is machine surface: it holds this task's own proposal lines and any
    other agent's suggestions. Two things depend on excluding it, and both are
    correctness rather than tidiness:

    - the classifier is fenced on the human's actual capture, so a second pass
      cannot "extract" a question out of a proposal an earlier pass wrote;
    - the verbatim check has a fixed point. Checking against the whole file would
      make any label trivially verbatim — the label is *in* the file — so a
      hand-edited or tampered label would validate itself.
    """
    kept: list[str] = []
    inside_panel = False
    for line in markdown.splitlines():
        if is_ai_fence(line):
            inside_panel = not inside_panel
            continue
        if not inside_panel:
            kept.append(line)
    return "\n".join(kept)


def _capture_identity(capture_note_path: Path, vault_root: Path) -> str:
    """Stable id for the source capture: its frontmatter uuid, else its path.

    Mirrors ``app.curation.lint._note_identity``: a uuid is advisory lineage
    metadata, never a processing gate, so a uuid-less capture still gets a stable
    proposal key rather than being skipped.
    """
    try:
        metadata, _body = load_frontmatter(capture_note_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = {}
    note_uuid = metadata.get("uuid") if isinstance(metadata, dict) else None
    if isinstance(note_uuid, str) and note_uuid.strip():
        return note_uuid.strip()
    try:
        return f"path:{capture_note_path.resolve().relative_to(vault_root).as_posix()}"
    except ValueError:
        return f"path:{capture_note_path.name}"


def _proposal_key(capture_id: str, extracted_text: str) -> str:
    return f"{capture_id}::{extracted_text}"


def proposal_id_for(capture_id: str, extracted_text: str) -> str:
    """Idempotency key for a registration proposal (spec: ``hash(capture_id, text)``)."""
    digest = hashlib.sha256(_proposal_key(capture_id, extracted_text).encode("utf-8"))
    return digest.hexdigest()


def _question_id_for(capture_id: str, extracted_text: str) -> str:
    """Deterministic Question id, so a repeated confirmation cannot duplicate a note."""
    return f"sq-{uuid.uuid5(_REGISTRATION_NAMESPACE, _proposal_key(capture_id, extracted_text))}"


def _proposal_label(extracted_text: str, proposal_id: str) -> str:
    """Self-contained checkbox label: the question plus its short proposal id.

    The short id makes the label unique per (capture, question) pair, which is what
    the panel write-back's own dedupe keys on — the same discipline
    ``app.curation.proposal_writer`` uses for finding ids.
    """
    return f'{REGISTRATION_LABEL_PREFIX}"{extracted_text}" (förslag {proposal_id[:12]})'


def _extracted_text_from_label(label: str) -> str | None:
    """Recover the question from a proposal label, or ``None`` if it does not parse."""
    if not label.startswith(REGISTRATION_LABEL_PREFIX):
        return None
    remainder = label[len(REGISTRATION_LABEL_PREFIX) :].strip()
    if not remainder.startswith('"'):
        return None
    # rsplit on the trailing suffix so a question containing a quote still parses.
    closing = remainder.rfind('" (förslag ')
    if closing <= 0:
        return None
    return remainder[1:closing]


def propose_question_registration(
    *,
    capture_note_path: Path | str,
    vault_root: Path | str,
    classifier: QuestionIntentClassifierCognition | None = None,
    complete: CompletionFn | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    trace_id: str | None = None,
) -> RegistrationProposalResult:
    """Classify a capture and, if it registers a question, offer an unchecked checkbox.

    This is path (a)'s production entrypoint. It **never** creates a Question note:
    the only durable effect it can have is one unchecked ``- [ ]`` line on the
    capture note itself.
    """
    resolved_root = Path(vault_root).expanduser().resolve()
    capture_path = Path(capture_note_path).expanduser().resolve()
    capture_text = capture_path.read_text(encoding="utf-8")
    human_text = capture_human_text(capture_text)

    cognition = classifier if classifier is not None else QuestionIntentClassifierCognition(
        completion=complete
    )
    classification = cognition.classify(capture_text=human_text, trace_id=trace_id)
    if classification.intent_class is not QuestionIntentClass.QUESTION_REGISTRATION:
        # UNKNOWN and not_a_question_registration are both non-admitting: no
        # proposal, no write, no note.
        return RegistrationProposalResult(classification=classification)

    extracted = classification.extracted_text
    # The cognition only returns QUESTION_REGISTRATION with a verbatim extraction;
    # re-checking it here keeps the guarantee local to the write path too, so an
    # injected classifier cannot smuggle fabricated text past this seam.
    if extracted is None or extracted not in human_text:
        _LOGGER.warning(
            "Refused a Standing Questions registration proposal whose text is not "
            "verbatim in its capture: %s",
            capture_path,
        )
        return RegistrationProposalResult(classification=classification)

    capture_id = _capture_identity(capture_path, resolved_root)
    proposal_id = proposal_id_for(capture_id, extracted)
    label = _proposal_label(extracted, proposal_id)

    # Guard at the seam, before any filesystem mutation.
    write_guard.assert_writes_allowed(REGISTRATION_PROPOSE_WRITE_ACTION)
    updated = _write_proposals_to_panel(capture_text, [(proposal_id, label)])
    if updated == capture_text:
        # Already proposed on an earlier pass — idempotent no-op, no write.
        return RegistrationProposalResult(
            classification=classification,
            proposal_id=proposal_id,
            extracted_text=extracted,
            label=label,
        )
    capture_path.write_text(updated, encoding="utf-8")
    return RegistrationProposalResult(
        classification=classification,
        proposal_id=proposal_id,
        extracted_text=extracted,
        label=label,
        written=True,
    )


def confirm_question_registrations(
    *,
    capture_note_path: Path | str,
    vault_root: Path | str,
    scope: str,
    store: QuestionStore | None = None,
) -> RegistrationConfirmResult:
    """Register every proposal the human has **checked** on this capture note.

    An unchecked proposal is left exactly as it is. This is the only function in
    this module that can turn a capture into a Question note, and it acts on the
    checkbox state, never on a classification.
    """
    resolved_root = Path(vault_root).expanduser().resolve()
    capture_path = Path(capture_note_path).expanduser().resolve()
    capture_text = capture_path.read_text(encoding="utf-8")
    human_text = capture_human_text(capture_text)
    question_store = store if store is not None else QuestionStore(resolved_root)
    capture_id = _capture_identity(capture_path, resolved_root)

    created: list[dict[str, Any]] = []
    unchecked = 0
    already_registered = 0
    refused_non_verbatim = 0

    for line in capture_text.splitlines():
        parsed = parse_action_line(line.strip())
        if parsed is None or not parsed.label.startswith(REGISTRATION_LABEL_PREFIX):
            continue
        if not parsed.checked:
            unchecked += 1
            continue
        extracted = _extracted_text_from_label(parsed.label)
        # Re-check verbatimness against the live capture: the label is editable
        # text in the human's vault, so a tampered or rewritten label must not be
        # able to author a Question note.
        if extracted is None or extracted not in human_text:
            _LOGGER.warning(
                "Refused a checked Standing Questions registration whose text is not "
                "verbatim in its capture: %s",
                capture_path,
            )
            refused_non_verbatim += 1
            continue
        try:
            note, _receipt = question_store.create_question(
                text=extracted,
                scope=scope,
                registered_via="capture_intent",
                question_id=_question_id_for(capture_id, extracted),
            )
        except FileExistsError:
            # Deterministic id + SQ-01's existing existence check = idempotency.
            already_registered += 1
            continue
        created.append(note)

    return RegistrationConfirmResult(
        created=tuple(created),
        unchecked=unchecked,
        already_registered=already_registered,
        refused_non_verbatim=refused_non_verbatim,
    )


def register_question_explicitly(
    *,
    text: str,
    scope: str,
    vault_root: Path | str,
    store: QuestionStore | None = None,
) -> tuple[dict[str, Any], WriteReceipt]:
    """Path (b): register a question the human stated directly.

    No proposal, no confirm step, no classifier — the human already confirmed by
    taking the action, and ``text`` is their own words stored unchanged.
    """
    question_text = text.strip()
    if not question_text:
        raise ValueError("explicit registration requires non-empty question text")
    resolved_root = Path(vault_root).expanduser().resolve()
    question_store = store if store is not None else QuestionStore(resolved_root)
    return question_store.create_question(
        text=question_text,
        scope=scope,
        registered_via="explicit",
    )


__all__ = [
    "REGISTRATION_LABEL_PREFIX",
    "REGISTRATION_PROPOSE_WRITE_ACTION",
    "RegistrationConfirmResult",
    "RegistrationProposalResult",
    "confirm_question_registrations",
    "propose_question_registration",
    "proposal_id_for",
    "register_question_explicitly",
]
