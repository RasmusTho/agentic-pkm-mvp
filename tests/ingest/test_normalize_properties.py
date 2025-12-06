from __future__ import annotations

from pathlib import Path
import importlib.util

import pytest

HAS_HYPOTHESIS = importlib.util.find_spec("hypothesis") is not None

if not HAS_HYPOTHESIS:
    def test_hypothesis_missing() -> None:
        pytest.skip("hypothesis not installed")
else:
    from hypothesis import given, strategies as st

    from app.agents.normalizer.agent import normalize_file

    @given(st.text())
    def test_normalize_file_core_fields(tmp_path: Path, text: str) -> None:
        path = tmp_path / "note.md"
        path.write_text(text, encoding="utf-8")

        result = normalize_file(str(path), trace_id="hypothesis-trace")

        assert result["uuid"]
        assert result["kind"] == "note"
        assert result.get("source_ref") == str(path)

        payload = result["payload"]
        assert payload["raw_text"] == text
        assert payload["source_path"] == str(path)

        core6 = payload["core6"]
        assert core6["id"] == result["uuid"]
        assert core6["title"].strip()
        assert core6["review_state"]

    @given(st.text())
    def test_normalize_file_deterministic_metadata_shape(tmp_path: Path, text: str) -> None:
        path = tmp_path / "note.md"
        path.write_text(text, encoding="utf-8")

        first = normalize_file(str(path), trace_id="trace-1")
        second = normalize_file(str(path), trace_id="trace-2")

        assert first["kind"] == second["kind"] == "note"
        assert first["payload"]["core6"]["title"] == second["payload"]["core6"]["title"]
        assert first["payload"]["source_path"] == second["payload"]["source_path"] == str(path)
        assert first["source_ref"] == second["source_ref"] == str(path)
        # UUIDs are intentionally unique per run; ensure they differ for the same file.
        if first["uuid"] != second["uuid"]:
            assert first["payload"]["core6"]["id"] != second["payload"]["core6"]["id"]
