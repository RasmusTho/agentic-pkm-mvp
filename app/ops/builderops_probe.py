"""One-shot BuilderOps host probe; installation and secret provisioning are separate."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Iterator, Protocol
import urllib.request
import uuid


class ProbeRefusal(ValueError):
    """Invalid binding/configuration/state; never include source values in errors."""


class Channel(Protocol):
    def send(self, subject: str, body: str) -> None: ...


def _read_file(path: Path, *, token: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            mode = stat.S_IMODE(info.st_mode)
            permitted = info.st_uid == os.geteuid() and mode == 0o600
            if token:
                permitted = permitted or (info.st_uid == os.geteuid() and mode == 0o400)
                permitted = permitted or (info.st_uid == 0 and info.st_gid == 101 and mode == 0o640)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not permitted:
                raise ProbeRefusal("private_file_metadata_invalid")
            data = handle.read(65537)
            if len(data) > 65536:
                raise ProbeRefusal("private_file_too_large")
            return data
    except OSError:
        raise ProbeRefusal("private_file_unavailable") from None


@dataclass(frozen=True)
class ProbeConfig:
    target_hostname: str
    engine_socket: str
    expected_engine_id: str
    project: str
    api_url: str
    expected_epoch: int
    expected_schema_version: int
    probe_token_file: str
    alert_runtime_file: str
    state_file: str
    max_outbox_age_seconds: int
    schema: str = "builderops_probe_config.v1"

    @classmethod
    def load(cls, path: Path) -> ProbeConfig:
        try:
            raw = json.loads(_read_file(path))
            if not isinstance(raw, dict) or set(raw) != set(cls.__dataclass_fields__):
                raise ValueError
            config = cls(**raw)
            if (
                config.schema != "builderops_probe_config.v1"
                or config.target_hostname != "builder-system"
                or config.engine_socket != "unix:///run/docker-builderops.sock"
                or config.project != "builderops-control-plane"
                or config.api_url != "http://127.0.0.1:18100"
            ):
                raise ValueError
            if not isinstance(config.expected_engine_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,128}", config.expected_engine_id
            ):
                raise ValueError
            for value in (
                config.expected_epoch,
                config.expected_schema_version,
                config.max_outbox_age_seconds,
            ):
                if type(value) is not int or not 0 < value <= 2**63 - 1:
                    raise ValueError
            for filename in (config.probe_token_file, config.alert_runtime_file, config.state_file):
                if (
                    not isinstance(filename, str)
                    or not Path(filename).is_absolute()
                    or ".." in Path(filename).parts
                ):
                    raise ValueError
            if len({config.probe_token_file, config.alert_runtime_file, config.state_file}) != 3:
                raise ValueError
            return config
        except (TypeError, ValueError, UnicodeError):
            raise ProbeRefusal("configuration_invalid") from None


def _command(*args: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
    return subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=5, env=environment
    ).stdout.strip()


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0  # type: ignore[arg-type,operator]


def dependencies(config: ProbeConfig) -> list[str]:
    """Read dependencies only; mismatched identity refuses before any alert/state effect."""
    if _command("hostname") != config.target_hostname:
        raise ProbeRefusal("target_hostname_mismatch")
    docker = ("docker", "--host", config.engine_socket)
    failures: list[str] = []
    try:
        identity = json.loads(_command(*docker, "info", "--format", "{{json .ID}}"))
        if identity != config.expected_engine_id:
            raise ProbeRefusal("engine_identity_mismatch")
        names = [f"{config.project}-{service}-1" for service in ("api", "worker", "db")]
        containers = json.loads(_command(*docker, "inspect", *names))
        if not isinstance(containers, list) or len(containers) != 3:
            raise ValueError
        seen: set[str] = set()
        for container in containers:
            labels = container["Config"]["Labels"]
            service = labels["com.docker.compose.service"]
            if (
                labels["com.docker.compose.project"] != config.project
                or service not in ("api", "worker", "db")
                or service in seen
                or container["Name"] != f"/{config.project}-{service}-1"
            ):
                raise ProbeRefusal("container_identity_mismatch")
            seen.add(service)
            if (
                container["State"]["Running"] is not True
                or container["State"]["Health"]["Status"] != "healthy"
            ):
                failures.append(f"{service}_container_unhealthy")
    except ProbeRefusal:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        failures.append("engine_or_container_unavailable")
        return failures
    try:
        token = _read_file(Path(config.probe_token_file), token=True).decode("utf-8").strip()
        if not re.fullmatch(r"[!-~]{1,4096}", token):
            raise ProbeRefusal("probe_credential_invalid")
        request = urllib.request.Request(
            config.api_url + "/readyz", headers={"Authorization": "Bearer " + token}
        )
        # Explicit loopback transport: environment proxies cannot redirect a bearer.
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise ValueError
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError
            payload = json.loads(raw)
        db = payload["database"]
        if (
            type(db["authority_epoch"]) is not int
            or db["authority_epoch"] != config.expected_epoch
            or type(db["schema_version"]) is not int
            or db["schema_version"] != config.expected_schema_version
        ):
            raise ProbeRefusal("api_authority_identity_mismatch")
        if (
            payload["ready"] is not True
            or db["available"] is not True
            or payload["lineage"]["matches_release"] is not True
        ):
            failures.append("api_not_ready")
        if (
            payload["authority_bootstrap"]["status"] != "converged"
            or payload["authority_bootstrap"]["writers_enabled"] is not True
        ):
            failures.append("authority_not_converged")
        if payload["executor_heartbeat"]["state"] != "healthy":
            failures.append("worker_heartbeat_unhealthy")
        outbox = payload["outbox"]
        if (
            type(outbox["pending"]) is not int
            or outbox["pending"] < 0
            or type(outbox["dead_letters"]) is not int
            or outbox["dead_letters"] < 0
            or not _number(outbox["oldest_age_seconds"])
            or type(outbox["authority_threatening"]) is not bool
        ):
            raise ValueError
        if (
            outbox["dead_letters"] > 0
            or outbox["authority_threatening"]
            or (
                outbox["pending"] > 0
                and outbox["oldest_age_seconds"] > config.max_outbox_age_seconds
            )
        ):
            failures.append("outbox_degraded")
    except ProbeRefusal:
        raise
    except Exception:
        # No transport errors, bearer, endpoint or provider response reaches logs.
        failures.append("authenticated_readiness_unavailable")
    return sorted(set(failures))


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    directory = path.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ProbeRefusal("state_directory_invalid")
        flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(directory / "probe.lock", flags, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ProbeRefusal("state_lock_invalid")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProbeRefusal("probe_already_running") from None
            yield
        finally:
            os.close(fd)
    except OSError:
        raise ProbeRefusal("state_unavailable") from None


def _state(path: Path, config: ProbeConfig) -> dict[str, Any] | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(_read_file(path))
        if (
            not isinstance(value, dict)
            or set(value)
            != {"schema", "incident_id", "target", "down_since", "engine_id", "authority_epoch"}
            or value["schema"] != "builderops_probe_outage.v1"
            or value["target"] != "bob-1"
            or value["engine_id"] != config.expected_engine_id
            or type(value["authority_epoch"]) is not int
            or value["authority_epoch"] != config.expected_epoch
            or not isinstance(value["incident_id"], str)
            or not isinstance(value["down_since"], str)
            or str(uuid.UUID(value["incident_id"])) != value["incident_id"]
            or datetime.fromisoformat(value["down_since"]).tzinfo is None
        ):
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError):
        raise ProbeRefusal("retained_state_invalid") from None


def _write_state(path: Path, value: dict[str, Any]) -> None:
    # One locked writer; unpredictable exclusive temporary file, never follow a link.
    temporary = path.parent / (".probe-" + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _channel(path: str) -> Channel:
    # Reuse the existing shared adapter without importing Product runtime settings.
    source = (
        Path(__file__).resolve().parents[2] / "ops/host-setup/mac-mini/notification_channels.py"
    )
    spec = importlib.util.spec_from_file_location("builderops_notification_channels", source)
    if spec is None or spec.loader is None:
        raise ProbeRefusal("notification_adapter_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_channel("discord", runtime_env_file=Path(path))  # type: ignore[no-any-return]


def run(config: ProbeConfig) -> int:
    # Host mismatch must not even create an outage directory on another machine.
    if _command("hostname") != config.target_hostname:
        raise ProbeRefusal("target_hostname_mismatch")
    path = Path(config.state_file)
    with state_lock(path):
        retained = _state(path, config)
        failures = dependencies(config)
        try:
            channel = _channel(config.alert_runtime_file)
        except Exception:
            raise ProbeRefusal("notification_configuration_invalid") from None
        if not failures and retained is None:
            return 0
        if failures and retained is not None:
            return 1
        now = datetime.now(timezone.utc).isoformat()
        incident = retained["incident_id"] if retained else str(uuid.uuid4())
        transition = "down" if failures else "recovered"
        body = json.dumps(
            {
                "source": "builderops-host-probe",
                "target": "bob-1",
                "severity": "error" if failures else "info",
                "transition": transition,
                "timestamp": now,
                "correlation_id": incident,
                "failures": failures,
                "remediation_url": "https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md",
            },
            sort_keys=True,
        )
        try:
            channel.send("BuilderOps " + transition, body)
        except Exception:
            # Failed recovery retains down state; failed down delivery remains
            # retryable. A timeout/crash may duplicate a send: no exactly-once claim.
            print("builderops_probe: notification_delivery_failed", file=sys.stderr)
            return 1
        if failures:
            _write_state(
                path,
                {
                    "schema": "builderops_probe_outage.v1",
                    "incident_id": incident,
                    "target": "bob-1",
                    "down_since": now,
                    "engine_id": config.expected_engine_id,
                    "authority_epoch": config.expected_epoch,
                },
            )
        else:
            path.unlink()
        return 1 if failures else 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise urllib.error.HTTPError(req.full_url, code, "redirect_refused", headers, fp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # Python/urllib normally honors environment proxy and netrc routing.
        # Local probe HTTP and shared notification HTTPS use direct transports.
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        )
        result = run(ProbeConfig.load(args.config))
        print(
            json.dumps(
                {"schema": "builderops_probe_result.v1", "target": "bob-1", "healthy": result == 0}
            )
        )
        return result
    except (ProbeRefusal, OSError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, ProbeRefusal) else "probe_unavailable"
        print("builderops_probe: " + reason, file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
