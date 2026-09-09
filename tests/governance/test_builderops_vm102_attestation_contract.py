from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _section(document: str, heading: str, next_heading: str) -> str:
    start = document.index(heading)
    end = document.index(next_heading, start + len(heading))
    return document[start:end]


def test_candidate_attestation_requires_vm102_local_verifier() -> None:
    deployment = _section(
        (ROOT / "docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md")
        .read_text(encoding="utf-8"),
        "### Approved candidate attestation runner",
        "## Purpose",
    )
    evidence = _section(
        (ROOT / "docs/BUILDEROPS_CONTROL_PLANE/README.md").read_text(encoding="utf-8"),
        "## VM-102 evidence and receipt contract",
        "## TARS qualification contract",
    )

    deployment_lower = " ".join(deployment.lower().split())
    evidence_lower = " ".join(evidence.lower().split())
    for section in (deployment_lower, evidence_lower):
        assert "vm 102 deployment host" in section
        assert "must run" in section
        assert "cannot be handed off to deployment" in section
        assert "prior remote verifier result" in section
        assert "vm 102 or from a named" not in section
        assert "may run on vm 102 or a named" not in section

    assert "gh attestation verify" in deployment
    assert "source-ref refs/heads/main" in deployment
    assert "source-digest" in deployment
    assert "immutable image digest" in deployment
    assert "exact candidate SHA" in evidence
    assert "image digests" in evidence
    assert "secret_material: absent" in evidence
