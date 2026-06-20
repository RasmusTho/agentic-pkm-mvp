from __future__ import annotations

from pathlib import Path
import importlib.util

import pytest

from app.agents.normalizer.agent import normalize_file

HAS_HYPOTHESIS = importlib.util.find_spec("hypothesis") is not None


# Representative file shapes for the deterministic-contract test below. These cover
# the branches normalize_file's metadata derivation actually depends on (empty,
# plain body, markdown heading, YAML frontmatter incl. artifact_kind, CRLF line
# endings, and non-ASCII/astral unicode) without leaning on randomized input.
_DETERMINISM_CASES = {
    "empty": "",
    "plain_body": "just a line of body text",
    "markdown_heading": "# Heading Title\n\nbody paragraph",
    "frontmatter": "---\ntitle: Front\nartifact_kind: task\n---\n# H\nbody",
    "crlf": "first line\r\nsecond line\r\n",
    "unicode": "unicode ☃ こんにちは \U0001F600 tail",
}


@pytest.mark.parametrize("content", _DETERMINISM_CASES.values(), ids=_DETERMINISM_CASES.keys())
def test_normalize_file_metadata_shape_is_deterministic(tmp_path: Path, content: str) -> None:
    """normalize_file's content-derived metadata is a pure function of the file.

    Replaces a former hypothesis property test (``@given(st.text())``) that only
    ever re-asserted this determinism over random text. That randomized form did
    two ``normalize_file`` calls (filesystem read + best-effort audit connect) per
    example under hypothesis's 200 ms wall-clock deadline, so on a loaded/contended
    CI runner a single GC/scheduler spike tripped ``FlakyFailure`` ("unreliable
    results"): green in isolation, intermittently red in the full ``-m "not pg"``
    suite. The contract here is not a property over text content, so it is asserted
    deterministically over fixed representative inputs instead -- no deadline, no
    order/load sensitivity.
    """
    path = tmp_path / "note.md"
    path.write_text(content, encoding="utf-8")

    first = normalize_file(str(path), trace_id="trace-1")
    second = normalize_file(str(path), trace_id="trace-2")

    # Kind is fixed regardless of content.
    assert first["kind"] == second["kind"] == "note"

    # Content-derived metadata is identical across calls on the same file.
    assert first["payload"]["core6"]["title"] == second["payload"]["core6"]["title"]
    assert first["payload"]["source_path"] == second["payload"]["source_path"] == str(path)
    assert first["source_ref"] == second["source_ref"] == str(path)

    # uuid is intentionally minted per call: unique each time, mirrored into core6.id.
    assert first["uuid"] != second["uuid"]
    assert first["payload"]["core6"]["id"] == first["uuid"]
    assert second["payload"]["core6"]["id"] == second["uuid"]


if not HAS_HYPOTHESIS:
    def test_hypothesis_missing() -> None:
        pytest.skip("hypothesis not installed")
else:
    from hypothesis import HealthCheck, given, settings, strategies as st

    # deadline=None: this is a genuine fuzz test (raw_text round-trip + crash
    # resistance over arbitrary text), but each example does filesystem + best-effort
    # audit-connect I/O whose latency is a property of the runner, not the input. A
    # wall-clock per-example deadline therefore measures CI contention and trips
    # FlakyFailure under load -- the same failure mode that forced the sibling
    # determinism test to be rewritten as a deterministic example-based test.
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(st.text())
    def test_normalize_file_core_fields(tmp_path: Path, text: str) -> None:
        path = tmp_path / "note.md"
        path.write_text(text, encoding="utf-8")

        result = normalize_file(str(path), trace_id="hypothesis-trace")

        assert result["uuid"]
        assert result["kind"] == "note"
        assert result.get("source_ref") == str(path)

        payload = result["payload"]
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        assert payload["raw_text"] == normalized_text
        assert payload["source_path"] == str(path)

        core6 = payload["core6"]
        assert core6["id"] == result["uuid"]
        assert core6["title"].strip()
        assert core6["review_state"]
