"""Exercise the production promotion/rollback call sites with isolated external I/O."""
from __future__ import annotations

import base64
import copy
import fcntl
import json
import os
from pathlib import Path

import pytest

from app.ops import devui_component_promotion as deploy

OLD = "1" * 40
NEW = "2" * 40
OLD_DIGEST = "sha256:" + "3" * 64
NEW_DIGEST = "sha256:" + "4" * 64


class External:
    def __init__(self, root):
        self.root = root
        self.directory = root / "releases" / (OLD + "-devui")
        self.directory.mkdir(parents=True)
        self.files = {n: (deploy.ROOT / n).read_text() for n in deploy.FILES}
        for name, text in self.files.items():
            (self.directory / name).write_text(text)
        self.environment = {
            "DEVUI_SOURCE_SHA": OLD, "DEVUI_IMAGE_DIGEST": OLD_DIGEST,
            "DEVUI_CONFIG_FINGERPRINT": "sha256:" + "5" * 64,
            "DEVUI_VM102_RECEIPT_DIR": "/run/builderops/devui-receipts",
            "DEVUI_REPOSITORY": deploy.REPOSITORY, "DEVUI_BUILDEROPS_AUTHORITY_EPOCH": "1",
            "BUILDEROPS_API_URL": "http://127.0.0.1:18100",
            "BUILDEROPS_API_TOKEN_FILE": "/run/builderops/devui-api-token",
            "DEVUI_GITHUB_ENABLED": "true", "GH_CONFIG_DIR": "/run/builderops/devui-gh",
            "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1",
            "DEVUI_DIAGNOSTIC_ORIGIN": "", "DEVUI_CKM_OVERVIEW_URL": "",
        }
        self.commands = []
        self.endpoint = "unix:///run/docker-builderops.sock"
        self.unsafe_compose = False
        self.fail_attestation = False
        self.fail_smoke = False
        self.uncertain_up = False
        self.identity = 0
        self.config_extra = {}
        self.compact_compose = True
        self.host_extra = {}
        self.drift_after_up = None
        self.expected_baseline = None

    def container(self):
        return {"Id": str(self.identity), "Image": "sha256:" + "a" * 64,
                "Config": {"User": "builderops", "Cmd": deploy.COMMAND, "Entrypoint": None,
                           "Healthcheck": {"Test": deploy.HEALTH_TEST, "Interval": 30000000000,
                                           "Timeout": 5000000000, "Retries": 3}, "Image": deploy.IMAGE + self.environment["DEVUI_IMAGE_DIGEST"],
                           "Env": [k + "=" + v for k, v in self.environment.items()],
                           "Labels": {"com.docker.compose.project": deploy.PROJECT,
                                      "com.docker.compose.service": "devui",
                                      "com.docker.compose.project.working_dir": str(self.directory),
                                      "org.opencontainers.image.revision": self.environment["DEVUI_SOURCE_SHA"]}},
                "State": {"Running": True}, "HostConfig": {"NetworkMode": "host", "ReadonlyRootfs": True, "IpcMode": "private",
                    "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                    "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0}, **self.host_extra},
                "Mounts": [{"Source": k, "Destination": v, "RW": False} for k, v in deploy.MOUNTS.items()]}

    def config(self, env):
        selected = {k: v for k, v in env.items() if k in deploy.ENV_KEYS}
        service = {"image": deploy.IMAGE + env["DEVUI_IMAGE_DIGEST"],
                   "command": ["python", "-m", "app.builderops.devui_runtime"], "network_mode": "host",
                   "restart": "unless-stopped", "healthcheck": deploy.HEALTHCHECK,
                   "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                   "environment": selected, "volumes": [{"type": "bind", "source": k, "target": v,
                       "read_only": True, "bind": {"create_host_path": False}} for k, v in deploy.MOUNTS.items()]}
        if self.compact_compose:
            service["entrypoint"] = None
            for volume in service["volumes"]:
                volume["bind"] = {}
        service.update(self.config_extra)
        if self.unsafe_compose:
            service["privileged"] = True
        return {"name": deploy.PROJECT, "services": {"devui": service}}

    def run(self, argv, *, env=None):
        self.commands.append(list(argv))
        if "gh" in argv:
            if "attestation" in argv:
                if self.fail_attestation:
                    raise deploy.Refusal("attestation_failed")
                return "verified"
            name = next(n for n in deploy.FILES if n in argv[-1])
            return json.dumps({"content": base64.b64encode(self.files[name].encode()).decode()})
        if argv[0] == "docker":
            if "context" in argv:
                return self.endpoint
            if "info" in argv:
                return "fixed-engine-identity"
            if "inspect" in argv:
                return json.dumps([self.container()])
            assert "compose" in argv and argv[argv.index("-p") + 1] == deploy.PROJECT
            assert "--env-file" in argv and argv[argv.index("--env-file") + 1] == "/dev/null"
            if "config" in argv:
                return json.dumps(self.config(env))
            if "pull" in argv:
                assert argv[-2:] == ["pull", "devui"]
                return ""
            assert argv[-5:] == ["up", "-d", "--no-deps", "--force-recreate", "devui"]
            records = [json.loads(p.read_text()) for p in deploy.RECEIPTS.glob("devui-component-*.json")
                       if p.name != "devui-component-latest.json"]
            pending = [r for r in records if r["outcome"] == "pending"]
            assert len(pending) == 1  # The first external effect already has durable recovery state.
            assert pending[0]["baseline"] == self.expected_baseline
            self.environment = {k: v for k, v in env.items() if k in deploy.ENV_KEYS}
            self.directory = Path(argv[argv.index("-f") + 1]).parent
            self.identity += 1
            if self.drift_after_up == self.identity:
                self.environment["DEVUI_BUILDEROPS_AUTHORITY_EPOCH"] = "unexpected-drift"
            if self.uncertain_up:
                raise deploy.Refusal("external_command_indeterminate")
            return ""
        assert argv[1].endswith("devui_component_browser_smoke.py")
        if self.fail_smoke and "--preflight" not in argv and "--baseline" not in argv:
            self.fail_smoke = False
            raise deploy.Refusal("browser_smoke_failed")
        return json.dumps({"source_sha": argv[argv.index("--source-sha") + 1],
                           "browser_launch": True, "owner_acceptance": False})

    def urlopen(self, url, **kwargs):
        import io
        if url.endswith("/version"):
            return io.BytesIO(json.dumps({"source_sha": self.environment["DEVUI_SOURCE_SHA"],
                "image_digest": self.environment["DEVUI_IMAGE_DIGEST"],
                "config_fingerprint": self.environment["DEVUI_CONFIG_FINGERPRINT"]}).encode())
        return io.BytesIO(b'{"listener_alive":true,"complete_dev_system_health":false}')

    def mutations(self):
        return [c for c in self.commands if c[0] == "docker" and "up" in c]


