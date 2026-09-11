from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app.builderops.devui_runtime import RuntimeConfigurationError, create_app, load_configuration


ROOT = Path(__file__).resolve().parents[2]


def _environment(path: Path) -> dict[str, str]:
    return {
        "VCS_REF": "a" * 40,
        "DEVUI_SOURCE_SHA": "a" * 40,
        "DEVUI_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "DEVUI_CONFIG_FINGERPRINT": "sha256:" + "c" * 64,
        "DEVUI_VM102_RECEIPT_DIR": str(path),
    }


def test_standalone_startup_boundary(tmp_path: Path) -> None:
    script = """
import importlib.abc, sys
class RejectProduct(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in {'app.api', 'app.settings', 'app.auth', 'app.store', 'app.db', 'app.dispatcher'}:
            raise AssertionError('Product/store import: ' + fullname)
sys.meta_path.insert(0, RejectProduct())
from app.builderops.devui_runtime import production_app
app = production_app()
assert {r.path for r in app.routes} == {'/api/devui/overview', '/healthz', '/version'}
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], **_environment(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
    for key in _environment(tmp_path):
        env = _environment(tmp_path)
        del env[key]
        with pytest.raises(RuntimeConfigurationError):
            load_configuration(env)
    with pytest.raises(RuntimeConfigurationError):
        load_configuration(_environment(tmp_path / "absent"))
    with pytest.raises(RuntimeConfigurationError):
        load_configuration({**_environment(tmp_path), "DEVUI_SOURCE_SHA": "d" * 40})


def test_managed_overview_admission(tmp_path: Path) -> None:
    app = create_app(load_configuration(_environment(tmp_path)))
    with TestClient(app, client=("127.0.0.1", 1000), base_url="http://127.0.0.1:8113") as client:
        response = client.get("/api/devui/overview")
        assert response.status_code == 200
        payload = response.json()
        assert "refused" in json.dumps(payload)
        assert "ready_to_try" in json.dumps(payload)
        for headers in (
            {"X-Forwarded-For": "127.0.0.1"},
            {"Forwarded": "for=127.0.0.1"},
            {"Host": "evil.example"},
        ):
            assert client.get("/api/devui/overview", headers=headers).status_code == 403
        assert client.post("/api/devui/overview").status_code == 405
        assert client.get("/api/devui/overview/extra").status_code == 404
        assert client.get("/api/devui/overview?upstream=http://evil.example").status_code == 400
        assert client.get("/api/devui/composition").status_code == 404
        assert client.get("/healthz").json()["complete_dev_system_health"] is False
    with TestClient(app, client=("192.0.2.5", 1000), base_url="http://127.0.0.1:8113") as client:
        assert client.get("/api/devui/overview").status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_managed_configuration_keeps_listener_private() -> None:
    import yaml

    config = yaml.safe_load((ROOT / "docker-compose.devui.yml").read_text())
    assert config["name"] == "builderops-devui"
    service = config["services"]["devui"]
    assert service["network_mode"] == "host"
    assert service["read_only"] is True
    assert service["command"] == ["python", "-m", "app.builderops.devui_runtime"]
    assert service["restart"] == "unless-stopped"
    assert service["volumes"][0]["read_only"] is True
    assert service["volumes"][0]["bind"]["create_host_path"] is False
    assert not {"ports", "env_file", "secrets"} & service.keys()
