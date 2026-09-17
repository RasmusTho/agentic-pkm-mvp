"""Finite FCA-05 source adapters and FCA-09 admission; no outcome persistence here.

The deployment owner supplies the typed receipt chain and immutable acceptance
profile in its existing prerequisites artifact. The API transaction owner alone
records outcomes. Missing source material never selects a local fallback.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.builderops.control_plane.models import canonical_repository
from app.builderops.devui_receipts import (
    AUTHORITY, RUNTIME_PREREQUISITES_FILE, _receipt_dir,
    _load_latest_by_type, read_vm102_receipt_evidence,
)

CONTRACT = "builder_owner_outcome.v1"
BIFROST_AUTHORITY = "bifrost_git_documentation_source"
BIFROST_REPOSITORY = "rasmustho/bifrost"
BIFROST_TRACKING_REPOSITORY = "rasmustho/agentic-pkm-mvp"
BIFROST_READINESS_PREFIX = "bifrost-readiness:"
OUTCOME_PREFIX = "owner-outcome:"
REQUEST_FIELDS = frozenset({
    "fact_kind", "outcome", "repository", "subject_ref", "source_revision",
    "candidate_ref", "environment_ref", "readiness_receipt_ref", "acceptance_profile_ref",
    "criterion_refs", "owner_actor", "authorization_ref", "observed_at", "decided_at",
    "observation", "limitation_refs", "trial_receipt_ref", "expected_previous_receipt_id",
    "supersedes_receipt_id", "correction_reason", "retention_policy_ref",
})
BINDING_FIELDS = (
    "repository", "subject_ref", "source_revision", "candidate_ref", "environment_ref",
    "readiness_receipt_ref", "acceptance_profile_ref", "criterion_refs", "owner_actor",
    "authorization_ref", "limitation_refs", "retention_policy_ref",
)
PROFILE_FIELDS = frozenset({
    "id", "version", "repository", "subject_ref", "source_owner", "owner_actor",
    "authorization_ref", "criterion_refs", "limitation_refs", "retention_policy_ref",
})


class OwnerFactRefusal(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class OwnerOutcomeAdmission:
    request: dict[str, Any]
    request_sha256: str
    confirmed_at: str
    revalidate: Callable[[int], dict[str, Any]]


def _json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise OwnerFactRefusal("invalid_owner_outcome")
    if value is None or type(value) is int:
        return
    if type(value) is str and len(value.encode()) <= 2048:
        return
    if isinstance(value, list) and len(value) <= 128:
        for item in value:
            _json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 64 and all(type(k) is str for k in value):
        for item in value.values():
            _json_value(item, depth=depth + 1)
        return
    raise OwnerFactRefusal("invalid_owner_outcome")


def canonical_json(value: Any) -> str:
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def outcome_request_hash(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(CONTRACT.encode() + b"\0" + canonical_json(dict(request)).encode()).hexdigest()


def strict_json(raw: bytes | str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise OwnerFactRefusal("duplicate_owner_outcome_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerFactRefusal("invalid_owner_outcome") from exc


def _closed(value: Any, fields: set[str] | frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise OwnerFactRefusal("invalid_owner_outcome")
    _json_value(value)
    return value


def _text(value: Any) -> str:
    if type(value) is not str or not value.strip() or len(value.encode()) > 2048:
        raise OwnerFactRefusal("invalid_owner_outcome")
    return value


def _refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 128:
        raise OwnerFactRefusal("invalid_owner_outcome")
    seen: set[str] = set()
    for ref in value:
        _closed(ref, {"id", "sha256"})
        identity = _text(ref["id"])
        sha = _text(ref["sha256"])
        if identity in seen or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise OwnerFactRefusal("invalid_owner_outcome")
        seen.add(identity)
    return value


def _time(value: Any) -> datetime:
    try:
        text = _text(value)
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", text):
            raise ValueError
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except ValueError as exc:
        raise OwnerFactRefusal("invalid_owner_outcome_time") from exc


def _read_vm102_profiles() -> list[dict[str, Any]]:
    """Read only the existing host-owned runtime prerequisite source."""
    try:
        path = _receipt_dir(None) / RUNTIME_PREREQUISITES_FILE
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError
        profiles = strict_json(path.read_bytes())["owner_acceptance_profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
            raise ValueError
        seen = set()
        for profile in profiles:
            _closed(profile, PROFILE_FIELDS)
            repo = canonical_repository(profile["repository"])
            if repo != profile["repository"] or profile["source_owner"] != AUTHORITY:
                raise ValueError
            for key in ("id", "version", "subject_ref"):
                _text(profile[key])
            if not profile["subject_ref"].startswith("github:" + repo + "#"):
                raise ValueError
            identity = (repo, profile["subject_ref"])
            if identity in seen:
                raise ValueError
            seen.add(identity)
            actor = _closed(profile["owner_actor"], {"actor_type", "id"})
            if actor["actor_type"] != "human":
                raise ValueError
            _text(actor["id"])
            authority = _closed(profile["authorization_ref"], {"ref", "version", "authority_epoch"})
            _text(authority["ref"])
            _text(authority["version"])
            if type(authority["authority_epoch"]) is not int or authority["authority_epoch"] <= 0:
                raise ValueError
            if not _refs(profile["criterion_refs"]):
                raise ValueError
            _refs(profile["limitation_refs"])
            policy = _closed(profile["retention_policy_ref"], {"ref", "version"})
            _text(policy["ref"])
            _text(policy["version"])
        return copy.deepcopy(profiles)
    except Exception as exc:
        raise OwnerFactRefusal("owner_source_unavailable", 503) from exc


def _bifrost_sources() -> tuple[Any, Any]:
    """Existing host-owned transports only; absence never selects an ambient token."""
    from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig
    from app.dispatcher.verification_github import (
        GitHubProtectedRepositoryAuthority, HostCredentialManifestResolver,
    )

    token = HostCredentialManifestResolver.from_env().resolve_repository_read_token(BIFROST_REPOSITORY)
    return (GitHubProtectedRepositoryAuthority(token),
            BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0))


def _git_blob(authority: Any, path: str, revision: str) -> tuple[bytes, str]:
    item = authority._get(f"/repos/{BIFROST_REPOSITORY}/contents/{path}", ref=revision)
    if item.get("type") != "file" or item.get("encoding") != "base64":
        raise OwnerFactRefusal("owner_document_unavailable", 503)
    # GitHub Contents responses wrap base64 with newlines. Keep strict alphabet
    # checking after removing only that transport line wrapping.
    content = base64.b64decode(item["content"].replace("\n", "").replace("\r", ""), validate=True)
    if len(content) > 2_000_000:
        raise OwnerFactRefusal("owner_document_unavailable", 503)
    oid = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    if oid != item.get("sha"):
        raise OwnerFactRefusal("owner_document_conflict", 409)
    return content, oid


def _bifrost_profile(authority: Any) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    base = authority.protected_base_sha(BIFROST_REPOSITORY)
    raw, _ = _git_blob(authority, authority.manifest_path, base)
    document = strict_json(raw)
    from app.dispatcher.verification_merge import ProtectedDeliveryManifest
    # Reconcile independent served-byte reads, using the existing protected
    # manifest contract rather than accepting a caller's policy verdict.
    repeated, oid = _git_blob(authority, authority.manifest_path, base)
    if repeated != raw:
        raise OwnerFactRefusal("owner_policy_conflict", 409)
    policy = ProtectedDeliveryManifest.from_document(document, repository=BIFROST_REPOSITORY,
                                                     base_sha=base, blob_sha=oid)
    config = _closed(document.get("owner_documentation"), {
        "profile", "owner_login", "readiness_generation", "readiness_ttl_seconds", "access_policy",
    })
    profile = _closed(config["profile"], PROFILE_FIELDS)
    if (profile["repository"] != BIFROST_REPOSITORY
        or profile["source_owner"] != BIFROST_AUTHORITY
        or re.fullmatch(r"github:rasmustho/agentic-pkm-mvp#[1-9][0-9]*", profile["subject_ref"]) is None):
        raise OwnerFactRefusal("owner_profile_conflict", 409)
    for key in ("id", "version"):
        _text(profile[key])
    actor = _closed(profile["owner_actor"], {"actor_type", "id"})
    if actor["actor_type"] != "human":
        raise OwnerFactRefusal("owner_profile_conflict", 409)
    _text(actor["id"])
    auth = _closed(profile["authorization_ref"], {"ref", "version", "authority_epoch"})
    _text(auth["ref"])
    _text(auth["version"])
    if type(auth["authority_epoch"]) is not int or auth["authority_epoch"] < 1:
        raise OwnerFactRefusal("owner_profile_conflict", 409)
    for key in ("ref", "version"):
        _text(_closed(profile["retention_policy_ref"], {"ref", "version"})[key])
        _text(_closed(config["access_policy"], {"ref", "version"})[key])
    criteria = _refs(profile["criterion_refs"])
    _refs(profile["limitation_refs"])
    from app.builderops.control_plane.issue_delivery import canonical_hash
    verification = policy.verification_profile
    criterion_hashes = {ref["id"]: ref["sha256"] for ref in criteria}
    if (not criteria or verification != {"content_hash": canonical_hash(criterion_hashes),
                                       "criterion_hashes": criterion_hashes}
        or not policy.required_checks or len(set(policy.required_checks)) != len(policy.required_checks)):
        raise OwnerFactRefusal("owner_criteria_conflict", 409)
    paths = policy.documentation_paths
    if (not paths or len(paths) > 64 or len(set(paths)) != len(paths)
        or any(not _documentation_path(path) for path in paths)):
        raise OwnerFactRefusal("owner_profile_conflict", 409)
    ttl = config["readiness_ttl_seconds"]
    if type(ttl) is not int or not 0 < ttl <= 86400:
        raise OwnerFactRefusal("invalid_owner_readiness_window", 409)
    _text(config["readiness_generation"])
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", _text(config["owner_login"])) is None:
        raise OwnerFactRefusal("owner_profile_conflict", 409)
    return copy.deepcopy(profile), policy, config


def _documentation_path(path: Any) -> bool:
    return (type(path) is str and not any(c in path for c in "*?[]\\\0")
            and all(part not in {"", ".", ".."} for part in path.split("/"))
            and (path == "README.md" or path.startswith("docs/") and path.endswith(".md")))


def read_bifrost_profile() -> dict[str, Any]:
    try:
        authority, client = _bifrost_sources()
        try:
            return _bifrost_profile(authority)[0]
        finally:
            authority.close()
            client.close()
    except OwnerFactRefusal:
        raise
    except Exception as exc:
        raise OwnerFactRefusal("owner_source_unavailable", 503) from exc


def read_owner_profiles(repository: str | None = None) -> list[dict[str, Any]]:
    if repository is not None:
        return [read_bifrost_profile()] if canonical_repository(repository) == BIFROST_REPOSITORY else _read_vm102_profiles()
    profiles: list[dict[str, Any]] = []
    failures = []
    for reader in (_read_vm102_profiles, lambda: [read_bifrost_profile()]):
        try:
            profiles.extend(reader())
        except OwnerFactRefusal as exc:
            failures.append(exc)
    if not profiles:
        raise failures[0]
    return profiles


def read_owner_binding(
    repository: str, subject_ref: str, *, authority_epoch: int,
    allow_withdrawn_readiness: bool = False,
    store: Any = None, retained_readiness_ref: Any = None,
) -> dict[str, Any]:
    """Produce readiness only from the deployment owner's current typed chain."""
    try:
        repo = canonical_repository(repository)
        if repo == BIFROST_REPOSITORY:
            return _read_bifrost_binding(subject_ref, authority_epoch=authority_epoch,
                store=store, allow_withdrawn=allow_withdrawn_readiness,
                retained_ref=retained_readiness_ref)
        profile = next(p for p in read_owner_profiles(repo) if p["repository"] == repo and p["subject_ref"] == subject_ref)
        if profile["authorization_ref"]["authority_epoch"] != authority_epoch:
            raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        readiness_status = "current"
        try:
            evidence = read_vm102_receipt_evidence(require_typed_runtime=True)
        except Exception:
            if not allow_withdrawn_readiness:
                raise
            # The existing source may retain an exact, formerly valid chain
            # after its freshness window expires. Revalidate those same bytes
            # at their source observation time; never invent missing history.
            retained = _load_latest_by_type(_receipt_dir(None))
            observed = _time(retained["devsystem_vm102_health.v1"]["observed_at"])
            if observed >= datetime.now(timezone.utc):
                raise ValueError
            evidence = read_vm102_receipt_evidence(require_typed_runtime=True, now=observed)
            readiness_status = "withdrawn"
        health = evidence["receipts"]["devsystem_vm102_health.v1"]
        candidate = health["candidate_identity"]
        if set(candidate) != {"source_sha", "devui_image_digest", "devui_config_fingerprint"}:
            raise ValueError
        binding = {
            "repository": repo, "subject_ref": subject_ref, "source_revision": evidence["candidate_source_sha"],
            "candidate_ref": candidate,
            "environment_ref": {**evidence["target_vm"], "component_id": evidence["component_id"]},
            "readiness_receipt_ref": {"id": health["source_ref"], "sha256": health["source_ref"].rsplit(":", 1)[-1], "source_owner": AUTHORITY},
            "acceptance_profile_ref": {"id": profile["id"], "version": profile["version"], "sha256": digest(profile), "source_owner": AUTHORITY},
            **{key: profile[key] for key in ("criterion_refs", "owner_actor", "authorization_ref", "limitation_refs", "retention_policy_ref")},
        }
        return {**copy.deepcopy(binding), "binding_hash": digest(binding), "readiness_status": readiness_status, "observed_at": datetime.now(timezone.utc).isoformat(), "source_refs": evidence["receipt_refs"]}
    except OwnerFactRefusal:
        raise
    except Exception as exc:
        raise OwnerFactRefusal("owner_source_unavailable", 503) from exc


