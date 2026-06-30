from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    return loader.construct_sequence(node)


_ComposeLoader.add_constructor("!override", _construct_override)


def _compose(path: str) -> dict:
    return yaml.load(
        (REPO_ROOT / path).read_text(encoding="utf-8"),
        Loader=_ComposeLoader,
    )


def test_gateway_runs_as_managed_unit_with_restart() -> None:
    base = _compose("docker-compose.yaml")
    service = base["services"]["companion-ui"]

    assert service["restart"] == "unless-stopped"
    assert service["depends_on"]["api"]["condition"] == "service_healthy"
    assert service["healthcheck"]
    assert "COMPANION_UI_SERVE_MODULE" in service["environment"]

    startup = (REPO_ROOT / "scripts/lib/companion_ui_startup.sh").read_text(
        encoding="utf-8"
    )
    assert "nohup" not in startup
    assert "up -d --force-recreate companion-ui" in startup
    assert "config/deploy/${CUI_CHANNEL}.env" in startup
    assert "cui_companion_ui_container_id" in startup


def test_gateway_recreated_in_lockstep_with_api() -> None:
    base = _compose("docker-compose.yaml")
    assert "api" in base["services"]
    assert "companion-ui" in base["services"]
    assert base["services"]["companion-ui"]["depends_on"]["api"]["condition"] == (
        "service_healthy"
    )

    startup = (REPO_ROOT / "scripts/lib/companion_ui_startup.sh").read_text(
        encoding="utf-8"
    )
    assert "cui_start_runtime" in startup
    assert "cui_start_ui" in startup
    assert "companion-ui" in startup


def test_wrappers_invoke_managed_unit() -> None:
    wrappers = [
        "scripts/dev/start_niflheim_ui.sh",
        "scripts/test/start_bifrost_ui.sh",
        "scripts/prod/start_midgard_ui.sh",
    ]
    for wrapper in wrappers:
        text = (REPO_ROOT / wrapper).read_text(encoding="utf-8")
        assert "cui_run_start" in text
        assert "docker-compose.app-bind.yml" not in text
        assert "nohup" not in text


def test_channel_overlays_define_distinct_gateway_units() -> None:
    expected = {
        "docker-compose.dev.yml": ("dev", 8111, "companion_ui.workspace.serve_dev_page"),
        "docker-compose.test.yml": ("test", 8112, "companion_ui.workspace.serve_dev_page"),
        "docker-compose.prod.yml": (
            "prod",
            8113,
            "companion_ui.workspace.serve_production_page",
        ),
    }

    for path, (channel, port, module) in expected.items():
        service = _compose(path)["services"]["companion-ui"]
        env = service["environment"]
        assert env["PKM_ENVIRONMENT"] == channel
        assert env["PORT"] == port
        assert env["COMPANION_UI_SERVE_MODULE"] == module
        assert service["ports"] == [
            f"${{COMPANION_UI_BIND_HOST:-127.0.0.1}}:{port}:{port}"
        ]
