"""Structured intent output with explicit UNKNOWN — acceptance tests (KERNEL-07, #2769).

Covers RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN:

- ``constrained_completion`` validates LLM output against a registered schema
  and raises a typed failure on invalid output — no regex extraction on the
  control path (audit invariant I-A1).
- The intent classifier emits an explicit ``UNKNOWN`` on validation failure and
  the ``/coauthor`` surface lands it read-only with a re-ask affordance; the
  silent ``CO_AUTHORING`` failure default is gone (audit invariant I-A2).
- Schema validation is invoked from the production
  ``IntentClassifierCognition.classify()`` entrypoint, not only from the
  utility in isolation.
- Fuzz: garbage LLM output never yields a governance-bearing (or any
  mutation-capable) route — UNKNOWN or a schema-validated class only.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.components.llm.constrained as constrained_module
from app.api.app import app
from app.chat.intent_classifier import (
    INTENT_CLASSIFICATION_SCHEMA_REF,
    IntentClass,
    IntentClassifierCognition,
)
from app.components.llm.constrained import (
    ConstrainedCompletionError,
    constrained_completion,
    registered_schema,
)


def _stub_completion(raw: str):
    """Deterministic raw-completion stub recording calls."""

    calls: list[dict[str, object]] = []

    def complete(
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        calls.append({"system": system, "user": user, "trace_id": trace_id})
        return raw

    complete.calls = calls  # type: ignore[attr-defined]
    return complete


def _classify(raw: str, intent: str = "promote this note to evergreen"):
    cognition = IntentClassifierCognition(completion=_stub_completion(raw))
    return cognition.classify(intent=intent)


# ---------------------------------------------------------------------------
# AC1: constrained_completion validates against the registered schema and
#      returns a typed failure on invalid output (no regex extraction).
# ---------------------------------------------------------------------------


def test_constrained_completion_validates() -> None:
    # Valid, schema-conforming output round-trips as a parsed dict.
    valid = json.dumps(
        {"intent_class": "governance_bearing", "action_type": "maturity_transition"}
    )
    payload = constrained_completion(
        INTENT_CLASSIFICATION_SCHEMA_REF,
        system="classify",
        user="promote this note to evergreen",
        complete=_stub_completion(valid),
    )
    assert payload["intent_class"] == "governance_bearing"
    assert payload["action_type"] == "maturity_transition"

    # Invalid outputs raise the typed failure — never a silently defaulted dict.
    invalid_outputs = [
        "",  # empty completion
        "MOCK_ASK_ANSWER: classify intent | context: ...",  # degraded sentinel
        "this is not json at all",  # prose
        "[1, 2, 3]",  # JSON, but not an object
        '"co_authoring"',  # JSON scalar
        json.dumps({"decision": "A"}),  # object missing required keys
        json.dumps({"intent_class": "co_authoring"}),  # missing action_type
        json.dumps({"intent_class": "governance", "action_type": None}),  # enum miss
        json.dumps({"intent_class": "co_authoring", "action_type": "explode"}),
        # JSON embedded in prose: the old regex extraction would have accepted
        # this. The constrained path parses the whole payload strictly.
        'Sure! Here you go: {"intent_class": "governance_bearing", '
        '"action_type": "cross_note"} — hope that helps.',
    ]
    for raw in invalid_outputs:
        with pytest.raises(ConstrainedCompletionError):
            constrained_completion(
                INTENT_CLASSIFICATION_SCHEMA_REF,
                system="classify",
                user="promote this note to evergreen",
                complete=_stub_completion(raw),
            )

    # An unregistered schema ref is a programming error, not a quiet pass.
    with pytest.raises(LookupError):
        constrained_completion(
            "no.such.schema.v0",
            system="s",
            user="u",
            complete=_stub_completion(valid),
        )

    # Regex extraction is gone from the classifier control path.
    import app.chat.intent_classifier as classifier_module

    bound = vars(classifier_module)
    assert "re" not in bound, "regex module must not be bound on the control path"
    assert "_extract_json_object" not in bound
    assert "_parse_label" not in bound
    assert "_defaulted" not in bound, "the CO_AUTHORING failure default must be gone"


# ---------------------------------------------------------------------------
# AC2: UNKNOWN lands read-only with a re-ask affordance; CO_AUTHORING default
#      is gone.
# ---------------------------------------------------------------------------


def test_unknown_degrades_read_only_and_reask(monkeypatch, tmp_path: Path) -> None:
    # Unit level: validation failure yields explicit UNKNOWN, never CO_AUTHORING.
    result = _classify("MOCK_ASK_ANSWER: classify intent | context: ...")
    assert result.intent_class is IntentClass.UNKNOWN
    assert result.classified is False
    assert result.action_type is None

    # Surface level: /coauthor lands UNKNOWN read-only with a re-ask affordance.
    note = tmp_path / "note.md"
    original = "---\nuuid: note-uuid-unknown\n---\n\n# Hello\n\nOriginal body.\n"
    note.write_text(original, encoding="utf-8")

    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: tmp_path)
    monkeypatch.setattr(canvas_module, "_get_vault_root_or_picker", lambda **_: tmp_path)
    monkeypatch.setattr(
        canvas_module,
        "_intent_classifier_completion",
        lambda: _stub_completion("not a classification"),
    )

    def _fail_generation() -> None:  # pragma: no cover - must never run
        raise AssertionError("UNKNOWN must not fall through to body generation")

    monkeypatch.setattr(canvas_module, "_coauthor_facade_factory", _fail_generation)

    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    client = TestClient(app)
    resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "unknown"}
    )
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Read-only degrade: explicit UNKNOWN landing surface, not a body edit.
    assert body["status"] == "unknown_intent_reask"
    assert body["session_id"] == session_id
    # Re-ask affordance is explicit in the response contract.
    assert body["reask"] is True
    assert body["detail"]
    # The note on disk is untouched.
    assert note.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# AC3 (enforcement): schema validation runs on the production classify() path.
# ---------------------------------------------------------------------------


def test_validation_invoked_from_classify(monkeypatch) -> None:
    validated: list[tuple[str, object]] = []
    real_validate = constrained_module.validate_payload

    def _spy(schema_ref: str, payload: object):
        validated.append((schema_ref, payload))
        return real_validate(schema_ref, payload)

    monkeypatch.setattr(constrained_module, "validate_payload", _spy)

    # Valid output: classify() routes through the utility and validation runs.
    valid = json.dumps(
        {"intent_class": "exploratory", "action_type": None}
    )
    result = _classify(valid, intent="what does this note argue?")
    assert result.intent_class is IntentClass.EXPLORATORY
    assert result.classified is True
    assert len(validated) == 1
    assert validated[0][0] == INTENT_CLASSIFICATION_SCHEMA_REF

    # Invalid output on the same production entrypoint: validation runs and its
    # failure is what produces UNKNOWN (not a bypass, not a regex fallback).
    result = _classify('{"intent_class": "governance_bearing"}')
    assert result.intent_class is IntentClass.UNKNOWN
    assert result.classified is False
    assert len(validated) == 2


# ---------------------------------------------------------------------------
# AC4 (fuzz): garbage never yields a mutation-capable route.
# ---------------------------------------------------------------------------


def _garbage_outputs(rng: random.Random, count: int) -> list[str]:
    """Adversarial garbage: random text, near-miss JSON, wrong shapes/enums."""

    enum_near_misses = [
        "CO_AUTHORING",
        "governance",
        "governance-bearing",
        "unknown",
        "exploratory ",
        "co_authoring\n",
        "",
        None,
        1,
        True,
        ["governance_bearing"],
    ]
    outputs: list[str] = []
    for _ in range(count):
        pick = rng.randrange(6)
        if pick == 0:
            # Random printable noise.
            outputs.append(
                "".join(rng.choices(string.printable, k=rng.randrange(0, 80)))
            )
        elif pick == 1:
            # JSON non-objects.
            outputs.append(
                json.dumps(rng.choice([None, True, 3.14, "governance_bearing", [1, 2]]))
            )
        elif pick == 2:
            # Objects with random keys/values.
            outputs.append(
                json.dumps(
                    {
                        "".join(rng.choices(string.ascii_lowercase, k=5)): rng.random()
                        for _ in range(rng.randrange(0, 4))
                    }
                )
            )
        elif pick == 3:
            # Near-miss classification objects (wrong enum members / types).
            outputs.append(
                json.dumps(
                    {
                        "intent_class": rng.choice(enum_near_misses),
                        "action_type": rng.choice(enum_near_misses),
                    }
                )
            )
        elif pick == 4:
            # Valid-looking JSON buried in prose (the regex-era escape hatch).
            outputs.append(
                'The classification is {"intent_class": "governance_bearing", '
                '"action_type": "maturity_transition"} as requested.'
            )
        else:
            # Truncated / malformed JSON.
            outputs.append('{"intent_class": "governance_bearing", "action_ty')
    return outputs


def test_fuzz_unknown_never_a_route() -> None:
    rng = random.Random(2769)
    schema = registered_schema(INTENT_CLASSIFICATION_SCHEMA_REF)
    mutation_capable = {IntentClass.CO_AUTHORING, IntentClass.GOVERNANCE_BEARING}

    for raw in _garbage_outputs(rng, 300):
        result = _classify(raw)
        if result.intent_class is IntentClass.UNKNOWN:
            assert result.classified is False
            assert result.action_type is None
            continue
        # Anything that classified MUST be provably schema-validated output:
        # the raw completion itself parses strictly and satisfies the schema.
        payload = json.loads(raw)
        jsonschema.validate(payload, schema)
        assert result.classified is True
        # And a mutation-capable class is reachable ONLY from that validated
        # parse — which for this garbage corpus must never have happened.
        assert result.intent_class not in mutation_capable, (
            f"garbage output routed to mutation-capable class: {raw!r}"
        )