def _read_bifrost_binding(subject: str, *, authority_epoch: int, store: Any,
                          allow_withdrawn: bool, retained_ref: Any) -> dict[str, Any]:
    """Produce technical evidence through the existing service/store owner only."""
    if store is None:
        raise OwnerFactRefusal("owner_source_unavailable", 503)
    authority, client = _bifrost_sources()
    try:
        profile, policy, config = _bifrost_profile(authority)
        if profile["subject_ref"] != subject or profile["authorization_ref"]["authority_epoch"] != authority_epoch:
            raise OwnerFactRefusal("owner_profile_conflict", 409)
        try:
            evidence = _bifrost_evidence(authority, client, profile, policy, config)
        except OwnerFactRefusal as exc:
            # Only a retained source-owned receipt can describe an attempted,
            # now-withdrawn candidate. An outage is not proof of withdrawal.
            if not allow_withdrawn or not retained_ref or exc.code != "owner_readiness_withdrawn":
                raise
            return _retained_bifrost_binding(store, retained_ref, profile, config)
        identity = BIFROST_READINESS_PREFIX + digest(evidence)
        if allow_withdrawn and retained_ref and retained_ref.get("id") != identity:
            retained = _retained_bifrost_binding(store, retained_ref, profile, config)
            if _time(retained["expires_at"]) <= datetime.now(timezone.utc):
                return retained
        try:
            receipt = store.get_owner_readiness(BIFROST_REPOSITORY, identity, subject)
        except KeyError:
            from app.builderops.control_plane.models import AuthorityEnvelope
            from app.builderops.control_plane.store import _owner_readiness_capability

            now = datetime.now(timezone.utc)
            body = {"source_owner": BIFROST_AUTHORITY, "version": "1", "evidence": evidence,
                    "observed_at": now.isoformat(),
                    "expires_at": datetime.fromtimestamp(evidence["observation_window"]["end"], timezone.utc).isoformat()}
            receipt = {"id": identity, "object_type": "BuilderOpsReceipt", "authority_class": "receipt",
                "lifecycle_state": "active", "promotion_status": "not_promotable",
                "created_at": body["observed_at"], "updated_at": body["observed_at"],
                "created_by": {"actor_type": "service", "id": "builderops-control-plane"},
                "source_refs": [{"ref_type": "source", "ref": subject, "authority_surface": "github"}],
                "target_refs": [{"ref_type": "subject", "ref": subject, "authority_surface": "github"}],
                "summary": "Exact documentation source readiness", "event_type": "readiness_observed",
                "actor": {"actor_type": "service", "id": BIFROST_AUTHORITY},
                "occurred_at": body["observed_at"], "action": "observe_documentation_readiness",
                "outcome": "succeeded", "idempotency_key": identity, "receipt_body": body}
            receipt["hash"] = digest(receipt)
            envelope = AuthorityEnvelope(repository=BIFROST_REPOSITORY, scope="owner-readiness",
                stack="builderops-control-plane", actor=BIFROST_AUTHORITY, source_refs=(subject,))
            # Same deterministic key serializes first observation. A concurrent
            # source read may win; always return the durable original below.
            try:
                store.commit_record(envelope=envelope, record_id=identity,
                    record_type="BuilderOpsReceipt", state="active", payload=receipt,
                    idempotency_key=identity, owner_readiness_admission=_owner_readiness_capability())
            except Exception:
                store.get_owner_readiness(BIFROST_REPOSITORY, identity, subject)
            receipt = store.get_owner_readiness(BIFROST_REPOSITORY, identity, subject)
        if receipt["receipt_body"]["evidence"] != evidence:
            raise OwnerFactRefusal("owner_readiness_conflict", 409)
        result = _bifrost_receipt_binding(receipt, profile, config)
        if result["readiness_status"] != "current" and not allow_withdrawn:
            raise OwnerFactRefusal("owner_readiness_withdrawn", 409)
        return result
    finally:
        authority.close()
        client.close()


