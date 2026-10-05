"""Intent-classification golden-set evaluation (KERNEL-13, #2775).

Scores the bilingual `classification_case.v1` golden set
(`docs/eval/classification_golden.yaml`, authored under RESEARCH-06 / #2784)
against the real classifier path `app.components.llm.intent_classifier`
(`IntentClassifierCognition.classify`), per
`docs/RUNTIME_CORRECTNESS_KERNEL/INTENT_CLASSIFICATION_GOLDEN_SET.md`.

Two explicitly different targets:

- Deterministic CI replays authored labels as synthetic typed Product results.
  The real classifier validates and maps them, including UNKNOWN and confidence
  handling. This is mapping/contract proof, not measured provider quality.
- Live mode is the opt-in legacy completion comparator using the existing exact
  OpenAI eval route. Its model, billing and content gates are unchanged. It never
  impersonates TypeSafe or supplies a fallback for the Product classifier.

Scoring semantics (from the dataset header, binding):

- ``unknown`` is scored as **safe-fail**, never as a wrong class: a predicted
  ``UNKNOWN`` on an answerable case is excluded from per-class recall
  denominators and reported separately (``safe_fail`` / ``answer_rate``).
- A case passes when the predicted class equals ``expected_intent`` or is
  listed in ``acceptable`` (read-side tolerance only).
- **HARD GATE:** any case with ``expected_intent`` in {exploratory, unknown}
  that is classified into an action-capable class (co_authoring,
  governance_bearing) is a mutation-side confusion — a blocking regression,
  not a thresholded metric. Read-side confusion is thresholded via
  `config/eval_thresholds.yaml :: classification`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml
from llm_contract import ChoiceQuestion

from app.components.llm.intent_classifier import GovernanceActionType, IntentClass, IntentClassifierCognition
from app.model_access.product_judgment_contract import ProductJudgmentResult, product_intent_request
from app.components.llm.constrained import (
    CompletionFn, ConstrainedCompletionError, constrained_completion, register_schema, validate_payload,
)

CLASSIFICATION_GOLDEN_PATH = Path("docs") / "eval" / "classification_golden.yaml"
CLASSIFICATION_REPLAY_PATH = Path("docs") / "eval" / "classification_replay.yaml"

CASE_SCHEMA_VERSION = "classification_case.v1"
REPLAY_SCHEMA_VERSION = "classification_replay.v1"

#: Classes the model may emit (``UNKNOWN`` is local-only, never emittable).
EMITTABLE_CLASSES: tuple[str, ...] = (
    IntentClass.CO_AUTHORING.value,
    IntentClass.GOVERNANCE_BEARING.value,
    IntentClass.EXPLORATORY.value,
)

#: Classes that can reach a mutation-capable route. Classifying an expected
#: exploratory/unknown case into one of these is the blocking regression.
ACTION_CAPABLE_CLASSES: frozenset[str] = frozenset(
    {IntentClass.CO_AUTHORING.value, IntentClass.GOVERNANCE_BEARING.value}
)

#: Expected classes protected by the hard gate.
HARD_GATE_EXPECTED_CLASSES: frozenset[str] = frozenset(
    {IntentClass.EXPLORATORY.value, IntentClass.UNKNOWN.value}
)

_ALL_CLASSES: tuple[str, ...] = EMITTABLE_CLASSES + (IntentClass.UNKNOWN.value,)


class ClassificationGoldenSetError(ValueError):
    """A golden-set or replay artifact is malformed — fail loud, never skip."""


@dataclass(frozen=True)
class ClassificationCase:
    """One `classification_case.v1` case."""

    id: str
    language: str
    utterance: str
    surface: str
    note_state: str
    expected_intent: str
    expected_action_type: str | None
    acceptable: tuple[str, ...]


def load_classification_cases(
    path: Path = CLASSIFICATION_GOLDEN_PATH,
) -> List[ClassificationCase]:
    """Load and validate the golden set. Raises on any malformed case."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != CASE_SCHEMA_VERSION:
        raise ClassificationGoldenSetError(
            f"{path}: expected schema_version {CASE_SCHEMA_VERSION!r}, "
            f"got {doc.get('schema_version') if isinstance(doc, dict) else type(doc).__name__!r}"
        )
    raw_cases = doc.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ClassificationGoldenSetError(f"{path}: 'cases' must be a non-empty list")

    cases: List[ClassificationCase] = []
    seen_ids: set[str] = set()
    for raw in raw_cases:
        case = _parse_case(raw, path=path)
        if case.id in seen_ids:
            raise ClassificationGoldenSetError(f"{path}: duplicate case id {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def _parse_case(raw: object, *, path: Path) -> ClassificationCase:
    if not isinstance(raw, dict):
        raise ClassificationGoldenSetError(f"{path}: case is not a mapping: {raw!r}")
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise ClassificationGoldenSetError(f"{path}: case without a string id: {raw!r}")

    def _fail(reason: str) -> ClassificationGoldenSetError:
        return ClassificationGoldenSetError(f"{path}: case {case_id!r}: {reason}")

    language = raw.get("language")
    if language not in ("en", "sv"):
        raise _fail(f"language must be en|sv, got {language!r}")
    utterance = raw.get("utterance")
    if not isinstance(utterance, str) or not utterance.strip():
        raise _fail("utterance must be a non-empty string")
    context = raw.get("context")
    if not isinstance(context, dict):
        raise _fail("context must be a mapping with surface/note_state")
    expected_intent = raw.get("expected_intent")
    if expected_intent not in _ALL_CLASSES:
        raise _fail(f"expected_intent must be one of {_ALL_CLASSES}, got {expected_intent!r}")
    expected_action_type = raw.get("expected_action_type")
    if expected_intent == IntentClass.GOVERNANCE_BEARING.value:
        if not isinstance(expected_action_type, str) or not expected_action_type:
            raise _fail("governance_bearing cases must name expected_action_type")
    elif expected_action_type is not None:
        raise _fail("expected_action_type must be null unless governance_bearing")
    acceptable_raw = raw.get("acceptable")
    if not isinstance(acceptable_raw, list):
        raise _fail("acceptable must be a list")
    acceptable = tuple(str(entry) for entry in acceptable_raw)
    for entry in acceptable:
        if entry == IntentClass.UNKNOWN.value:
            # unknown is safe-fail, scored separately — never an acceptable class.
            raise _fail("'unknown' must never be listed in acceptable")
        if entry not in EMITTABLE_CLASSES:
            raise _fail(f"acceptable entry {entry!r} is not an emittable class")
    if expected_intent in HARD_GATE_EXPECTED_CLASSES:
        action_capable = set(acceptable) & ACTION_CAPABLE_CLASSES
        if action_capable:
            # Dataset invariant protecting the hard gate.
            raise _fail(
                "hard-gate case must not list action-capable classes as "
                f"acceptable: {sorted(action_capable)}"
            )
    return ClassificationCase(
        id=case_id,
        language=language,
        utterance=utterance,
        surface=str(context.get("surface", "")),
        note_state=str(context.get("note_state", "")),
        expected_intent=expected_intent,
        expected_action_type=expected_action_type,
        acceptable=acceptable,
    )


def load_replay_completions(path: Path = CLASSIFICATION_REPLAY_PATH) -> Dict[str, str]:
    """Load the recorded raw completions keyed by case id."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema_version") != REPLAY_SCHEMA_VERSION:
        raise ClassificationGoldenSetError(
            f"{path}: expected schema_version {REPLAY_SCHEMA_VERSION!r}"
        )
    completions = doc.get("completions")
    if not isinstance(completions, dict) or not completions:
        raise ClassificationGoldenSetError(f"{path}: 'completions' must be a non-empty mapping")
    out: Dict[str, str] = {}
    for case_id, raw in completions.items():
        if not isinstance(raw, str):
            raise ClassificationGoldenSetError(
                f"{path}: completion for {case_id!r} must be a raw string"
            )
        out[str(case_id)] = raw
    return out


# Retained only for the explicitly separate, opt-in legacy OpenAI comparator
# and authored replay-label compatibility. Product never imports this module.
INTENT_CLASSIFICATION_SCHEMA_REF = "chat.intent_classification.v1"

_INTENT_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "intent_class": {
            "enum": [
                IntentClass.CO_AUTHORING.value,
                IntentClass.GOVERNANCE_BEARING.value,
                IntentClass.EXPLORATORY.value,
            ]
        },
        "action_type": {
            "enum": [
                GovernanceActionType.MATURITY_TRANSITION.value,
                GovernanceActionType.FRONTMATTER_UPDATE.value,
                GovernanceActionType.NOTE_LIFECYCLE.value,
                GovernanceActionType.CROSS_NOTE.value,
                None,
            ]
        },
        "rationale": {"type": ["string", "null"]},
    },
    "required": ["intent_class", "action_type"],
}

register_schema(INTENT_CLASSIFICATION_SCHEMA_REF, _INTENT_CLASSIFICATION_SCHEMA)


_SYSTEM_PROMPT = (
    "You are classifying a single user intent during an active canvas "
    "co-authoring session. Classify the intent into exactly one class and "
    "return ONLY a JSON object, no commentary:\n"
    '{"intent_class": "<co_authoring|governance_bearing|exploratory>", '
    '"action_type": "<maturity_transition|frontmatter_update|note_lifecycle'
    '|cross_note|null>"}\n\n'
    "Classes:\n"
    "- co_authoring: edit the body of the currently open note "
    "(rewrite/expand/tighten/restructure prose). action_type = null.\n"
    "- governance_bearing: change classification, frontmatter/metadata with "
    "policy meaning, maturity/promotion state, note lifecycle "
    "(create/delete/rename/archive), or cross-note state. Set action_type to "
    "the closest match: maturity_transition (promote/demote/evergreen/"
    "seedling), frontmatter_update (tags/classification/properties/metadata), "
    "note_lifecycle (create/delete/rename/archive/split), cross_note "
    "(link/move/merge across notes).\n"
    "- exploratory: reason/compare/plan/draft/orient without mutating durable "
    "state. action_type = null."
)


class ClassificationReplayClient:
    """Translate authored label fixtures into synthetic typed Product results.

    The all-or-nothing probabilities are fixture values, not measured confidence.
    This exercises Product validation/mapping without claiming a TypeSafe call.
    Live comparator output must never enter this adapter.
    """

    def __init__(self, raw: str) -> None:
        self.raw = raw

    def judge_product_intent(self, intent_text: str) -> ProductJudgmentResult:
        try:
            payload = json.loads(self.raw)
            validate_payload(INTENT_CLASSIFICATION_SCHEMA_REF, payload)
            request = product_intent_request(intent_text)
            answers = []
            for question in request.questions:
                assert isinstance(question, ChoiceQuestion)
                value = payload[question.question_id] or "unknown"
                answers.append({
                    "question_id": question.question_id, "kind": "choice", "choice": value,
                    "confidence": 1.0,
                    "probabilities": {key: float(key == value) for key in question.criteria},
                })
            return ProductJudgmentResult.model_validate({
                "outcome": "success",
                "selection": {"model": "jev-0.0.0", "sdk_version": "0.0.0"},
                "judgment": {
                    "answers": answers,
                    "provenance": {"provider": "typesafe", "model": "jev-0.0.0"},
                },
                "usage": {"input_tokens": 0, "output_tokens": 0},
            })
        except (TypeError, ValueError, ConstrainedCompletionError):
            return ProductJudgmentResult(outcome="response_invalid")


def _legacy_comparator(intent: str, completion: CompletionFn, trace_id: str) -> str:
    """Preserve the old eval model's completion semantics, never a Product fallback."""
    try:
        payload = constrained_completion(
            INTENT_CLASSIFICATION_SCHEMA_REF, system=_SYSTEM_PROMPT,
            user=f"User intent: {intent.strip()}", task_kind="decide", trace_id=trace_id,
            complete=completion,
        )
    except ConstrainedCompletionError:
        return IntentClass.UNKNOWN.value
    return str(payload["intent_class"])


def classify_cases(
    cases: List[ClassificationCase],
    completions: Mapping[str, str] | None,
    *,
    live_completion: CompletionFn | None = None,
) -> Dict[str, str]:
    """Run authored fixtures through Product mapping, or the explicit legacy comparator.

    ``completions`` maps case ids to recorded raw model output (deterministic
    replay). ``None`` requires an explicitly bound ``live_completion``. A case
    missing from the replay fixture fails loud — a partially covered dataset is a false-green (cross-task invariant #6).
    """
    if completions is not None:
        # Reverse coverage (review finding on #2851): an orphan replay entry —
        # a completion id with no golden case — signals a renamed/removed case
        # whose stale recording would otherwise accumulate silently.
        golden_ids = {case.id for case in cases}
        orphans = sorted(set(completions) - golden_ids)
        if orphans:
            raise ClassificationGoldenSetError(
                f"replay fixture has orphan completions with no golden case: {orphans}; "
                "remove them or restore the matching golden cases"
            )
    if completions is None and live_completion is None:
        raise ClassificationGoldenSetError("live classification requires a bound eval client")
    predictions: Dict[str, str] = {}
    for case in cases:
        if completions is None:
            assert live_completion is not None
            predictions[case.id] = _legacy_comparator(
                case.utterance, live_completion, f"eval-cls-{case.id}",
            )
            continue
        else:
            raw = completions.get(case.id)
            if raw is None:
                raise ClassificationGoldenSetError(
                    f"replay fixture has no completion for case {case.id!r}; "
                    "every golden case must be covered"
                )
            cognition = IntentClassifierCognition(judgment_client=ClassificationReplayClient(raw))
        result = cognition.classify(intent=case.utterance, trace_id=f"eval-cls-{case.id}")
        predictions[case.id] = result.intent_class.value
    return predictions


def evaluate_classification(
    cases: List[ClassificationCase],
    predictions: Mapping[str, str],
) -> Dict:
    """Score predictions per the classification_case.v1 semantics."""
    confusion: Dict[str, Dict[str, int]] = {
        expected: {predicted: 0 for predicted in _ALL_CLASSES} for expected in _ALL_CLASSES
    }
    mutation_side: List[Dict[str, str]] = []
    passes = 0
    safe_fail_count = 0
    unknown_expected = 0
    unknown_safe_fail_hits = 0
    unknown_read_side = 0

    for case in cases:
        predicted = predictions[case.id]
        confusion[case.expected_intent][predicted] += 1

        if case.expected_intent in HARD_GATE_EXPECTED_CLASSES and (
            predicted in ACTION_CAPABLE_CLASSES
        ):
            mutation_side.append(
                {
                    "case_id": case.id,
                    "expected_intent": case.expected_intent,
                    "predicted_intent": predicted,
                }
            )

        if case.expected_intent == IntentClass.UNKNOWN.value:
            unknown_expected += 1
            if predicted == IntentClass.UNKNOWN.value:
                unknown_safe_fail_hits += 1
                passes += 1
            elif predicted == IntentClass.EXPLORATORY.value:
                unknown_read_side += 1
            continue

        if predicted == IntentClass.UNKNOWN.value:
            # Safe-fail: never scored as a wrong class.
            safe_fail_count += 1
        elif predicted == case.expected_intent or predicted in case.acceptable:
            passes += 1

    per_class: Dict[str, Dict[str, float | int]] = {}
    for cls in EMITTABLE_CLASSES:
        predicted_count = sum(confusion[expected][cls] for expected in _ALL_CLASSES)
        true_positive = confusion[cls][cls]
        # Recall denominator excludes safe-fails (predicted unknown): unknown
        # is scored separately, not as a wrong class.
        answered_support = sum(
            count
            for predicted, count in confusion[cls].items()
            if predicted != IntentClass.UNKNOWN.value
        )
        per_class[cls] = {
            "precision": (true_positive / predicted_count) if predicted_count else 0.0,
            "recall": (true_positive / answered_support) if answered_support else 0.0,
            "support": sum(confusion[cls].values()),
            "predicted": predicted_count,
        }

    answerable = len(cases) - unknown_expected
    answer_rate = ((answerable - safe_fail_count) / answerable) if answerable else 0.0
    macro_precision = sum(m["precision"] for m in per_class.values()) / len(per_class)
    macro_recall = sum(m["recall"] for m in per_class.values()) / len(per_class)

    return {
        "n_cases": len(cases),
        "per_class": per_class,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "pass_rate": passes / len(cases) if cases else 0.0,
        "confusion_matrix": confusion,
        "unknown": {
            "expected": unknown_expected,
            "safe_fail_hits": unknown_safe_fail_hits,
            "read_side_landings": unknown_read_side,
            "safe_fail_rate": (
                (unknown_safe_fail_hits / unknown_expected) if unknown_expected else 0.0
            ),
        },
        "safe_fail": {
            "count": safe_fail_count,
            "answer_rate": answer_rate,
        },
        "mutation_side_confusions": mutation_side,
        "hard_gate_passed": not mutation_side,
    }


def evaluate_classification_golden_set(
    *,
    cases_path: Path = CLASSIFICATION_GOLDEN_PATH,
    replay_path: Path = CLASSIFICATION_REPLAY_PATH,
    completions: Mapping[str, str] | None = None,
    live: bool = False,
    live_completion: CompletionFn | None = None,
) -> Dict:
    """Load, classify, and score the golden set.

    Deterministic replay by default; pass ``live=True`` (opt-in eval runs
    only) to drive the real provider instead of the replay fixture.
    """
    cases = load_classification_cases(cases_path)
    if live:
        if cases_path.resolve() != CLASSIFICATION_GOLDEN_PATH.resolve():
            raise ClassificationGoldenSetError("live evaluation only accepts the checked-in golden set")
        if live_completion is None:
            from app.eval.live_classification import configure_classification_eval, ClassificationCompletion

            live_completion = ClassificationCompletion(configure_classification_eval())
        resolved: Mapping[str, str] | None = None
    else:
        resolved = completions if completions is not None else load_replay_completions(replay_path)
    predictions = classify_cases(cases, resolved, live_completion=live_completion)
    result = evaluate_classification(cases, predictions)
    result["dataset"] = str(cases_path)
    result["replay"] = None if live else str(replay_path)
    result["mode"] = "live" if live else "replay"
    result["target"] = "legacy_completion_comparator" if live else "product_typed_mapping_fixture"
    return result


__all__ = [
    "ACTION_CAPABLE_CLASSES",
    "CASE_SCHEMA_VERSION",
    "CLASSIFICATION_GOLDEN_PATH",
    "CLASSIFICATION_REPLAY_PATH",
    "ClassificationCase",
    "ClassificationGoldenSetError",
    "EMITTABLE_CLASSES",
    "HARD_GATE_EXPECTED_CLASSES",
    "REPLAY_SCHEMA_VERSION",
    "classify_cases",
    "evaluate_classification",
    "evaluate_classification_golden_set",
    "load_classification_cases",
    "load_replay_completions",
]
