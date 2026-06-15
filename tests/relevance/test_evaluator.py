"""Regression tests for the deterministic relevance evaluator (#2015).

Covers the datetime-vs-date coercion gap: an unquoted YAML ``due``/``deadline``
value parses as a :class:`datetime.datetime` (a subclass of :class:`datetime.date`),
which the old ``_coerce_date`` returned unchanged, so the later
``due - self.today`` subtraction did ``datetime - date`` and raised ``TypeError``,
aborting evaluation for the entire vault.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.relevance.evaluator import DeterministicRelevanceEvaluator

TODAY = date(2026, 6, 13)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_datetime_due_normalized_to_date(tmp_path: Path) -> None:
    """An unquoted YAML datetime due value evaluates without TypeError.

    YAML parses ``due: 2026-06-15 09:30:00`` as a ``datetime``; the evaluator
    must normalize it to a ``date`` before subtracting ``self.today`` so the
    commitment-horizon math does not raise ``datetime - date``.
    """

    vault = tmp_path / "vault"
    _write(
        vault / "Projects" / "Deadline.md",
        "---\n"
        "uuid: deadline-uuid\n"
        "due: 2026-06-15 09:30:00\n"  # unquoted -> YAML datetime
        "---\n\n# Deadline\n",
    )

    evaluator = DeterministicRelevanceEvaluator(vault, today=TODAY)

    # Before the fix this raised TypeError("unsupported operand type(s) for -:
    # 'datetime.datetime' and 'datetime.date'") and aborted the whole evaluation.
    moments = evaluator.evaluate()

    assert moments, "a commitment within the horizon must produce a moment"
    moment = moments[0]
    assert moment.urgency.band == "pressing"
    assert any("Projects/Deadline.md" == ref.ref for ref in moment.surfaced_refs)