@pytest.fixture
def operator(tmp_path, monkeypatch):
    world = External(tmp_path)
    lock = tmp_path / "interlock" / "deployment.lock"
    lock.parent.mkdir(mode=0o700)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    monkeypatch.setattr(deploy, "LOCK", lock)
    monkeypatch.setattr(deploy, "RELEASES", tmp_path / "releases")
    monkeypatch.setattr(deploy, "RECEIPTS", tmp_path / "receipts")
    monkeypatch.setattr(deploy.os, "geteuid", lambda: 0)
    monkeypatch.setattr(deploy.socket, "gethostname", lambda: "builder-system")
    monkeypatch.setenv("BUILDEROPS_DEPLOYMENT_LOCK_FD", str(fd))
    original_prepare = deploy.prepare
    def remember_baseline(*args):
        plan = original_prepare(*args)
        world.expected_baseline = plan["baseline"]
        return plan
    monkeypatch.setattr(deploy, "prepare", remember_baseline)
    monkeypatch.setattr(deploy, "run", world.run)
    monkeypatch.setattr(deploy.urllib.request, "urlopen", world.urlopen)
    monkeypatch.setattr(deploy.time, "sleep", lambda _: None)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"receipt_version": 1, "repository": deploy.REPOSITORY,
        "workflow": ".github/workflows/app-image-build.yml", "event_name": "push", "source_ref": "refs/heads/main",
        "durability_posture": "rebuildable", "platform": "linux/amd64", "source_sha": NEW,
        "control_plane_image_digest": NEW_DIGEST, "postgres_image_digest": "sha256:" + "6" * 64}))
    try:
        yield world, candidate
    finally:
        os.close(fd)