def _bifrost_evidence(authority: Any, client: Any, profile: dict[str, Any],
                      policy: Any, config: dict[str, Any]) -> dict[str, Any]:
    from app.builderops.cockpit_github_plane import read_issue_delivery_github
    from app.builderops.issue_delivery_readback import read_issue_delivery_projection
    from app.builderops.issue_delivery_effect_executor import complete_documentation_diff
    from app.builderops.issue_delivery_operation import observe_issue_delivery_operation
    from app.builderops.control_plane.issue_delivery import delivery_source_pair

    matches = []
    for task in client.list_tasks(repository=BIFROST_REPOSITORY):
        delivery = task.get("payload", {}).get("issue_delivery")
        if not isinstance(delivery, dict):
            continue
        readback = client.issue_delivery_readback(repository=BIFROST_REPOSITORY,
                                                  approval_id=delivery["approval_id"])
        approval = readback.get("approval", {})
        issue = approval.get("issue", {})
        if f"github:{issue.get('repository')}#{issue.get('number')}" != profile["subject_ref"]:
            continue
        if (approval.get("contract_version") != "fca-issue-delivery.v2"
            or approval.get("repository") != BIFROST_REPOSITORY
            or issue.get("repository") != BIFROST_TRACKING_REPOSITORY):
            raise OwnerFactRefusal("owner_delivery_conflict", 409)
        context, destination = approval["context"], approval["destination"]
        observed = observe_issue_delivery_operation(approval, client=client,
            plan=context["dispatch_plan"], expected_plan_hash=context["expected_plan_hash"],
            repo_root=Path(destination.get("resolved_worktree") or destination["worktree"]))
        # Reapproval retains historical native tasks. Only independently
        # authenticated terminal delivery may qualify; malformed/unavailable
        # history still fails closed, and multiple qualifying deliveries do too.
        if observed.state != "terminal":
            continue
        kinds = set()
        for ref in observed.host_effect_refs or []:
            effect = client.get_outbox_status(repository=BIFROST_REPOSITORY, operation_key=ref["operation_key"])
            payload = effect.get("payload", {})
            kind = payload.get("effect_kind")
            if (effect.get("status") != "succeeded"
                or effect.get("operation_key") != ref["operation_key"]
                or payload.get("request_sha256") != ref["request_sha256"]
                or payload.get("effect_slot_sha256") != ref["effect_slot_sha256"]
                or payload.get("approval_id") != approval["approval_id"]
                or payload.get("approved_operation_key") != approval["operation_key"]
                or payload.get("repository") != BIFROST_REPOSITORY
                or payload.get("approval_manifest_hash") != approval["approval_manifest_hash"]
                or payload.get("delivery_sources") != delivery_source_pair(approval)
                or payload.get("effect_repository") != (BIFROST_REPOSITORY if kind in {"publication", "merge"} else BIFROST_TRACKING_REPOSITORY)
                or not isinstance(payload.get("target"), dict) or payload["target"].get("kind") != kind
                or kind not in {"claim", "publication", "merge", "closure", "parent_evidence"}
                or kind in kinds):
                raise OwnerFactRefusal("owner_delivery_conflict", 409)
            kinds.add(kind)
        if not {"publication", "merge", "closure"}.issubset(kinds):
            continue  # Authenticated terminal history with incomplete effects is not delivery.
        projection = read_issue_delivery_projection(client=client, task=task,
            github_reader=read_issue_delivery_github, owner_binding_reader=lambda *a, **kw: None)
        if projection["state"] == "delivered" and projection["subject_ref"] == profile["subject_ref"]:
            matches.append((task, approval, projection))
    if len(matches) != 1:
        raise OwnerFactRefusal("owner_delivery_conflict", 409)
    _task, approval, projection = matches[0]
    protected = approval["target_policies"][BIFROST_REPOSITORY]
    if (protected["content_sha256"] != policy.content_sha256
        or protected["blob_sha"] != policy.blob_sha
        or protected["documentation_paths"] != list(policy.documentation_paths)
        or protected["verification_profile"] != policy.verification_profile
        or protected["required_checks"] != list(policy.required_checks)):
        raise OwnerFactRefusal("owner_readiness_withdrawn", 409)
    base = approval["destination"]["base_sha"]
    head = projection["merge_commit_sha"]
    if re.fullmatch(r"[0-9a-f]{40}", head) is None or base != protected["base_sha"]:
        raise OwnerFactRefusal("owner_delivery_conflict", 409)
    # A remote commit read and protected-branch ancestry are independent of the
    # worker checkout. Local Git supplies complete trees, never a selected diff.
    commit = authority._get(f"/repos/{BIFROST_REPOSITORY}/git/commits/{head}")
    comparison = authority._get(f"/repos/{BIFROST_REPOSITORY}/compare/{head}...{policy.base_sha}")
    ancestry = authority._get(f"/repos/{BIFROST_REPOSITORY}/compare/{base}...{head}")
    if (commit.get("sha") != head or comparison.get("status") not in {"ahead", "identical"}
        or comparison.get("merge_base_commit", {}).get("sha") != head
        or ancestry.get("status") != "ahead" or ancestry.get("merge_base_commit", {}).get("sha") != base):
        raise OwnerFactRefusal("owner_readiness_withdrawn", 409)
    root = Path(approval["destination"].get("resolved_worktree") or approval["destination"]["worktree"])
    try:
        delta = complete_documentation_diff(root, base, head, policy.documentation_paths)
    except Exception as exc:
        raise OwnerFactRefusal("owner_complete_diff_conflict", 409) from exc
    tree = _reconcile_complete_tree(authority, root, head)
    _reconcile_complete_tree(authority, root, base)
    checked_tree = subprocess.run(["git", "-C", str(root), "rev-parse", f"{projection['head_sha']}^{{tree}}"],
        check=True, capture_output=True, text=True).stdout.strip()
    if checked_tree != tree["sha"]:
        raise OwnerFactRefusal("owner_candidate_checks_conflict", 409)
    documents = []
    for path in policy.documentation_paths:
        content, oid = _git_blob(authority, path, head)
        # Check the independently served bytes against the immutable tree, not
        # only the Content API's self-reported blob identity.
        rows = [row for row in tree.get("tree", []) if row.get("path") == path]
        if len(rows) != 1 or rows[0].get("sha") != oid or rows[0].get("mode") != "100644" or rows[0].get("type") != "blob":
            raise OwnerFactRefusal("owner_document_conflict", 409)
        content.decode("utf-8", errors="strict")
        if not content.strip():
            raise OwnerFactRefusal("owner_document_conflict", 409)
        documents.append({"path": path, "blob_oid": oid, "sha256": hashlib.sha256(content).hexdigest()})
    access = authority._get(f"/repos/{BIFROST_REPOSITORY}/collaborators/{config['owner_login']}/permission")
    if (access.get("user", {}).get("login", "").lower() != config["owner_login"].lower()
        or access.get("permission") not in {"read", "triage", "write", "maintain", "admin"}):
        raise OwnerFactRefusal("owner_readiness_withdrawn", 409)
    checks = authority.required_gates(BIFROST_REPOSITORY, projection["pr_number"],
        projection["head_sha"], verification_checks=tuple(policy.required_checks))
    if not checks or not all(value is True for value in checks.values()):
        raise OwnerFactRefusal("owner_readiness_withdrawn", 409)
    # A refreshed observation is a different immutable receipt, never a renewal
    # of prior consent. UTC windows bound the source-owned lifetime without a
    # second mutable index or a scheduler.
    ttl = config["readiness_ttl_seconds"]
    start = int(datetime.now(timezone.utc).timestamp()) // ttl * ttl
    return {"repository": BIFROST_REPOSITORY, "subject_ref": profile["subject_ref"],
        "observation_window": {"start": start, "end": start + ttl},
        "source_owner": BIFROST_AUTHORITY, "profile": profile, "profile_sha256": digest(profile),
        "policy_sha256": policy.content_sha256, "policy_blob_oid": policy.blob_sha,
        "readiness_generation": config["readiness_generation"], "access_policy": config["access_policy"],
        "owner_login": config["owner_login"], "base_sha": base, "source_sha": head,
        "diff_sha256": digest(delta), "documents": documents,
        "operation_key": projection["operation_key"], "approval_id": projection["approval_id"],
        "approval_manifest_hash": projection["approval_manifest_hash"],
        "pr_number": projection["pr_number"], "head_sha": projection["head_sha"],
        "technical_results": [{"criterion_ref": ref, "status": "passed"} for ref in profile["criterion_refs"]]}


