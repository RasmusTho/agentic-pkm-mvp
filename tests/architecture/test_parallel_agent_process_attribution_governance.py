"""Governance regression for #5252 process attribution and intervention."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_process_intervention_requires_ownership_evidence() -> None:
    """Census observations must not become host-global process authority."""
    agents = _read("AGENTS.md")
    host_lease = _read("scripts/run_with_host_lease.py")

    parallel_section = agents.split("## Parallel-agent execution", 1)[1].split(
        "## Transition-period bug-delivery policy", 1
    )[0]

    assert "the lease is the only coordination authority" in parallel_section
    assert "process census are advisory diagnostics" in parallel_section
    assert "before attributing or interrupting another task's process" in parallel_section
    assert "cwd or parent/lease readback" in parallel_section
    assert "command text, PID, census, or a quiet period alone is insufficient" in parallel_section

    assert "Host-global suite coordination:" in host_lease
    assert "repo-common lock is the lease and mutual-exclusion authority" in host_lease
    assert "advisory diagnostics, not evidence for attributing or interrupting another" in host_lease
    assert "only recovers its own child process group" in host_lease