def test_promotion_preserves_component_boundary_and_attestation(operator):
    world, candidate = operator
    plan = deploy.prepare(candidate, "github:issue:6105; explicit owner mandate")
    assert not world.mutations()
    result = deploy.apply(plan, candidate, plan["plan_sha256"])
    assert result["outcome"] == "deployed"
    assert len(world.mutations()) == 1
    assert world.environment["DEVUI_SOURCE_SHA"] == NEW
    assert world.environment["DEVUI_BUILDEROPS_AUTHORITY_EPOCH"] == "1"
    attestations = [i for i, c in enumerate(world.commands) if "attestation" in c]
    mutation = world.commands.index(world.mutations()[0])
    assert len(attestations) == 2 and max(attestations) < mutation
    assert all(c[-1] == "devui" for c in world.mutations())
    assert not any("migrate" in c or "worker" in c or "db" in c for c in world.commands)
    assert deploy.rollback(plan, plan["plan_sha256"])["outcome"] == "rolled_back"
    assert world.environment["DEVUI_SOURCE_SHA"] == OLD


@pytest.mark.parametrize("failure", ["context", "attestation", "unsafe_compose", "baseline", "plan", "pending"])
def test_preflight_refuses_drift_before_service_mutation(operator, failure):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    if failure == "context":
        world.endpoint = "unix:///var/run/docker.sock"
    elif failure == "attestation":
        world.fail_attestation = True
    elif failure == "unsafe_compose":
        world.unsafe_compose = True
    elif failure == "baseline":
        world.identity += 1
    elif failure == "plan":
        plan = copy.deepcopy(plan)
        plan["target_environment"]["DEVUI_REPOSITORY"] = "Other/Repository"
    else:
        deploy.atomic(deploy.RECEIPTS / ("devui-component-" + "b" * 64 + ".json"),
                      {"receipt_type": "devui_component_deployment.v1", "outcome": "indeterminate"})
    with pytest.raises(deploy.Refusal):
        deploy.apply(plan, candidate, plan["plan_sha256"])
    assert not world.mutations()


def test_failed_smoke_restores_exact_baseline_and_uncertainty_refuses_replay(operator):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    world.fail_smoke = True
    with pytest.raises(deploy.Refusal, match="rolled_back"):
        deploy.apply(plan, candidate, plan["plan_sha256"])
    assert world.environment == plan["baseline"]["environment"]
    assert len(world.mutations()) == 2
    second = deploy.prepare(candidate, "fresh same-owner attempt")
    world.uncertain_up = True
    with pytest.raises(deploy.Refusal, match="readback"):
        deploy.apply(second, candidate, second["plan_sha256"])
    count = len(world.mutations())
    with pytest.raises(deploy.Refusal, match="retained_attempt"):
        deploy.prepare(candidate, "another attempted plan cannot bypass uncertainty")
    assert len(world.mutations()) == count


def test_component_evidence_does_not_grant_fullsystem_or_acceptance(operator):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    result = deploy.apply(plan, candidate, plan["plan_sha256"])
    retained = json.loads((deploy.RECEIPTS / "devui-component-latest.json").read_text())
    assert result == retained
    for field in ["complete_dev_system_health", "source_qualification", "owner_pilot", "owner_trial", "owner_acceptance"]:
        assert retained[field] is False
    assert retained["receipt_type"] == "devui_component_deployment.v1"
    assert retained["runtime"]["source_sha"] == NEW
    assert retained["runtime"]["image_digest"] == NEW_DIGEST
    assert retained["runtime"]["config_fingerprint"] == world.environment["DEVUI_CONFIG_FINGERPRINT"]
    assert retained["secret_material"] == "absent"