def _reconcile_complete_tree(authority: Any, root: Path, revision: str) -> dict[str, Any]:
    """Require full remote tree identity and inventory to agree with immutable Git objects."""
    tree = authority._get(f"/repos/{BIFROST_REPOSITORY}/git/trees/{revision}", recursive=1)
    tree_oid = subprocess.run(["git", "-C", str(root), "rev-parse", f"{revision}^{{tree}}"],
        check=True, capture_output=True, text=True).stdout.strip()
    if tree.get("truncated") is not False or tree.get("sha") != tree_oid:
        raise OwnerFactRefusal("owner_complete_tree_conflict", 409)
    raw = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "-t", "-z", revision],
        check=True, capture_output=True).stdout.decode("utf-8", errors="strict")
    local = []
    for entry in raw.split("\0"):
        if entry:
            metadata, path = entry.split("\t", 1)
            mode, kind, oid = metadata.split()
            local.append({"path": path, "mode": mode, "type": kind, "sha": oid})
    remote = [{key: row.get(key) for key in ("path", "mode", "type", "sha")} for row in tree.get("tree", [])]
    if sorted(remote, key=lambda row: str(row["path"])) != sorted(local, key=lambda row: row["path"]):
        raise OwnerFactRefusal("owner_complete_tree_conflict", 409)
    return dict(tree)


