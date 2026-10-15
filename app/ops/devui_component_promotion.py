"""Manual, fixed-boundary DevUI promotion; no control-plane or acceptance authority.

One trusted operator on one host. The existing deployment lock serializes plans and
effects. A durable pending attempt prevents replay after process/transport loss;
recovery is deliberate readback, not an automatic second deployment.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.builderops.deployment_lock import _assert_held

ROOT = Path(__file__).resolve().parents[2]
RELEASES = Path("/opt/builderops/releases")
RECEIPTS = Path("/opt/builderops/receipts")
LOCK = Path("/tmp/agentic-pkm-mvp-builderops-lock/deployment.lock")
PROJECT = "builderops-devui"
CONTAINER = "builderops-devui-devui-1"
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
IMAGE = "ghcr.io/rasmustho/builderops-control-plane@"
FILES = ("docker-compose.devui.yml", "docker-compose.devui-sources.yml")
ENV_KEYS = {"DEVUI_SOURCE_SHA", "DEVUI_IMAGE_DIGEST", "DEVUI_CONFIG_FINGERPRINT",
            "DEVUI_VM102_RECEIPT_DIR", "DEVUI_REPOSITORY", "DEVUI_BUILDEROPS_AUTHORITY_EPOCH",
            "BUILDEROPS_API_URL", "BUILDEROPS_API_TOKEN_FILE", "DEVUI_GITHUB_ENABLED",
            "GH_CONFIG_DIR", "GH_HOST", "GH_PROMPT_DISABLED", "DEVUI_DIAGNOSTIC_ORIGIN",
            "DEVUI_CKM_OVERVIEW_URL"}
MOUNTS = {"/opt/builderops/receipts": "/run/builderops/devui-receipts",
          "/opt/builderops/secrets/devui-api-token": "/run/builderops/devui-api-token",
          "/opt/builderops/devui-gh": "/run/builderops/devui-gh"}

COMMAND = ["python", "-m", "app.builderops.devui_runtime"]
HEALTH_TEST = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8113/healthz', timeout=3)"]
HEALTHCHECK = {"test": HEALTH_TEST, "interval": "30s", "timeout": "5s", "retries": 3}


class Refusal(RuntimeError):
    """Value-free operational refusal."""


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(argv: list[str], *, env: dict[str, str] | None = None) -> str:
    # Errors never echo command output: a tool may accidentally return credentials.
    try:
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("external_command_indeterminate") from exc
    if result.returncode:
        raise Refusal("external_command_failed")
    return result.stdout


def gh(arguments: list[str]) -> str:
    operator = os.environ.get("SUDO_USER")
    prefix = ["runuser", "--user", operator, "--"] if operator and operator != "root" else []
    return run(prefix + ["gh", *arguments])


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        Path(name).unlink(missing_ok=True)


def boundary() -> str:
    if os.geteuid() != 0 or socket.gethostname() != "builder-system":
        raise Refusal("host_or_operator_refused")
    try:
        fd = int(os.environ["BUILDEROPS_DEPLOYMENT_LOCK_FD"])
    except (KeyError, ValueError) as exc:
        raise Refusal("interlock_missing") from exc
    if _assert_held(LOCK, fd):
        raise Refusal("interlock_invalid")
    endpoint = run(["docker", "context", "inspect", "builderops", "--format", "{{.Endpoints.docker.Host}}"])
    if endpoint.strip() != "unix:///run/docker-builderops.sock":
        raise Refusal("engine_context_refused")
    return run(["docker", "--context", "builderops", "info", "--format", "{{.ID}}"]
               ).strip()


def pair(path: Path) -> tuple[dict[str, Any], str]:
    contents = path.read_bytes()
    data = json.loads(contents)
    expected = {"receipt_version": 1, "repository": REPOSITORY,
                "workflow": ".github/workflows/app-image-build.yml", "event_name": "push",
                "source_ref": "refs/heads/main", "durability_posture": "rebuildable", "platform": "linux/amd64"}
    if any(data.get(k) != v for k, v in expected.items()) or not re.fullmatch(r"[a-f0-9]{40}", data.get("source_sha", "")):
        raise Refusal("candidate_provenance_refused")
    for key in ("control_plane_image_digest", "postgres_image_digest"):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", data.get(key, "")):
            raise Refusal("candidate_digest_refused")
    # The normal operator can read this public receipt, but cannot replace/write it.
    # Parse, hash and attest one snapshot even if the caller's path is replaced.
    with tempfile.TemporaryDirectory(prefix="devui-candidate-") as directory:
        snapshot = Path(directory) / "candidate-pair.json"
        snapshot.write_bytes(contents)
        snapshot.chmod(0o444)
        Path(directory).chmod(0o755)
        gh(["attestation", "verify", str(snapshot), "--repo", REPOSITORY, "--signer-workflow",
            REPOSITORY + "/.github/workflows/app-image-build.yml", "--source-ref", "refs/heads/main",
            "--source-digest", data["source_sha"]])
    return data, hashlib.sha256(contents).hexdigest()


def pending() -> None:
    for path in RECEIPTS.glob("devui-component-*.json"):
        if re.fullmatch(r"devui-component-[a-f0-9]{64}\.json", path.name):
            record = json.loads(path.read_text())
            if record.get("receipt_type") != "devui_component_deployment.v1" or record.get("outcome") not in {"deployed", "rolled_back"}:
                raise Refusal("retained_attempt_requires_readback")


def observed() -> dict[str, Any]:
    rows = json.loads(run(["docker", "--context", "builderops", "inspect", CONTAINER]))
    if len(rows) != 1:
        raise Refusal("component_cardinality_refused")
    c = rows[0]
    labels = c["Config"]["Labels"]
    if labels.get("com.docker.compose.project") != PROJECT or labels.get("com.docker.compose.service") != "devui":
        raise Refusal("component_project_refused")
    env = dict(x.split("=", 1) for x in c["Config"]["Env"] if "=" in x)
    selected = {k: v for k, v in env.items() if k in ENV_KEYS}
    image = c["Config"]["Image"]
    if image != IMAGE + selected.get("DEVUI_IMAGE_DIGEST", "") or labels.get("org.opencontainers.image.revision") != selected.get("DEVUI_SOURCE_SHA"):
        raise Refusal("runtime_identity_refused")
    if not c["State"]["Running"] or c["Config"].get("User") not in {"builderops", "101", "101:101"}:
        raise Refusal("runtime_posture_refused")
    if c["HostConfig"].get("NetworkMode") != "host" or not c["HostConfig"].get("ReadonlyRootfs"):
        raise Refusal("runtime_posture_refused")
    host = c["HostConfig"]
    if (host.get("Privileged") or host.get("CapAdd") or host.get("VolumesFrom") or
            host.get("Devices") or host.get("DeviceRequests") or host.get("DeviceCgroupRules") or
            host.get("PidMode") or host.get("IpcMode") != "private" or
            host.get("CapDrop") != ["ALL"] or host.get("SecurityOpt") != ["no-new-privileges:true"] or
            host.get("RestartPolicy") != {"Name": "unless-stopped", "MaximumRetryCount": 0} or
            c["Config"].get("Cmd") != COMMAND or c["Config"].get("Entrypoint") or
            c["Config"].get("Healthcheck") != {"Test": HEALTH_TEST, "Interval": 30000000000,
                                            "Timeout": 5000000000, "Retries": 3}):
        raise Refusal("runtime_posture_refused")
    mounts = {m["Source"]: m["Destination"] for m in c["Mounts"] if not m["RW"]}
    if mounts != MOUNTS or len(c["Mounts"]) != len(MOUNTS):
        raise Refusal("runtime_mounts_refused")
    directory = Path(labels["com.docker.compose.project.working_dir"])
    if not directory.resolve().is_relative_to(RELEASES.resolve()):
        raise Refusal("release_directory_refused")
    return {"container_id": c["Id"], "image_id": c["Image"], "image": image,
            "environment": selected, "directory": str(directory),
            "compose": {name: (directory / name).read_text() for name in FILES}}


def require_runtime(environment: dict[str, str], directory: str, files: dict[str, str], *, image_id: str | None = None) -> dict[str, Any]:
    current = observed()  # Includes the fixed runtime security posture and mounts.
    if (current["environment"] != environment or current["image"] != IMAGE + environment["DEVUI_IMAGE_DIGEST"] or
            current["directory"] != directory or current["compose"] != files or
            (image_id is not None and current["image_id"] != image_id)):
        raise Refusal("runtime_configuration_drift")
    return current


def compose(directory: Path, environment: dict[str, str], arguments: list[str]) -> str:
    # No .env, Compose project overrides, caller-supplied files or raw secrets.
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "DOCKER_CONFIG"}}
    env.update(environment)
    env["DEVUI_BUILDEROPS_API_URL"] = env.get("BUILDEROPS_API_URL", "")
    argv = ["docker", "--context", "builderops", "compose", "--env-file", "/dev/null", "-p", PROJECT]
    for name in FILES:
        argv.extend(["-f", str(directory / name)])
    return run(argv + arguments, env=env)


def validate_config(config: dict[str, Any], environment: dict[str, str], *, baseline: bool = False) -> str:
    # Closed effective configuration, including nested commands and bind options.
    # A trusted future image does not expand this operator's component mandate.
    service: dict[str, Any] = {"image": IMAGE + environment["DEVUI_IMAGE_DIGEST"], "command": COMMAND,
               "network_mode": "host", "restart": "unless-stopped", "read_only": True,
               "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
               "environment": environment, "healthcheck": HEALTHCHECK,
               "volumes": [{"type": "bind", "source": source, "target": target,
                            "read_only": True, "bind": {"create_host_path": False}}
                           for source, target in MOUNTS.items()]}
    expected = {"name": PROJECT, "services": {"devui": service}}
    normalized = json.loads(json.dumps(config))
    actual_service = normalized.get("services", {}).get("devui", {})
    if actual_service.get("entrypoint") is None:
        actual_service.pop("entrypoint", None)  # Compose serializes the inherited entrypoint as null.
    actual_volumes = actual_service.get("volumes", [])
    # Compose may reorder mounts; their complete values must still match.
    if not isinstance(actual_volumes, list) or any(not isinstance(v, dict) for v in actual_volumes):
        raise Refusal("compose_mounts_refused")
    for volume in actual_volumes:
        if volume.get("bind") == {}:
            volume["bind"] = {"create_host_path": False}  # Compose omits this false default.
    actual_service["volumes"] = sorted(actual_volumes, key=lambda v: str(v.get("target")))
    service["volumes"] = sorted(service["volumes"], key=lambda v: v["target"])
    optional = {"DEVUI_DIAGNOSTIC_ORIGIN", "DEVUI_CKM_OVERVIEW_URL"}
    valid_keys = [ENV_KEYS, ENV_KEYS - optional] if baseline else [ENV_KEYS]
    if set(environment) not in valid_keys or normalized != expected:
        raise Refusal("compose_boundary_refused")
    sanitized = normalized
    sanitized["services"]["devui"]["environment"].pop("DEVUI_CONFIG_FINGERPRINT", None)
    return digest(sanitized)


def stage(directory: Path, files: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    for name in FILES:
        path = directory / name
        if path.is_symlink() or (path.exists() and path.read_text() != files[name]):
            raise Refusal("staged_compose_drift")
        path.write_text(files[name])


def browser(source_sha: str, *, preflight: bool = False, baseline: bool = False) -> dict[str, Any]:
    args = [sys.executable, str(ROOT / "scripts/devui_component_browser_smoke.py"), "--source-sha", source_sha]
    if preflight:
        args.append("--preflight")
    if baseline:
        args.append("--baseline")
    return json.loads(run(args))


def probe(environment: dict[str, str]) -> dict[str, Any]:
    version = health = None
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8113/version", timeout=3) as response:
                version = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:8113/healthz", timeout=3) as response:
                health = json.load(response)
            if all(version.get(k) == environment[v] for k, v in {
                    "source_sha": "DEVUI_SOURCE_SHA", "image_digest": "DEVUI_IMAGE_DIGEST",
                    "config_fingerprint": "DEVUI_CONFIG_FINGERPRINT"}.items()) and health.get("listener_alive") is True:
                return {"source_sha": version["source_sha"], "image_digest": version["image_digest"],
                        "config_fingerprint": version["config_fingerprint"], "listener_alive": True}
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise Refusal("runtime_probe_failed")


def prepare(candidate_file: Path, authorization: str) -> dict[str, Any]:
    engine = boundary()
    pending()
    if not authorization.strip():
        raise Refusal("operator_reference_missing")
    candidate, candidate_hash = pair(candidate_file)
    baseline = observed()
    probe(baseline["environment"])
    browser(candidate["source_sha"], preflight=True)
    browser(baseline["environment"]["DEVUI_SOURCE_SHA"], baseline=True)
    files = {}
    for name in FILES:
        response = json.loads(gh(["api", f"repos/{REPOSITORY}/contents/{name}?ref={candidate['source_sha']}"]))
        files[name] = base64.b64decode(response["content"]).decode()
    target_env = dict(baseline["environment"])
    target_env.update(DEVUI_SOURCE_SHA=candidate["source_sha"], DEVUI_IMAGE_DIGEST=candidate["control_plane_image_digest"],
                      DEVUI_CONFIG_FINGERPRINT="sha256:" + "0" * 64)
    target_env.setdefault("DEVUI_DIAGNOSTIC_ORIGIN", "")
    target_env.setdefault("DEVUI_CKM_OVERVIEW_URL", "")
    directory = RELEASES / (candidate["source_sha"] + "-devui-component")
    stage(directory, files)
    rendered = json.loads(compose(directory, target_env, ["config", "--format", "json"]))
    target_env["DEVUI_CONFIG_FINGERPRINT"] = validate_config(rendered, target_env)
    validate_config(json.loads(compose(Path(baseline["directory"]), baseline["environment"], ["config", "--format", "json"])), baseline["environment"], baseline=True)
    body = {"contract": "devui_component_promotion_plan.v1", "candidate": candidate,
            "candidate_file_sha256": candidate_hash,
            "engine_id": engine, "authorization_reference": authorization, "baseline": baseline,
            "target_environment": target_env, "target_directory": str(directory), "target_compose": files}
    return {**body, "plan_sha256": digest(body)}


def apply(plan: dict[str, Any], candidate_file: Path, expected_digest: str) -> dict[str, Any]:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if plan.get("contract") != "devui_component_promotion_plan.v1" or plan.get("plan_sha256") != expected_digest or digest(body) != expected_digest:
        raise Refusal("plan_digest_refused")
    engine = boundary()
    pending()
    candidate, candidate_hash = pair(candidate_file)
    if candidate != plan["candidate"] or candidate_hash != plan["candidate_file_sha256"]:
        raise Refusal("candidate_plan_drift")
    if engine != plan["engine_id"] or observed() != plan["baseline"]:
        raise Refusal("baseline_plan_drift")
    attempt = RECEIPTS / ("devui-component-" + expected_digest.removeprefix("sha256:") + ".json")
    if attempt.exists():
        raise Refusal("retained_attempt_requires_readback")
    directory = Path(plan["target_directory"])
    if directory != RELEASES / (candidate["source_sha"] + "-devui-component"):
        raise Refusal("target_directory_refused")
    stage(directory, plan["target_compose"])
    environment = plan["target_environment"]
    if validate_config(json.loads(compose(directory, environment, ["config", "--format", "json"])), environment) != environment["DEVUI_CONFIG_FINGERPRINT"]:
        raise Refusal("target_config_drift")
    baseline = plan["baseline"]
    if {name: (Path(baseline["directory"]) / name).read_text() for name in FILES} != baseline["compose"]:
        raise Refusal("rollback_compose_drift")
    validate_config(json.loads(compose(Path(baseline["directory"]), baseline["environment"], ["config", "--format", "json"])), baseline["environment"], baseline=True)
    probe(baseline["environment"])
    browser(candidate["source_sha"], preflight=True)
    browser(baseline["environment"]["DEVUI_SOURCE_SHA"], baseline=True)
    record: dict[str, Any] = {"receipt_type": "devui_component_deployment.v1", "plan_sha256": expected_digest,
              "observed_at": datetime.now(timezone.utc).isoformat(), "engine_id": engine,
              "candidate_receipt_sha256": plan["candidate_file_sha256"],
              "authorization_reference": plan["authorization_reference"], "source_sha": candidate["source_sha"],
              "image_digest": environment["DEVUI_IMAGE_DIGEST"], "config_fingerprint": environment["DEVUI_CONFIG_FINGERPRINT"],
              "project": PROJECT, "service": "devui", "baseline": baseline,
              "outcome": "pending", "complete_dev_system_health": False, "source_qualification": False,
              "owner_pilot": False, "owner_trial": False, "owner_acceptance": False, "secret_material": "absent"}
    compose(directory, environment, ["pull", "devui"])
    atomic(attempt, record)
    try:
        compose(directory, environment, ["up", "-d", "--no-deps", "--force-recreate", "devui"])
    except Refusal:
        # Unknown client/daemon completion: never compensate or retry blindly.
        record["outcome"] = "indeterminate"
        atomic(attempt, record)
        raise Refusal("compose_outcome_requires_readback") from None
    try:
        record["runtime"] = probe(environment)
        record["browser"] = browser(candidate["source_sha"])
        record["container"] = require_runtime(environment, str(directory), plan["target_compose"])
    except Refusal:
        try:
            # A completed Compose plus exact target readback permits compensation.
            require_runtime(environment, str(directory), plan["target_compose"])
            compose(Path(baseline["directory"]), baseline["environment"], ["up", "-d", "--no-deps", "--force-recreate", "devui"])
            record["rollback_runtime"] = probe(baseline["environment"])
            record["rollback_browser"] = browser(baseline["environment"]["DEVUI_SOURCE_SHA"], baseline=True)
            record["rollback_container"] = require_runtime(baseline["environment"], baseline["directory"],
                                                           baseline["compose"], image_id=baseline["image_id"])
            record["outcome"] = "rolled_back"
        except Refusal:
            record["outcome"] = "indeterminate"
        atomic(attempt, record)
        if record["outcome"] == "rolled_back":
            atomic(RECEIPTS / "devui-component-latest.json", record)
        raise Refusal("component_smoke_failed_" + record["outcome"]) from None
    record["outcome"] = "deployed"
    atomic(attempt, record)
    atomic(RECEIPTS / "devui-component-latest.json", record)
    return record


def rollback(plan: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if digest(body) != expected_digest or plan.get("plan_sha256") != expected_digest:
        raise Refusal("plan_digest_refused")
    engine = boundary()
    pending()
    attempt = RECEIPTS / ("devui-component-" + expected_digest.removeprefix("sha256:") + ".json")
    record = json.loads(attempt.read_text())
    if record.get("outcome") != "deployed" or engine != plan["engine_id"]:
        raise Refusal("rollback_state_refused")
    environment = plan["target_environment"]
    require_runtime(environment, plan["target_directory"], plan["target_compose"])
    baseline = plan["baseline"]
    if {name: (Path(baseline["directory"]) / name).read_text() for name in FILES} != baseline["compose"]:
        raise Refusal("rollback_compose_drift")
    validate_config(json.loads(compose(Path(baseline["directory"]), baseline["environment"], ["config", "--format", "json"])), baseline["environment"], baseline=True)
    browser(baseline["environment"]["DEVUI_SOURCE_SHA"], preflight=True)
    record["outcome"] = "pending"
    atomic(attempt, record)
    try:
        compose(Path(baseline["directory"]), baseline["environment"], ["up", "-d", "--no-deps", "--force-recreate", "devui"])
        record["rollback_runtime"] = probe(baseline["environment"])
        record["rollback_browser"] = browser(baseline["environment"]["DEVUI_SOURCE_SHA"], baseline=True)
        record["rollback_container"] = require_runtime(baseline["environment"], baseline["directory"],
                                                       baseline["compose"], image_id=baseline["image_id"])
        record["outcome"] = "rolled_back"
    except Refusal:
        record["outcome"] = "indeterminate"
        atomic(attempt, record)
        raise Refusal("rollback_outcome_requires_readback") from None
    atomic(attempt, record)
    atomic(RECEIPTS / "devui-component-latest.json", record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "rollback"))
    parser.add_argument("--candidate-pair", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--authorization-reference", default="")
    parser.add_argument("--expected-plan-sha256", default="")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            result = prepare(args.candidate_pair, args.authorization_reference)
            atomic(args.plan, result)
            print(json.dumps({"plan_sha256": result["plan_sha256"], "effect": "none"}))
        elif args.action == "apply":
            result = apply(json.loads(args.plan.read_text()), args.candidate_pair, args.expected_plan_sha256)
            print(json.dumps({"outcome": result["outcome"], "plan_sha256": result["plan_sha256"]}))
        else:
            result = rollback(json.loads(args.plan.read_text()), args.expected_plan_sha256)
            print(json.dumps({"outcome": result["outcome"], "plan_sha256": result["plan_sha256"]}))
    except (Refusal, OSError, ValueError, KeyError, TypeError):
        print("DevUI component promotion refused; consult retained attempt and perform readback", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
