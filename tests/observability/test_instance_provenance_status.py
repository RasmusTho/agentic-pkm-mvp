from __future__ import annotations

from types import SimpleNamespace

from app.observability.status_service import get_system_status


def test_status_summary_reports_instance_provenance(monkeypatch) -> None:
    bundle = SimpleNamespace(instance=SimpleNamespace(id="office", role="satellite", environment="dev"))
    monkeypatch.setattr("app.observability.status_service.get_settings_bundle", lambda: bundle, raising=False)

    status = get_system_status()

    assert status.instance_provenance is not None
    assert status.instance_provenance.instance_id == "office"
    assert status.instance_provenance.instance_role == "satellite"
    assert status.instance_provenance.environment == "dev"