def _bifrost_receipt_binding(receipt: Any, profile: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    body = receipt["receipt_body"]
    evidence = body["evidence"]
    if (receipt.get("hash") != digest({k: v for k, v in receipt.items() if k != "hash"})
        or receipt.get("id") != BIFROST_READINESS_PREFIX + digest(evidence)
        or body.get("source_owner") != BIFROST_AUTHORITY or body.get("version") != "1"
        or evidence["profile"] != profile or evidence["access_policy"] != config["access_policy"]
        or evidence["readiness_generation"] != config["readiness_generation"]):
        raise OwnerFactRefusal("owner_readiness_conflict", 409)
    observed, expires = _time(body["observed_at"]), _time(body["expires_at"])
    now = datetime.now(timezone.utc)
    window = evidence["observation_window"]
    if (not observed <= now or not timedelta(0) < expires - observed <= timedelta(seconds=config["readiness_ttl_seconds"])
        or type(window["start"]) is not int or type(window["end"]) is not int
        or window["end"] - window["start"] != config["readiness_ttl_seconds"]
        or not window["start"] <= observed.timestamp() < window["end"]
        or expires.timestamp() != window["end"]):
        raise OwnerFactRefusal("invalid_owner_readiness_window", 409)
    candidate = {"kind": "git_documentation", "source_sha": evidence["source_sha"],
        "base_sha": evidence["base_sha"], "diff_sha256": evidence["diff_sha256"],
        "documents": evidence["documents"], "image_digests": "not_applicable",
        "runtime_configuration": "not_applicable",
        "delivery_ref": {key: evidence[key] for key in ("operation_key", "approval_id", "approval_manifest_hash", "pr_number", "head_sha")}}
    binding = {"repository": BIFROST_REPOSITORY, "subject_ref": profile["subject_ref"],
        "source_revision": evidence["source_sha"], "candidate_ref": candidate,
        "environment_ref": {"kind": "github_document_view", "repository": BIFROST_REPOSITORY,
            "commit": evidence["source_sha"], "access_policy": config["access_policy"]},
        "readiness_receipt_ref": {"id": receipt["id"], "sha256": receipt["hash"], "source_owner": BIFROST_AUTHORITY},
        "acceptance_profile_ref": {"id": profile["id"], "version": profile["version"], "sha256": digest(profile), "source_owner": BIFROST_AUTHORITY},
        **{key: profile[key] for key in ("criterion_refs", "owner_actor", "authorization_ref", "limitation_refs", "retention_policy_ref")}}
    return {**copy.deepcopy(binding), "binding_hash": digest(binding),
        "readiness_status": "current" if now < expires else "withdrawn",
        "observed_at": body["observed_at"], "expires_at": body["expires_at"],
        "source_refs": [receipt["id"]]}


def _retained_bifrost_binding(store: Any, ref: Any, profile: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    _closed(ref, {"id", "sha256", "source_owner"})
    receipt = store.get_owner_readiness(BIFROST_REPOSITORY, ref["id"], profile["subject_ref"])
    binding = _bifrost_receipt_binding(receipt, profile, config)
    if ref != binding["readiness_receipt_ref"]:
        raise OwnerFactRefusal("owner_readiness_conflict", 409)
    return {**binding, "readiness_status": "withdrawn"}


def validate_outcome_request(request: Any, *, confirmed_at: str) -> dict[str, Any]:
    value = _closed(request, REQUEST_FIELDS)
    if canonical_repository(value["repository"]) != value["repository"]:
        raise OwnerFactRefusal("invalid_owner_outcome")
    _text(value["subject_ref"])
    _text(value["source_revision"])
    bifrost = isinstance(value["candidate_ref"], dict) and value["candidate_ref"].get("kind") == "git_documentation"
    if bifrost:
        _validate_documentation_candidate(value)
    else:
        for key, fields in (
            ("candidate_ref", {"source_sha", "devui_image_digest", "devui_config_fingerprint"}),
            ("environment_ref", {"vmid", "name", "component_id"}),
        ):
            for field, item in _closed(value[key], fields).items():
                if field == "vmid":
                    if type(item) is not int or item <= 0:
                        raise OwnerFactRefusal("invalid_owner_outcome")
                else:
                    _text(item)
    for key, fields in (
        ("readiness_receipt_ref", {"id", "sha256", "source_owner"}),
        ("acceptance_profile_ref", {"id", "version", "sha256", "source_owner"}),
        ("owner_actor", {"actor_type", "id"}),
        ("authorization_ref", {"ref", "version", "authority_epoch"}),
        ("retention_policy_ref", {"ref", "version"}),
    ):
        for field, item in _closed(value[key], fields).items():
            if field in {"vmid", "authority_epoch"}:
                if type(item) is not int or item <= 0:
                    raise OwnerFactRefusal("invalid_owner_outcome")
            else:
                _text(item)
    if value["trial_receipt_ref"] is not None:
        _text(value["trial_receipt_ref"])
    outcomes = {"owner_trial": {"tried", "unable_to_try"}, "owner_acceptance": {"accepted", "rejected"}}
    kind = value["fact_kind"]
    if type(kind) is not str or kind not in outcomes or type(value["outcome"]) is not str or value["outcome"] not in outcomes[kind]:
        raise OwnerFactRefusal("invalid_owner_outcome")
    trial = kind == "owner_trial"
    if value["decided_at" if trial else "observed_at"] is not None:
        raise OwnerFactRefusal("invalid_owner_outcome_time")
    if _time(value["observed_at" if trial else "decided_at"]) > _time(confirmed_at):
        raise OwnerFactRefusal("invalid_owner_outcome_time")
    criteria = _refs(value["criterion_refs"])
    if not criteria:
        raise OwnerFactRefusal("invalid_owner_outcome")
    limits = _refs(value["limitation_refs"])
    if trial:
        observation = value["observation"]
        if not isinstance(observation, list) or len(observation) > 128 or value["trial_receipt_ref"] is not None:
            raise OwnerFactRefusal("invalid_owner_outcome")
        seen = set()
        for item in observation:
            _closed(item, {"criterion_ref", "status"})
            ref = item["criterion_ref"]
            if ref not in criteria or type(item["status"]) is not str or item["status"] not in {"observed", "not_observed"} or ref["id"] in seen:
                raise OwnerFactRefusal("invalid_owner_outcome")
            seen.add(ref["id"])
        if value["outcome"] == "unable_to_try" and (not limits or any(o["status"] == "observed" for o in observation)):
            raise OwnerFactRefusal("invalid_owner_outcome")
    elif value["observation"] is not None:
        raise OwnerFactRefusal("invalid_owner_outcome")
    previous = value["expected_previous_receipt_id"]
    if previous is None:
        if value["supersedes_receipt_id"] is not None or value["correction_reason"] is not None:
            raise OwnerFactRefusal("invalid_owner_correction")
    elif _text(previous) != value["supersedes_receipt_id"] or value["correction_reason"] != "owner_correction":
        raise OwnerFactRefusal("invalid_owner_correction")
    return copy.deepcopy(value)


def _validate_documentation_candidate(value: dict[str, Any]) -> None:
    candidate = _closed(value["candidate_ref"], {"kind", "source_sha", "base_sha", "diff_sha256",
        "documents", "image_digests", "runtime_configuration", "delivery_ref"})
    environment = _closed(value["environment_ref"], {"kind", "repository", "commit", "access_policy"})
    if (value["repository"] != BIFROST_REPOSITORY
        or re.fullmatch(r"github:rasmustho/agentic-pkm-mvp#[1-9][0-9]*", value["subject_ref"]) is None
        or candidate["image_digests"] != "not_applicable" or candidate["runtime_configuration"] != "not_applicable"
        or candidate["source_sha"] != value["source_revision"]
        or environment["kind"] != "github_document_view" or environment["repository"] != BIFROST_REPOSITORY
        or environment["commit"] != candidate["source_sha"]
        or not isinstance(value["acceptance_profile_ref"], dict) or value["acceptance_profile_ref"].get("source_owner") != BIFROST_AUTHORITY
        or not isinstance(value["readiness_receipt_ref"], dict) or value["readiness_receipt_ref"].get("source_owner") != BIFROST_AUTHORITY):
        raise OwnerFactRefusal("invalid_owner_outcome")
    delivery = _closed(candidate["delivery_ref"], {"operation_key", "approval_id", "approval_manifest_hash", "pr_number", "head_sha"})
    if (type(delivery["pr_number"]) is not int or delivery["pr_number"] < 1
        or re.fullmatch(r"[0-9a-f]{40}", _text(delivery["head_sha"])) is None
        or re.fullmatch(r"[0-9a-f]{64}", _text(delivery["approval_manifest_hash"])) is None):
        raise OwnerFactRefusal("invalid_owner_outcome")
    _text(delivery["operation_key"])
    _text(delivery["approval_id"])
    for key in ("source_sha", "base_sha"):
        if re.fullmatch(r"[0-9a-f]{40}", _text(candidate[key])) is None:
            raise OwnerFactRefusal("invalid_owner_outcome")
    if re.fullmatch(r"[0-9a-f]{64}", _text(candidate["diff_sha256"])) is None:
        raise OwnerFactRefusal("invalid_owner_outcome")
    for item in _closed(environment["access_policy"], {"ref", "version"}).values():
        _text(item)
    documents = candidate["documents"]
    if not isinstance(documents, list) or not 1 <= len(documents) <= 64:
        raise OwnerFactRefusal("invalid_owner_outcome")
    paths = set()
    for doc in documents:
        _closed(doc, {"path", "blob_oid", "sha256"})
        if (not _documentation_path(doc["path"]) or doc["path"] in paths
            or re.fullmatch(r"[0-9a-f]{40}", _text(doc["blob_oid"])) is None
            or re.fullmatch(r"[0-9a-f]{64}", _text(doc["sha256"])) is None):
            raise OwnerFactRefusal("invalid_owner_outcome")
        paths.add(doc["path"])


def validate_current_binding(request: dict[str, Any], binding: dict[str, Any]) -> None:
    if (request["repository"] == BIFROST_REPOSITORY and request["outcome"] == "unable_to_try"
        and binding["readiness_status"] != "withdrawn"):
        raise OwnerFactRefusal("owner_withdrawn_readiness_required", 409)
    for key in BINDING_FIELDS:
        if key == "criterion_refs":
            if any(ref not in binding[key] for ref in request[key]):
                raise OwnerFactRefusal("owner_binding_changed", 409)
            if request["outcome"] == "accepted" and {digest(ref) for ref in request[key]} != {digest(ref) for ref in binding[key]}:
                raise OwnerFactRefusal("incomplete_acceptance_scope", 409)
        elif request[key] != binding[key]:
            raise OwnerFactRefusal("owner_binding_changed", 409)


def outcome_record_id(repository: str, key: str) -> str:
    _text(key)
    return OUTCOME_PREFIX + digest({"repository": repository, "operation": CONTRACT, "key": key})


def receipt_hash(receipt: Mapping[str, Any]) -> str:
    return digest({key: value for key, value in receipt.items() if key != "hash"})
