"""Execute the selector and real missing-path boundary for SV/EN eval lanes."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from scripts.select_pr_tests import PR_MARKER_EXPRESSION

_MODULE = "tests/evals/test_sv_en_retrieval_eval.py"
_LIVE_NODES = {
    f"{_MODULE}::test_live_run_reproduces_the_cross_lingual_finding",
    f"{_MODULE}::test_live_corpus_embeds_at_the_declared_dimensions",
}
_PATH_ENV = (
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
)


def _collect(marker: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", marker, _MODULE],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {line.strip() for line in result.stdout.splitlines() if line.startswith(f"{_MODULE}::")}


def test_default_pr_marker_keeps_only_deterministic_sv_en_layers() -> None:
    declared = {
        f"{_MODULE}::{node.name}"
        for node in ast.parse(Path(_MODULE).read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    deterministic = declared - _LIVE_NODES
    assert len(deterministic) == 10
    assert _collect(PR_MARKER_EXPRESSION) == deterministic


def test_explicit_eval_marker_selects_exact_live_reproduction_nodes() -> None:
    assert _collect("eval") == _LIVE_NODES


def test_explicit_live_eval_without_product_path_fails_loudly() -> None:
    """No admission credentials or availability fake: execute the real two test bodies."""
    environment = {key: value for key, value in os.environ.items() if key not in _PATH_ENV}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "eval", _MODULE, "--tb=short"],
        env=environment, capture_output=True, text=True, check=False, timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "ExecutorNetworkConfigurationError" in output, output
    assert "path_configuration_missing" in output, output
    failed = {
        line.split(" - ", 1)[0].removeprefix("FAILED ")
        for line in output.splitlines() if line.startswith("FAILED ")
    }
    assert failed == _LIVE_NODES, output
    assert "2 failed" in output and "skipped" not in output, output
