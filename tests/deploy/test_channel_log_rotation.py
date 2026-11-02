"""Bounded log retention for real non-production container creation paths."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.ops import heavy_acceptance, heavy_acceptance_runner, pg_acceptance, pg_acceptance_runner
from app.ops.acceptance_memory import AcceptanceMemoryPolicy, MemoryLimit
from app.ops.heavy_acceptance_runner import HeavyAcceptanceRunner
from tests.deploy import test_postmerge_heavy_acceptance as heavy_fixtures
from tests.deploy import test_postmerge_pg_acceptance as pg_fixtures

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_LOGGING = {
    "driver": "json-file",
    "options": {"max-file": "3", "max-size": "50m"},
}


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_channel_compose_logging_has_no_anchor_or_alias(channel: str) -> None:
    # The retained-source projection deliberately refuses YAML indirection;
    # real channel overlays must remain admissible to that comparison.
    events = yaml.parse((ROOT / f"docker-compose.{channel}.yml").read_text())
    assert all(not isinstance(event, yaml.events.AliasEvent) and not getattr(event, "anchor", None)
               for event in events)


def _compose(*files: str, channel: str = "dev") -> dict:
    result = subprocess.run(
        [
            "docker", "compose", "--env-file", str(ROOT / "config" / "deploy" / f"{channel}.env"),
            *(argument for file in files for argument in ("-f", str(ROOT / file))),
            "--profile", "*", "config", "--format", "json", "--no-env-resolution", "--no-interpolate",
        ],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)["services"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker compose executable unavailable")
def test_channel_compose_rotation_and_prod_isolation() -> None:
    base = _compose("docker-compose.yaml")
    for channel in ("dev", "test"):
        actual = _compose("docker-compose.yaml", f"docker-compose.{channel}.yml", channel=channel)
        assert actual.keys() == base.keys()
        for name in base:
            assert actual[name]["logging"] == EXPECTED_LOGGING, (channel, name)
    prod = _compose("docker-compose.yaml", "docker-compose.prod.yml", channel="prod")
    assert all("logging" not in service for service in prod.values())


def _assert_rotation(arguments: list[str] | tuple[str, ...]) -> None:
    assert arguments[arguments.index("--log-driver") + 1] == "json-file"
    options = [arguments[i + 1] for i, value in enumerate(arguments) if value == "--log-opt"]
    assert sorted(options) == ["max-file=3", "max-size=50m"]


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("use_memory", [False, True])
def test_native_acceptance_container_create_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str, use_memory: bool,
) -> None:
    limit = MemoryLimit(256 * 1024**2, 256 * 1024**2)
    policy = AcceptanceMemoryPolicy(heavy=limit, pg_db=limit, pg_tests=limit) if use_memory else None
    pg_dir = tmp_path / "pg"
    pg_dir.mkdir()
    runner, boundary, _, _ = pg_fixtures._runner(pg_dir, monkeypatch, channel=channel, memory_policy=policy)
    assert runner.verify()["result"] == "passed"
    pg_creates = [args for args, _ in boundary.commands if args[0] == "create"]
    assert len(pg_creates) == 2
    for args in pg_creates:
        _assert_rotation(args)
        if use_memory:
            assert args[args.index("--memory") + 1] == str(limit.memory)
            assert args[args.index("--memory-swap") + 1] == str(limit.memory_swap)

    heavy_dir = tmp_path / "heavy"
    heavy_dir.mkdir()
    output = heavy_acceptance.RESULT_PREFIX + json.dumps(heavy_fixtures._summary(channel=channel)) + "\n"
    fixture_runner, fake = heavy_fixtures._runner(heavy_dir, monkeypatch, output)
    heavy_runner = HeavyAcceptanceRunner(
        fixture_runner.repository, heavy_dir / "journal", sha=heavy_fixtures.SHA,
        digest=heavy_fixtures.DIGEST, channel=channel, operation_id=heavy_fixtures.OPERATION,
        memory_limit=limit if use_memory else None,
    )
    assert heavy_runner.verify()["result"] == "passed"
    _assert_rotation(fake.created)
    if use_memory:
        assert fake.created[fake.created.index("--memory") + 1] == str(limit.memory)
        assert fake.created[fake.created.index("--memory-swap") + 1] == str(limit.memory_swap)


def test_native_acceptance_rejects_prod_before_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(pg_acceptance_runner, "_command", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(heavy_acceptance_runner, "_command", lambda *args, **kwargs: calls.append(args))
    arguments = {
        "sha": heavy_fixtures.SHA, "digest": heavy_fixtures.DIGEST,
        "channel": "prod", "operation_id": heavy_fixtures.OPERATION,
    }
    with pytest.raises(pg_acceptance.PgAcceptanceError):
        pg_acceptance_runner.PgAcceptanceRunner(tmp_path, tmp_path, **arguments)
    with pytest.raises(heavy_acceptance.HeavyAcceptanceError):
        HeavyAcceptanceRunner(tmp_path, tmp_path, **arguments)
    assert not calls
