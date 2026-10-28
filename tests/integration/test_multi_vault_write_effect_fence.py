"""Production write/receipt window cannot be crossed by authority changes."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from pathlib import Path

import pytest

from app.api.routes import capture
from app.instance.binding_effect_lease import BindingEffectLeaseManager
from tests.api.test_multi_vault_governed_writes import setup_capture
from tests._mvr03_principal_harness import principal_store
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_authority_change_cannot_cross_validation_write_window(tmp_path, monkeypatch):
    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    original = capture._emit_capture_event

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(capture, "_emit_capture_event", paused)
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )

    def exclusive():
        with leases.exclusive_change(
            first.vault_binding_id, channel_id=runtime.layout.channel_id, root=Path(first.path)
        ):
            return True

    with ThreadPoolExecutor(max_workers=3) as pool:
        write = pool.submit(
            client.post,
            "/api/companion/capture/scoped",
            headers=headers,
            json={"text": "Authorized effect", "target_binding_id": first.vault_binding_id},
        )
        assert entered.wait(timeout=5)
        changed = pool.submit(exclusive)
        revoked = pool.submit(
            principal_store(runtime).rotate_credential,
            credential="new-test-credential",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        for pending in (changed, revoked):
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.1)
        release.set()
        result = write.result(timeout=5)
        assert result.status_code == 200, result.text
        assert changed.result(timeout=5)
        revoked.result(timeout=5)
    assert "Authorized effect" in Path(first.path, "Inbox/inbox.md").read_text()
    assert (
        result.json()["governed_write"]["authority_receipt"]["receipt_id"]
        in (tmp_path / "outbox.jsonl").read_text()
    )
