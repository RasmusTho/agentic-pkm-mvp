from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev_bootstrap.sh"


def test_dev_bootstrap_uses_canonical_dev_channel() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "--env-file config/deploy/dev.env" in text
    assert "-f docker-compose.dev.yml" in text
    assert "-p pkm-dev" in text
    assert "127.0.0.1:18001/healthz" in text
    assert "API healthy on 18001; db on 15433; worker running" in text


def test_dev_bootstrap_has_no_prod_port_dependency() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "18000" not in text
    assert "15432" not in text
