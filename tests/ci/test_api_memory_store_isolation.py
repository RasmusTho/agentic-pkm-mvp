"""Exercise API requests after another test leaves a conflicting memory index."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET


def test_api_requests_do_not_inherit_prior_memory_index_identity(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    prior = tmp_path / "test_prior_index_occupant.py"
    prior.write_text(textwrap.dedent("""\
        from uuid import UUID
        from app.components.embeddings import EmbeddingIdentity
        from app.stores import get_vector_index, reset_memory_store_backend

        def test_prior_index_occupant(monkeypatch):
            monkeypatch.setenv("STORE_BACKEND", "memory")
            reset_memory_store_backend()
            index = get_vector_index()
            identity = EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text:latest", dim=768,
                normalize=True,
            )
            index.upsert(
                UUID("11111111-1111-1111-1111-111111111111"), kind="note",
                source_ref="unit-test://prior-occupant",
                payload={"text": "synthetic prior occupant"},
                embedding=[1.0] * 768, model=identity.model, identity=identity,
            )
            assert index.get_identity() == identity
        """), encoding="utf-8")
    targets = [
        str(prior),
        "tests/api/test_ask_alias.py::test_ask_accepts_question_field",
        "tests/api/test_ask_alias.py::test_ask_accepts_query_alias",
        "tests/api/test_health_api.py::test_health_success",
        "tests/api/test_health_api.py::test_health_allows_stale",
        "tests/api/test_health_api.py::test_disabled_seam_not_blocking",
    ]
    env = os.environ.copy()
    for key in ("PYTEST_ADDOPTS", "INDEX_PERSIST_PATH", "INDEX_PERSIST_LOAD"):
        env.pop(key, None)
    env.update(
        PYTHONPATH=str(repo), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        LLM_FORCE_PROVIDER="mock", STORE_BACKEND="memory",
    )
    junit = tmp_path / "api-prior-occupant.xml"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(repo / "pyproject.toml"),
         "--rootdir", str(repo), "-q", "-m", "not pg", f"--junitxml={junit}",
         *targets],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cases = ET.parse(junit).findall(".//testcase")
    assert {case.attrib["name"] for case in cases} == {
        "test_prior_index_occupant", "test_ask_accepts_question_field",
        "test_ask_accepts_query_alias", "test_health_success",
        "test_health_allows_stale", "test_disabled_seam_not_blocking",
    }
    assert len(cases) == 6
    assert all(len(case) == 0 for case in cases)
