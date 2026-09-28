"""Fresh BuilderOps authority reconciliation; never performs a GitHub write.

The operator supplies the existing deployment pin and candidate-pair receipt.
The reader authenticates their provenance and two complete lifecycle inventories.
Only this transaction can produce the receipt that admits ordinary store writers.
VM deployment and its independent no-dual-writer admission remain separate gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from app.builderops.cockpit_github_plane import GithubReadError, _paged_rest, _run_gh
from app.builderops.control_plane.models import canonical_repository

_SOURCE_REPOSITORY = "RasmusTho/agentic-pkm-mvp"
_WORKFLOW = ".github/workflows/app-image-build.yml"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def receipt_matches(row: Mapping[str, Any]) -> bool:
    receipt = row.get("bootstrap_receipt")
    return bool(
        row.get("executor_enabled") and not row.get("reconciliation_required")
        and row.get("bootstrap_status") == "converged"
        and isinstance(receipt, dict)
        and receipt == {
            "schema": "builderops-authority-convergence.v1",
            "bootstrap_id": str(row["bootstrap_id"]),
            "authority_epoch": int(row["activated_authority_epoch"]),
            "config_digest": digest(row.get("bootstrap_config")),
            "readback_digest": digest(row.get("bootstrap_readback")),
        }
        and isinstance(row.get("bootstrap_config"), dict)
        and isinstance(row.get("bootstrap_readback"), dict)
    )


class BootstrapRefusal(RuntimeError):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


def _configuration(pin: bytes, candidate: bytes, repositories: Sequence[str]) -> dict[str, Any]:
    try:
        pairs = [line.split("=", 1) for line in pin.decode().splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        pins = dict(pairs)
        if len(pairs) != len(pins):
            raise ValueError("duplicate pin")
        payload = json.loads(candidate)
        expected = {"receipt_version": 1, "repository": _SOURCE_REPOSITORY,
                    "workflow": _WORKFLOW, "event_name": "push", "source_ref": "refs/heads/main",
                    "durability_posture": "rebuildable", "platform": "linux/amd64"}
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ValueError("candidate provenance")
        source = pins["BUILDEROPS_SOURCE_SHA"]
        control = pins["BUILDEROPS_IMAGE_DIGEST"]
        postgres = pins["BUILDEROPS_POSTGRES_IMAGE_DIGEST"]
        if not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValueError("source pin")
        if any(not re.fullmatch(r"sha256:[0-9a-f]{64}", item) for item in (control, postgres)):
            raise ValueError("image pin")
        if (payload.get("source_sha"), payload.get("control_plane_image_digest"),
                payload.get("postgres_image_digest")) != (source, control, postgres):
            raise ValueError("candidate pins")
        candidate_digest = hashlib.sha256(candidate).hexdigest()
        if pins.get("BUILDEROPS_CANDIDATE_RECEIPT_SHA") != candidate_digest:
            raise ValueError("candidate receipt pin")
        repos = sorted({canonical_repository(repo) for repo in repositories})
        if not repos:
            raise ValueError("repository inventory missing")
        return {"repositories": repos, "source_sha": source, "control_plane_image_digest": control,
                "postgres_image_digest": postgres, "candidate_digest": candidate_digest,
                "pin_digest": hashlib.sha256(pin).hexdigest()}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise BootstrapRefusal("conflict", "configured_authority_mismatch") from exc


def _authenticate_candidate(candidate: bytes, source_sha: str) -> None:
    # Verify the exact bytes parsed above, not a mutable caller path. stderr and
    # credential-bearing subprocess diagnostics never enter receipts or health.
    with tempfile.NamedTemporaryFile(prefix="builderops-candidate-", suffix=".json") as snapshot:
        snapshot.write(candidate)
        snapshot.flush()
        result = subprocess.run(
            ["gh", "attestation", "verify", snapshot.name, "--repo", _SOURCE_REPOSITORY,
             "--signer-workflow", f"{_SOURCE_REPOSITORY}/{_WORKFLOW}",
             "--source-ref", "refs/heads/main", "--source-digest", source_sha],
            capture_output=True, timeout=60, check=False,
        )
        if result.returncode:
            raise BootstrapRefusal("unknown", "candidate_authentication_unavailable")


def _readback(config: Mapping[str, Any]) -> dict[str, Any]:
    principal = _run_gh(["api", "user", "--method", "GET"])
    if not isinstance(principal, dict) or not isinstance(principal.get("id"), int):
        raise BootstrapRefusal("unknown", "github_authentication_unavailable")
    commit = _run_gh(["api", f"repos/{_SOURCE_REPOSITORY}/commits/{config['source_sha']}",
                      "--method", "GET"])
    if not isinstance(commit, dict) or commit.get("sha") != config["source_sha"]:
        raise BootstrapRefusal("conflict", "source_readback_mismatch")
    inventories: dict[str, Any] = {}
    for repository in config["repositories"]:
        owner, name = repository.split("/", 1)
        issues = _paged_rest(owner, name, "issues", page_size=100, max_pages=100,
                             extra_fields=("state=all", "sort=created", "direction=asc"))
        pulls = _paged_rest(owner, name, "pulls", page_size=100, max_pages=100,
                            extra_fields=("state=all", "sort=created", "direction=asc"))
        normalized: dict[str, Any] = {}
        for item in issues:
            number, state = item["number"], item["state"]
            if type(number) is not int or number <= 0 or state not in {"open", "closed"}:
                raise BootstrapRefusal("unknown", "incomplete_github_lifecycle")
            labels = sorted(label["name"] for label in item["labels"])
            agents = [label for label in labels if label.startswith("agent:")]
            if len(agents) > 1 or str(number) in normalized:
                raise BootstrapRefusal("conflict", "contradictory_github_lifecycle")
            normalized[str(number)] = {"state": state, "labels": labels,
                                       "updated_at": item["updated_at"],
                                       "body_digest": hashlib.sha256((item.get("body") or "").encode()).hexdigest(),
                                       "kind": "pull" if "pull_request" in item else "issue"}
        seen: set[int] = set()
        for pull in pulls:
            number = pull["number"]
            issue = normalized.get(str(number))
            if (number in seen or issue is None or issue["kind"] != "pull"
                    or issue["state"] != pull["state"]):
                raise BootstrapRefusal("conflict", "contradictory_pull_lifecycle")
            seen.add(number)
            issue.update({"head_sha": pull["head"]["sha"], "base_sha": pull["base"]["sha"],
                          "merged_at": pull["merged_at"], "updated_at": pull["updated_at"]})
        if len(seen) != sum(item["kind"] == "pull" for item in normalized.values()):
            raise BootstrapRefusal("unknown", "incomplete_pull_lifecycle")
        inventories[repository] = normalized
    return {"principal_id": principal["id"], "repositories": inventories,
            "source_sha": commit["sha"]}


def _reconcile_surviving_tasks(conn: Any, readback: Mapping[str, Any]) -> None:
    """Retain surviving facts only when their explicit source still agrees.

    An unknown source is not evidence of deletion or permission to reconstruct
    work. Non-GitHub authority objects need their own existing reconciliation.
    """
    tasks = conn.execute("SELECT repository, task_id, state, payload FROM builderops_tasks").fetchall()
    for task in tasks:
        payload = task["payload"]
        number = payload.get("issue_number")
        repository = task["repository"]
        if (type(number) is not int or payload.get("repo") != repository
                or task["task_id"] != f"github-{repository.replace('/', '--')}-issue-{number}"):
            raise BootstrapRefusal("unknown", "surviving_task_source_unknown")
        issue = readback["repositories"].get(repository, {}).get(str(number))
        if issue is None or issue["kind"] != "issue":
            raise BootstrapRefusal("unknown", "surviving_task_readback_missing")
        labels = set(issue["labels"])
        if issue["state"] == "closed":
            expected = {"completed"}
        elif "agent:ready" in labels:
            expected = {"ready"}
        elif labels & {"agent:blocked", "agent:needs-human"}:
            expected = {"blocked"}
        elif "agent:in-progress" in labels:
            # The task kernel persists claimed; the GitHub projection uses
            # in_progress. Neither lifecycle fact revives the retired lease.
            expected = {"claimed", "in_progress"}
        else:
            expected = set()
        sync = payload.get("sync_state") or {}
        if (task["state"] not in expected
                or sync.get("body_sha256") != issue["body_digest"]
                or sync.get("source_version") != issue["updated_at"]):
            raise BootstrapRefusal("conflict", "surviving_task_lifecycle_mismatch")
    extra = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM builderops_records) "
        "OR EXISTS(SELECT 1 FROM builderops_promotions) "
        "OR EXISTS(SELECT 1 FROM builderops_attempts WHERE state NOT IN "
        "('completed','failed','cancelled')) AS unresolved"
    ).fetchone()
    if extra["unresolved"]:
        raise BootstrapRefusal("unknown", "surviving_authority_requires_source_readback")


def bootstrap_from_authority(store: Any, *, pin_file: Path, candidate_receipt: Path,
                             repositories: Sequence[str]) -> dict[str, Any]:
    """Authenticate readback and atomically admit one current-epoch receipt.

    A session advisory lock owns reconciliation across durable checkpoint commits.
    A crash releases that lock while retaining the fence and readback evidence.
    Unknown historical effects require the existing explicit reconciliation path;
    no task, intent, claim, or effect is recreated from a missing local record.
    """
    with store._connect() as conn:
        lock = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(current_schema() || "
                            "'builderops-bootstrap', 0)) AS held").fetchone()
        if not lock or not lock["held"]:
            return {"status": "conflict", "reason": "reconciliation_in_progress"}
        try:
            row = conn.execute("UPDATE builderops_recovery_state SET executor_enabled=false, "
                               "reconciliation_required=true, bootstrap_receipt=NULL, bootstrap_status='unknown' "
                               "WHERE singleton RETURNING *").fetchone()
            if row is None:
                raise RuntimeError("BuilderOps bootstrap state is not initialized")
            store._bind_authority(conn)
            identity, epoch = str(row["bootstrap_id"]), int(row["activated_authority_epoch"])
            conn.commit()  # Fence survives network failure, process loss, and retry.
            try:
                pin, candidate = pin_file.read_bytes(), candidate_receipt.read_bytes()
                config = _configuration(pin, candidate, repositories)
                if row["bootstrap_config"] is not None and row["bootstrap_config"] != config:
                    raise BootstrapRefusal("conflict", "bootstrap_authority_changed")
                _authenticate_candidate(candidate, config["source_sha"])
                first = _readback(config)
                conn.execute("UPDATE builderops_recovery_state SET bootstrap_config=%s, "
                             "bootstrap_readback=%s, bootstrap_status='unknown', "
                             "bootstrap_reason='confirming_readback' WHERE singleton",
                             (Jsonb(config), Jsonb(first)))
                conn.commit()
                second = _readback(config)
                if first != second:
                    raise BootstrapRefusal("conflict", "github_authority_changed")
                if pin_file.read_bytes() != pin or candidate_receipt.read_bytes() != candidate:
                    raise BootstrapRefusal("conflict", "configured_authority_changed")
                current = conn.execute("SELECT * FROM builderops_recovery_state WHERE singleton "
                                       "FOR UPDATE").fetchone()
                if (str(current["bootstrap_id"]), int(current["activated_authority_epoch"])) != (identity, epoch):
                    raise BootstrapRefusal("conflict", "authority_epoch_changed")
                pending = conn.execute("SELECT EXISTS(SELECT 1 FROM builderops_outbox WHERE "
                                       "status IN ('unknown','claimed') OR (status='pending' AND "
                                       "(reconciliation_lsn IS NULL OR reconciliation_receipt_sequence IS NULL "
                                       "OR reconciliation_evidence IS NULL OR NOT EXISTS (SELECT 1 FROM "
                                       "builderops_outbox_reconciliations AS proof WHERE "
                                       "proof.repository=builderops_outbox.repository AND "
                                       "proof.operation_key=builderops_outbox.operation_key AND "
                                       "proof.receipt_sequence=builderops_outbox.reconciliation_receipt_sequence AND "
                                       "proof.claim_fencing_token=builderops_outbox.claim_fencing_token AND "
                                       "proof.recovery_lsn=builderops_outbox.reconciliation_lsn AND "
                                       "proof.evidence=builderops_outbox.reconciliation_evidence AND "
                                       "NOT proof.observed_applied AND proof.status='pending' AND "
                                       "proof.evidence->>'readback'='not-found')))) AS pending").fetchone()
                if pending["pending"]:
                    raise BootstrapRefusal("unknown", "historical_effects_require_readback")
                active = conn.execute("SELECT EXISTS(SELECT 1 FROM builderops_leases WHERE "
                                      "expires_at > clock_timestamp()) AS active").fetchone()
                if active["active"]:
                    raise BootstrapRefusal("conflict", "existing_writer_lease")
                _reconcile_surviving_tasks(conn, second)
                receipt = {"schema": "builderops-authority-convergence.v1", "bootstrap_id": identity,
                           "authority_epoch": epoch, "config_digest": digest(config),
                           "readback_digest": digest(second)}
                conn.execute("UPDATE builderops_recovery_state SET bootstrap_receipt=%s, "
                             "bootstrap_status='converged', bootstrap_reason='authority_converged', "
                             "executor_enabled=true, reconciliation_required=false, "
                             "reconciled_at=clock_timestamp() WHERE singleton", (Jsonb(receipt),))
                conn.commit()
                return {"status": "converged", "receipt": receipt}
            except (BootstrapRefusal, GithubReadError, OSError, subprocess.SubprocessError,
                    ValueError, KeyError, TypeError, AttributeError) as exc:
                status = exc.status if isinstance(exc, BootstrapRefusal) else "unknown"
                reason = exc.reason if isinstance(exc, BootstrapRefusal) else "authority_readback_unavailable"
                conn.rollback()
                conn.execute("UPDATE builderops_recovery_state SET bootstrap_status=%s, "
                             "bootstrap_reason=%s, executor_enabled=false, reconciliation_required=true "
                             "WHERE singleton", (status, reason))
                conn.commit()
                return {"status": status, "reason": reason}
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(current_schema() || "
                         "'builderops-bootstrap', 0))")


def main() -> int:
    from app.builderops.control_plane.selection import database_environment, production_store

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin-file", required=True, type=Path)
    parser.add_argument("--candidate-receipt", required=True, type=Path)
    parser.add_argument("--repository", action="append", required=True)
    args = parser.parse_args()
    store = production_store(database_environment(os.environ))
    result = bootstrap_from_authority(store, pin_file=args.pin_file,
                                      candidate_receipt=args.candidate_receipt, repositories=args.repository)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "converged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
