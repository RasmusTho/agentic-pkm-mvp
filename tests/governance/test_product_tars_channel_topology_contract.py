from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = (
    ROOT / "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md",
    ROOT / "docs/deployment/profiles/TARS_PROXMOX.md",
    ROOT / "docs/ENVIRONMENTS.md",
    ROOT / "docs/RELEASE_CHANNELS/README.md",
    ROOT / "docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md",
)


def test_owner_docs_keep_product_channels_demerzel_and_vm102_separate() -> None:
    contents = [path.read_text(encoding="utf-8") for path in DOCS]
    joined = "\n".join(contents)

    assert "TARS-hosted Linux VM topology" in joined
    assert "Demerzel/Mac mini" in joined
    assert "control, development, client" in joined
    assert "VM 102 (`builder-system`)" in joined
    assert "separate Builder System / Dev System target" in joined
    assert "local Compose/Colima" in joined
    assert "product_tars_channel_topology.v1" in joined
    assert "does not" in joined

    deployment = contents[0]
    assert "must not be used as a Product Runtime channel VM or\nengine" in deployment
    assert "do not authorize a channel operation" in deployment


def test_topology_contract_is_provider_neutral() -> None:
    profile = (ROOT / "docs/deployment/profiles/TARS_PROXMOX.md").read_text(encoding="utf-8")
    assert "Provider/model selection is outside placement" in profile
    assert "no named provider, model, or codex-only architecture decision" in profile.lower()
    assert "provider:" not in profile.lower()
    assert "model:" not in profile.lower()