@pytest.mark.parametrize("extra", [
    {"cap_add": ["SYS_ADMIN"]}, {"entrypoint": ["sh", "-c", "id"]}, {"volumes_from": ["container:builderops-api-1:rw"]},
    {"post_start": [{"command": "id", "user": "root", "privileged": True}]},
    {"pre_stop": [{"command": "id"}]}, {"healthcheck": {"test": ["CMD", "sh", "-c", "id"]}},
    {"volumes": [{"type": "bind", "source": "/", "target": "/host", "read_only": False}]},
    {"volumes": [{"type": "bind", "source": source, "target": target, "read_only": True,
                  "bind": {"create_host_path": True}} for source, target in deploy.MOUNTS.items()]},
    {"volumes": [{"type": "bind", "source": source, "target": target, "read_only": True,
                  "bind": {"create_host_path": False, "propagation": "rshared"}}
                 for source, target in deploy.MOUNTS.items()]},
])
def test_effective_compose_is_closed_before_mutation(operator, extra):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    world.config_extra = extra
    with pytest.raises(deploy.Refusal, match="compose_"):
        deploy.apply(plan, candidate, plan["plan_sha256"])
    assert not world.mutations()


@pytest.mark.parametrize("posture", [{"Privileged": True}, {"CapAdd": ["SYS_ADMIN"]},
                                    {"VolumesFrom": ["container:api:rw"]},
                                    {"SecurityOpt": []}, {"Devices": [{"PathOnHost": "/dev/sda"}]}])
def test_runtime_posture_drift_refuses_before_mutation(operator, posture):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    world.host_extra = posture
    with pytest.raises(deploy.Refusal, match="runtime_posture"):
        deploy.apply(plan, candidate, plan["plan_sha256"])
    assert not world.mutations()


def test_target_config_drift_prevents_compensation(operator):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    world.drift_after_up = 1
    world.fail_smoke = True
    with pytest.raises(deploy.Refusal, match="indeterminate"):
        deploy.apply(plan, candidate, plan["plan_sha256"])
    assert len(world.mutations()) == 1
    with pytest.raises(deploy.Refusal, match="retained_attempt"):
        deploy.prepare(candidate, "no replay")


@pytest.mark.parametrize("manual", [False, True])
def test_rollback_requires_observed_exact_baseline(operator, manual):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    world.drift_after_up = 2
    if manual:
        deploy.apply(plan, candidate, plan["plan_sha256"])
        effect = lambda: deploy.rollback(plan, plan["plan_sha256"])
    else:
        world.fail_smoke = True
        effect = lambda: deploy.apply(plan, candidate, plan["plan_sha256"])
    with pytest.raises(deploy.Refusal, match="indeterminate|readback"):
        effect()
    record = json.loads(next(p for p in deploy.RECEIPTS.glob("devui-component-*.json")
                             if p.name != "devui-component-latest.json").read_text())
    assert record["outcome"] == "indeterminate"
    assert len(world.mutations()) == 2


def test_retained_pending_refuses_restart_before_effect(operator):
    world, candidate = operator
    plan = deploy.prepare(candidate, "owner mandate")
    deploy.atomic(deploy.RECEIPTS / ("devui-component-" + "c" * 64 + ".json"),
                  {"receipt_type": "devui_component_deployment.v1", "outcome": "pending", "baseline": plan["baseline"]})
    with pytest.raises(deploy.Refusal, match="retained_attempt"):
        deploy.prepare(candidate, "restart")
    assert not world.mutations()


def test_host_compose_serialization_and_legacy_baseline(operator):
    world, candidate = operator
    del world.environment["DEVUI_DIAGNOSTIC_ORIGIN"]
    del world.environment["DEVUI_CKM_OVERVIEW_URL"]
    plan = deploy.prepare(candidate, "owner mandate")
    assert len(plan["baseline"]["environment"]) == 12
    assert len(plan["target_environment"]) == 14
    assert deploy.apply(plan, candidate, plan["plan_sha256"])["outcome"] == "deployed"
    assert deploy.rollback(plan, plan["plan_sha256"])["outcome"] == "rolled_back"
    assert world.environment == plan["baseline"]["environment"]
    config = world.config(world.environment)
    with pytest.raises(deploy.Refusal):  # Legacy serialization never relaxes candidate env requirements.
        deploy.validate_config(config, world.environment)
    assert deploy.validate_config(config, world.environment, baseline=True)
    full = dict(world.environment, DEVUI_DIAGNOSTIC_ORIGIN="", DEVUI_CKM_OVERVIEW_URL="")
    compact = world.config(full)
    world.compact_compose = False
    assert deploy.validate_config(compact, full) == deploy.validate_config(world.config(full), full)
