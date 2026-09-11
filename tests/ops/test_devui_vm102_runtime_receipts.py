from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.builderops.devui_receipts import read_vm102_receipt_evidence
from app.ops.builderops_vm_rebuild_activation import build_activation_receipt
from app.ops.devsystem_vm102_component_inventory import build_component_inventory_receipt
from app.ops.devui_vm102_runtime_receipts import (
    ReceiptValidationError,
    build_receipt,
    canonical_digest,
    validate_receipt,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/devui_vm102_runtime"
TYPES = {
    "qualification": "devui_vm102_runtime_qualification.v1",
    "deploy": "devsystem_vm102_deploy.v1",
    "health": "devsystem_vm102_health.v1",
}


def _bundle() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    inventory_evidence = json.loads((FIXTURES / "inventory.json").read_text())
    inventory_evidence["observed_at"] = now
    inventory = build_component_inventory_receipt(inventory_evidence)
    activation_evidence = json.loads((FIXTURES / "activation.json").read_text())
    activation_evidence["observed_at"] = now
    digest = inventory["component_inventory_digest"]
    activation_evidence["component_inventory_digest"] = digest
    activation_evidence["source_refs"] = sorted(
        [
            ref
            for ref in activation_evidence["source_refs"]
            if not ref.startswith("receipt:devsystem_vm102_component_inventory.v1:")
        ]
        + ["receipt:devsystem_vm102_component_inventory.v1:" + digest]
    )
    activation = build_activation_receipt(activation_evidence)
    candidate = {
        **activation["candidate_identity"],
        "devui_image_digest": "sha256:" + "e" * 64,
        "devui_config_fingerprint": "sha256:" + "c" * 64,
    }
    topology = []
    for row in inventory["components"]:
        topology.append(
            {
                "component_id": row["component_id"],
                "owner": row["owner"],
                "placement_class": row["placement_class"],
                "evidence_digest": "a" * 64,
                "state": "excluded"
                if row["component_id"] == "product_runtime"
                else "external"
                if row["placement_class"] == "external_dependency"
                else "prepared",
                "service_or_project": "builderops-devui"
                if row["component_id"] == "devui_projection"
                else activation["dedicated_engine"]["project"]
                if row["component_id"] == "builderops_control_plane"
                else row["component_id"],
                "source_identity_digest": "a" * 64,
                "source_identity": None
                if row["component_id"] == "product_runtime"
                else {
                    "source_sha": candidate["source_sha"],
                    "image_digest": candidate["devui_image_digest"],
                    "config_fingerprint": candidate["config_fingerprint"]
                    if row["component_id"] == "builderops_control_plane"
                    else candidate["devui_config_fingerprint"],
                }
                if row["placement_class"] == "vm102_resident_target"
                else {
                    "source_ref": row["component_id"],
                    "version_digest": "b" * 64,
                },
                "observed_at": now,
                "ingress_auth": "excluded"
                if row["component_id"] == "product_runtime"
                else "internal_authenticated"
                if row["placement_class"] == "vm102_resident_target"
                else "external_source_owned",
                "health_version": "excluded"
                if row["component_id"] == "product_runtime"
                else "not_observed",
                "deployment_owner": row["owner"],
                "migration_rollback": "excluded"
                if row["component_id"] == "product_runtime"
                else "no_migration_restore_image_config"
                if row["component_id"] == "devui_projection"
                else "builderops_governed_no_data_rewind"
                if row["placement_class"] == "vm102_resident_target"
                else "external_source_owned",
            }
        )
    bundle = {
        "evidence": {
            "observed_at": now,
            "candidate_identity": candidate,
            "topology": topology,
            "runtime": {
                "project": "builderops-devui",
                "service": "devui",
                "engine_id": activation["dedicated_engine"]["engine_id"],
                "engine_context": "builderops",
                "engine_socket": "unix:///run/docker-builderops.sock",
                "process_owner": "builderops",
                "bind_host": "127.0.0.1",
                "port": 8113,
                "overview_path": "/api/devui/overview",
                "managed": True,
                "product_runtime_started": False,
                "no_dual_writer": True,
                "private_authenticated_ingress": True,
                "funnel": False,
                "migration": "none",
                "rollback_owner": "builder-system-release-operator",
            },
            "checks": {
                "complete_topology": True,
                "source_image_config_verified": True,
                "read_only_sources": True,
                "listener_contract_verified": True,
            },
        },
        "prerequisites": {"inventory": inventory, "activation": activation},
    }

    _component_evidence(bundle["evidence"], bundle["prerequisites"], "qualification")
    return bundle


def _component_evidence(evidence: dict, prerequisites: dict, kind: str) -> None:
    proofs = {}
    for row in evidence["topology"]:
        if row["placement_class"] == "vm102_resident_target":
            row["state"] = {"qualification": "prepared", "deploy": "deployed", "health": "healthy"}[
                kind
            ]
        if row["placement_class"] != "intentionally_non_runtime":
            row["health_version"] = "verified" if kind == "health" else "not_observed"
        proof = {
            key: value
            for key, value in row.items()
            if key not in {"source_identity_digest", "evidence_digest"}
        }
        row["source_identity_digest"] = canonical_digest(row["source_identity"])
        row["evidence_digest"] = canonical_digest(proof)
        proofs[row["component_id"]] = copy.deepcopy(proof)
    prerequisites.setdefault("component_evidence", {})[kind] = proofs


def _chain(bundle: dict) -> list[dict]:
    evidence = bundle["evidence"]
    prerequisites = bundle["prerequisites"]
    qualification = build_receipt("qualification", evidence, prerequisites)
    prerequisites["qualification"] = qualification
    evidence = {
        **copy.deepcopy(evidence),
        "checks": {
            "deployment_completed": True,
            "vm_local_attestation_verified": True,
            "operator_gate_satisfied": True,
            "migration_completed": True,
        },
        "rollback_baseline_state": "no_baseline",
        "previous_identity": None,
    }
    _component_evidence(evidence, prerequisites, "deploy")
    deploy = build_receipt("deploy", evidence, prerequisites)
    prerequisites["deploy"] = deploy
    health_evidence = {
        **copy.deepcopy(bundle["evidence"]),
        "checks": {
            key: True
            for key in (
                "identity_verified",
                "complete_topology",
                "readiness",
                "ingress_auth_verified",
                "no_dual_writer",
                "read_only_smoke",
                "normal_work",
                "parent_epic_separation",
                "review_verification",
                "blocked_reason",
                "completed_history",
            )
        },
    }
    _component_evidence(health_evidence, prerequisites, "health")
    health = build_receipt("health", health_evidence, prerequisites)
    return [qualification, deploy, health]


def test_complete_receipt_chain_reaches_b1_reader(tmp_path: Path) -> None:
    bundle = _bundle()
    chain = _chain(bundle)
    for kind, receipt in zip(TYPES, chain):
        validate_receipt(receipt, bundle["prerequisites"])
        assert receipt["receipt_type"] == TYPES[kind]
        assert receipt["evidence_fingerprint"] == canonical_digest(
            {k: v for k, v in receipt.items() if k != "evidence_fingerprint"}
        )
        (tmp_path / f"{kind}.json").write_text(json.dumps(receipt))
    result = read_vm102_receipt_evidence(tmp_path)
    assert result["candidate_source_sha"] == bundle["evidence"]["candidate_identity"]["source_sha"]
    assert len(result["receipt_refs"]) == 3
    assert build_receipt("qualification", bundle["evidence"], bundle["prerequisites"]) == chain[0]


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "tampered",
        "stale",
        "future",
        "candidate",
        "topology",
        "unknown_field",
        "listener",
        "secret",
    ],
)
def test_receipt_cli_refuses_invalid_evidence(tmp_path: Path, failure: str) -> None:
    bundle = _bundle()
    if failure == "missing":
        del bundle["prerequisites"]["inventory"]
    elif failure == "tampered":
        bundle["prerequisites"]["inventory"]["evidence_fingerprint"] = "f" * 64
    elif failure in {"stale", "future"}:
        delta = timedelta(days=-2 if failure == "stale" else 2)
        bundle["evidence"]["observed_at"] = (datetime.now(timezone.utc) + delta).isoformat()
    elif failure == "candidate":
        bundle["evidence"]["candidate_identity"]["source_sha"] = "0" * 40
    elif failure == "topology":
        bundle["evidence"]["topology"].pop()
    elif failure == "listener":
        bundle["evidence"]["runtime"]["managed"] = False
    else:
        bundle["evidence"]["unknown" if failure == "unknown_field" else "password"] = (
            "sentinel-never-echo"
        )
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(bundle))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.ops.devui_vm102_runtime_receipts",
            "--kind",
            "qualification",
            "--bundle",
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "sentinel-never-echo" not in result.stdout + result.stderr
    refusal = json.loads(result.stdout)
    assert refusal["verdict"] == "refused"
    assert refusal["mutation_performed"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["evidence.json"]


def test_first_deployment_and_rollback_identity() -> None:
    bundle = _bundle()
    _, deploy, _ = _chain(bundle)
    assert deploy["refusals"] == ["no_compatible_baseline"]
    assert deploy["previous_identity"] is None
    for state, previous in [
        ("available", None),
        ("no_baseline", deploy["candidate_identity"]),
        ("available", {**deploy["candidate_identity"], "source_sha": "0" * 40}),
    ]:
        broken = copy.deepcopy(deploy)
        broken.update(rollback_baseline_state=state, previous_identity=previous)
        broken["evidence_fingerprint"] = canonical_digest(
            {k: v for k, v in broken.items() if k != "evidence_fingerprint"}
        )
        with pytest.raises(ReceiptValidationError):
            validate_receipt(broken, bundle["prerequisites"])


@pytest.mark.parametrize(
    "kind,failure",
    [
        ("deploy", "activation"),
        ("deploy", "candidate"),
        ("deploy", "chronology"),
        ("health", "deploy"),
        ("health", "checks"),
        ("health", "topology"),
        ("health", "source_refs"),
    ],
)
def test_deploy_health_validation_rechecks_prerequisites(kind: str, failure: str) -> None:
    bundle = _bundle()
    chain = _chain(bundle)
    receipt = copy.deepcopy(chain[1 if kind == "deploy" else 2])
    if failure in {"activation", "deploy"}:
        bundle["prerequisites"][failure]["evidence_fingerprint"] = "f" * 64
    elif failure == "candidate":
        receipt["candidate_identity"]["source_sha"] = "d" * 40
    elif failure == "chronology":
        receipt["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    elif failure == "checks":
        receipt["checks"]["readiness"] = False
    elif failure == "topology":
        receipt["topology"][0]["ingress_auth"] = "external_source_owned"
    elif failure == "source_refs":
        receipt["source_refs"].pop()
    receipt["evidence_fingerprint"] = canonical_digest(
        {k: v for k, v in receipt.items() if k != "evidence_fingerprint"}
    )
    with pytest.raises(ReceiptValidationError):
        validate_receipt(receipt, bundle["prerequisites"])


def test_runtime_withdraws_another_candidate_chain(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from app.builderops.devui_runtime import create_app, load_configuration

    bundle = _bundle()
    for receipt in _chain(bundle):
        (tmp_path / f"{receipt['receipt_type']}.json").write_text(json.dumps(receipt))
    (tmp_path / "devui-runtime-prerequisites.json").write_text(
        json.dumps(bundle["prerequisites"])
    )
    candidate = bundle["evidence"]["candidate_identity"]
    env = {
        "VCS_REF": candidate["source_sha"],
        "DEVUI_SOURCE_SHA": candidate["source_sha"],
        "DEVUI_IMAGE_DIGEST": candidate["devui_image_digest"],
        "DEVUI_CONFIG_FINGERPRINT": candidate["devui_config_fingerprint"],
        "DEVUI_VM102_RECEIPT_DIR": str(tmp_path),
    }

    def read(environment: dict) -> dict:
        with TestClient(
            create_app(load_configuration(environment)),
            client=("127.0.0.1", 1000),
            base_url="http://127.0.0.1:8113",
        ) as client:
            response = client.get("/api/devui/overview")
            assert response.status_code == 200
            return response.json()

    assert "DevUI on VM 102" in json.dumps(read(env))
    for key in ("DEVUI_IMAGE_DIGEST", "DEVUI_CONFIG_FINGERPRINT"):
        refused = read({**env, key: "sha256:" + "f" * 64})
        assert "DevUI on VM 102" not in json.dumps(refused)
        assert "runtime_identity_mismatch" in json.dumps(refused)


def test_qualification_does_not_claim_observed_health() -> None:
    bundle = _bundle()
    qualification, deploy, health = _chain(bundle)
    for receipt, state, readiness in (
        (qualification, "prepared", "not_observed"),
        (deploy, "deployed", "not_observed"),
        (health, "healthy", "verified"),
    ):
        row = next(row for row in receipt["topology"] if row["component_id"] == "devui_projection")
        assert (row["state"], row["health_version"]) == (state, readiness)
    broken = copy.deepcopy(bundle["evidence"])
    broken["topology"][0]["health_version"] = "verified"
    with pytest.raises(ReceiptValidationError):
        build_receipt("qualification", broken, bundle["prerequisites"])


@pytest.mark.parametrize("failure", ["missing", "digest", "contents", "identity", "timestamp"])
def test_component_evidence_is_verified(failure: str) -> None:
    bundle = _bundle()
    evidence, prerequisites = bundle["evidence"], bundle["prerequisites"]
    row = evidence["topology"][0]
    proof = prerequisites["component_evidence"]["qualification"][row["component_id"]]
    if failure == "missing":
        del prerequisites["component_evidence"]
    elif failure == "digest":
        row["evidence_digest"] = "f" * 64
    elif failure == "contents":
        proof["service_or_project"] = "different"
    elif failure == "identity":
        row["source_identity_digest"] = "f" * 64
    else:
        proof["observed_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        row["observed_at"] = proof["observed_at"]
        row["evidence_digest"] = canonical_digest(proof)
    with pytest.raises(ReceiptValidationError):
        build_receipt("qualification", evidence, prerequisites)


def test_available_baseline_requires_compatible_known_good_receipts() -> None:
    previous_bundle = _bundle()
    _, previous_deploy, previous_health = _chain(previous_bundle)
    bundle = _bundle()
    _, deploy, _ = _chain(bundle)
    evidence = {key: value for key, value in deploy.items() if key in bundle["evidence"]}
    evidence.update(
        rollback_baseline_state="available", previous_identity=previous_deploy["candidate_identity"]
    )
    prerequisites = bundle["prerequisites"]
    baseline = {
        "deploy": previous_deploy,
        "health": previous_health,
        "compatibility": "verified_no_data_rewind",
    }
    prerequisites["rollback_baseline"] = baseline
    receipt = build_receipt("deploy", evidence, prerequisites)
    assert receipt["refusals"] == []
    assert len(receipt["rollback_baseline_refs"]) == 2
    for failure in (
        "missing",
        "fingerprint",
        "identity",
        "compatibility",
        "linkage",
        "health_stage",
    ):
        broken = copy.deepcopy(prerequisites)
        if failure == "missing":
            del broken["rollback_baseline"]["health"]
        elif failure == "fingerprint":
            broken["rollback_baseline"]["health"]["evidence_fingerprint"] = "f" * 64
        elif failure == "compatibility":
            broken["rollback_baseline"]["compatibility"] = "unknown"
        else:
            prior = broken["rollback_baseline"]["health"]
            if failure == "identity":
                prior["candidate_identity"]["source_sha"] = "d" * 40
            elif failure == "health_stage":
                for row in prior["topology"]:
                    if row["placement_class"] != "intentionally_non_runtime":
                        row["health_version"] = "not_observed"
                    if row["placement_class"] == "vm102_resident_target":
                        row["state"] = "prepared"
                    row["evidence_digest"] = canonical_digest(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"evidence_digest", "source_identity_digest"}
                        }
                    )
                prior["operator_evidence_digest"] = canonical_digest(
                    {key: prior[key] for key in bundle["evidence"]}
                )
                prior["source_refs"] = sorted(
                    [ref for ref in prior["source_refs"] if not ref.startswith("operator:")]
                    + ["operator:sha256:" + prior["operator_evidence_digest"]]
                )
            else:
                prior["source_refs"] = [
                    ref for ref in prior["source_refs"] if "devsystem_vm102_deploy" not in ref
                ]
            prior["evidence_fingerprint"] = canonical_digest(
                {key: value for key, value in prior.items() if key != "evidence_fingerprint"}
            )
        with pytest.raises(ReceiptValidationError):
            build_receipt("deploy", evidence, broken)


@pytest.mark.parametrize("kind", TYPES)
def test_cli_generates_and_verifies_each_type(tmp_path: Path, kind: str) -> None:
    bundle = _bundle()
    receipt = dict(zip(TYPES, _chain(bundle)))[kind]
    evidence = {key: value for key, value in receipt.items() if key in bundle["evidence"]}
    if kind == "deploy":
        evidence.update(
            {key: receipt[key] for key in ("rollback_baseline_state", "previous_identity")}
        )
    for verify in (False, True):
        path = tmp_path / "bundle.json"
        path.write_text(
            json.dumps(
                {
                    "receipt" if verify else "evidence": receipt if verify else evidence,
                    "prerequisites": bundle["prerequisites"],
                }
            )
        )
        command = [
            sys.executable,
            "-m",
            "app.ops.devui_vm102_runtime_receipts",
            "--kind",
            kind,
            "--bundle",
            str(path),
        ]
        result = subprocess.run(
            command + (["--verify"] if verify else []), cwd=ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == receipt


def test_receipt_cli_in_declared_builder_image_closure(tmp_path: Path) -> None:
    import shutil

    # Mirror the declared COPY closure without a daemon, network or service start.
    image_root = tmp_path / "image"
    image_root.mkdir()
    shutil.copytree(ROOT / "app", image_root / "app", ignore=shutil.ignore_patterns("__pycache__"))
    for line in (ROOT / "Dockerfile.builderops").read_text().splitlines():
        if line.startswith("COPY config/platform/"):
            *sources, destination = line.split()[1:]
            target = image_root / destination
            target.mkdir(parents=True)
            for source in sources:
                shutil.copyfile(ROOT / source, target / Path(source).name)
    assert "jsonschema==4.23.0" in (ROOT / "requirements-builderops.txt").read_text()
    bundle = _bundle()
    for kind, receipt in zip(TYPES, _chain(bundle)):
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps({"receipt": receipt, "prerequisites": bundle["prerequisites"]}))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.ops.devui_vm102_runtime_receipts",
                "--kind",
                kind,
                "--verify",
                "--bundle",
                str(path),
            ],
            cwd=image_root,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == receipt


def _refingerprint(receipt: dict) -> None:
    receipt["operator_evidence_digest"] = canonical_digest(
        {
            key: receipt[key]
            for key in (
                "observed_at",
                "candidate_identity",
                "topology",
                "runtime",
                "checks",
                *(
                    ("rollback_baseline_state", "previous_identity")
                    if receipt["receipt_type"] == TYPES["deploy"]
                    else ()
                ),
            )
        }
    )
    receipt["source_refs"] = sorted(
        [ref for ref in receipt["source_refs"] if not ref.startswith("operator:")]
        + ["operator:sha256:" + receipt["operator_evidence_digest"]]
    )
    receipt["evidence_fingerprint"] = canonical_digest(
        {key: value for key, value in receipt.items() if key != "evidence_fingerprint"}
    )


@pytest.mark.parametrize("failure", ["candidate", "project"])
def test_rollback_rejects_rehashed_candidate_topology_mismatch(failure: str) -> None:
    bundle = _bundle()
    _, deploy, health = _chain(bundle)
    prior_deploy, prior_health = copy.deepcopy(deploy), copy.deepcopy(health)
    old_ref = "receipt:" + TYPES["deploy"] + ":" + canonical_digest(prior_deploy)
    for prior in (prior_deploy, prior_health):
        if failure == "candidate":
            prior["candidate_identity"]["source_sha"] = "d" * 40
        else:
            row = next(row for row in prior["topology"] if row["component_id"] == "builderops_control_plane")
            row["service_or_project"] = "unrelated-project"
            row["evidence_digest"] = canonical_digest({
                key: value for key, value in row.items()
                if key not in {"evidence_digest", "source_identity_digest"}
            })
    _refingerprint(prior_deploy)
    prior_health["source_refs"] = [ref for ref in prior_health["source_refs"] if ref != old_ref] + [
        "receipt:" + TYPES["deploy"] + ":" + canonical_digest(prior_deploy)
    ]
    _refingerprint(prior_health)
    prerequisites = bundle["prerequisites"]
    prerequisites["rollback_baseline"] = {
        "deploy": prior_deploy,
        "health": prior_health,
        "compatibility": "verified_no_data_rewind",
    }
    evidence = {key: deploy[key] for key in bundle["evidence"]}
    evidence.update(
        rollback_baseline_state="available", previous_identity=prior_deploy["candidate_identity"]
    )
    with pytest.raises(
        ReceiptValidationError,
        match="topology must bind" if failure == "candidate" else "control-plane project",
    ):
        build_receipt("deploy", evidence, prerequisites)


@pytest.mark.parametrize("kind", ["deploy", "health"])
def test_component_observations_follow_stage_prerequisites(kind: str) -> None:
    bundle = _bundle()
    receipt = copy.deepcopy(dict(zip(TYPES, _chain(bundle)))[kind])
    evidence = {key: receipt[key] for key in bundle["evidence"]}
    if kind == "deploy":
        evidence.update(rollback_baseline_state="no_baseline", previous_identity=None)
    for row in evidence["topology"]:
        if row["placement_class"] != "intentionally_non_runtime":
            row["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _component_evidence(evidence, bundle["prerequisites"], kind)
    with pytest.raises(ReceiptValidationError, match="predates its stage prerequisite"):
        build_receipt(kind, evidence, bundle["prerequisites"])
    receipt.update(evidence)
    _refingerprint(receipt)
    with pytest.raises(ReceiptValidationError, match="predates its stage prerequisite"):
        validate_receipt(receipt, bundle["prerequisites"])


@pytest.mark.parametrize(
    "failure", [None, "qualification", "deploy", "health", "missing", "malformed", "source_packet", "activation"]
)
def test_listener_admits_only_owner_verified_typed_evidence(tmp_path: Path, failure: str | None) -> None:
    from fastapi.testclient import TestClient
    from app.builderops.devui_runtime import create_app, load_configuration

    bundle = _bundle()
    chain = _chain(bundle)
    if failure in TYPES:
        receipt = chain[list(TYPES).index(failure)]
        receipt["topology"] = []
        receipt["checks"][next(iter(receipt["checks"]))] = False
        receipt["evidence_fingerprint"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "evidence_fingerprint"}
        )
    elif failure == "source_packet":
        del bundle["prerequisites"]["component_evidence"]["health"]["devui_projection"]
    elif failure == "activation":
        del bundle["prerequisites"]["activation"]
    for receipt in chain:
        (tmp_path / f"{receipt['receipt_type']}.json").write_text(json.dumps(receipt))
    if failure != "missing":
        (tmp_path / "devui-runtime-prerequisites.json").write_text(
            "[" if failure == "malformed" else json.dumps(bundle["prerequisites"])
        )
    candidate = bundle["evidence"]["candidate_identity"]
    configuration = load_configuration({
        "VCS_REF": candidate["source_sha"],
        "DEVUI_SOURCE_SHA": candidate["source_sha"],
        "DEVUI_IMAGE_DIGEST": candidate["devui_image_digest"],
        "DEVUI_CONFIG_FINGERPRINT": candidate["devui_config_fingerprint"],
        "DEVUI_VM102_RECEIPT_DIR": str(tmp_path),
    })
    with TestClient(
        create_app(configuration), client=("127.0.0.1", 1000), base_url="http://127.0.0.1:8113"
    ) as client:
        response = client.get("/api/devui/overview")
        assert response.status_code == 200
        assert ("DevUI on VM 102" in response.text) == (failure is None)
        if failure is not None:
            assert "evidence_unavailable" in response.text
            assert candidate["devui_image_digest"] not in response.text


def test_control_plane_project_must_match_activation() -> None:
    bundle = _bundle()
    row = next(
        row for row in bundle["evidence"]["topology"] if row["component_id"] == "builderops_control_plane"
    )
    row["service_or_project"] = "unrelated-project"
    _component_evidence(bundle["evidence"], bundle["prerequisites"], "qualification")
    with pytest.raises(ReceiptValidationError, match="control-plane project"):
        _chain(bundle)

    bundle = _bundle()
    _, deploy, health = _chain(bundle)
    for receipt, kind in ((deploy, "deploy"), (health, "health")):
        broken = copy.deepcopy(receipt)
        row = next(row for row in broken["topology"] if row["component_id"] == "builderops_control_plane")
        row["service_or_project"] = "unrelated-project"
        prerequisites = copy.deepcopy(bundle["prerequisites"])
        _component_evidence(broken, prerequisites, kind)
        _refingerprint(broken)
        with pytest.raises(ReceiptValidationError, match="control-plane project"):
            validate_receipt(broken, prerequisites)
