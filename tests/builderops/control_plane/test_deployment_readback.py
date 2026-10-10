from __future__ import annotations

import json

import pytest

from app.builderops.control_plane.deployment_readback import deployment_readback
from app.dispatcher.cli import _new_verification_ledger
from app.dispatcher.verification_merge import MergeAuthorityError


def _files(tmp_path, monkeypatch):
    receipt = {"project": "builderops-control-plane", "source_sha": "a" * 40,
               "image_digest": "sha256:" + "b" * 64,
               "postgres_image_digest": "sha256:" + "c" * 64,
               "candidate_receipt_sha": "d" * 64, "schema_version": 5,
               "authority_epoch": 17, "migration_completed": True,
               "authority_fencing_required": True}
    rp, pp = tmp_path / "latest.json", tmp_path / "pin.env"
    rp.write_text(json.dumps({**receipt, "private_extra": "never-project"}))
    names = {"source_sha": "SOURCE_SHA", "image_digest": "IMAGE_DIGEST",
             "postgres_image_digest": "POSTGRES_IMAGE_DIGEST", "candidate_receipt_sha": "CANDIDATE_RECEIPT_SHA"}
    pp.write_text("\n".join(f"BUILDEROPS_{name}={receipt[key]}" for key, name in names.items()))
    monkeypatch.setenv("BUILDEROPS_DEPLOYMENT_RECEIPT_FILE", str(rp))
    monkeypatch.setenv("BUILDEROPS_SELECTED_PIN_FILE", str(pp))
    return receipt, rp, pp


def test_installed_launcher_uses_fresh_status_and_withdraws_pin_drift(tmp_path, monkeypatch):
    receipt, _, pin = _files(tmp_path, monkeypatch)
    monkeypatch.delenv("BUILDEROPS_POST_EFFECT_DEPLOYMENT_READBACK_FILE", raising=False)

    class Client:
        def status(self):
            return {**receipt, "post_effect_capability": "post_effect_merge_readback.v1",
                    "post_effect_deployment": deployment_readback()}

    ledger = _new_verification_ledger(Client(), repository="example/repo", effect_outbox=None)
    ledger.require_post_effect_capability()
    assert ledger.post_effect_deployment["deployment_receipt"] == receipt
    first = ledger.post_effect_deployment["observed_at"]
    ledger.require_post_effect_capability()
    assert ledger.post_effect_deployment["observed_at"] != first
    # Match production write_pin: atomic pathname replacement, not in-place mutation.
    replacement = pin.with_suffix(".replacement")
    replacement.write_text(pin.read_text().replace("a" * 40, "e" * 40))
    replacement.replace(pin)
    with pytest.raises(MergeAuthorityError, match="exact deployed substrate"):
        ledger.require_post_effect_capability()


@pytest.mark.parametrize("failure", ["missing", "malformed", "duplicate", "unsafe", "partial"])
def test_deployment_projection_refuses_unavailable_or_invalid_files(tmp_path, monkeypatch, failure):
    _, receipt, pin = _files(tmp_path, monkeypatch)
    if failure == "missing":
        receipt.unlink()
    elif failure == "malformed":
        receipt.write_text("{")
    elif failure == "duplicate":
        pin.write_text(pin.read_text() + "\n" + pin.read_text().splitlines()[0])
    elif failure == "unsafe":
        body = json.loads(receipt.read_text()); body["source_sha"] = "secret-looking-text"
        receipt.write_text(json.dumps(body))
    else:
        body = json.loads(receipt.read_text()); body.pop("migration_completed")
        receipt.write_text(json.dumps(body))
    assert deployment_readback() is None
