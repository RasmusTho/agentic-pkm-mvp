"""FCA-05 proofs through the authenticated service and real PostgreSQL kernel."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.service import create_app
from app.builderops.owner_fact_producers import outcome_request_hash, read_owner_binding
from tests.builderops.control_plane.conftest import control_plane_store  # noqa: F401
from tests.ops.test_devui_vm102_runtime_receipts import _bundle, _chain, _component_evidence

pytestmark = pytest.mark.pg
REPO = "example/fixture"
SUBJECT = "github:example/fixture#5404"

# Captured from the unmodified v1 codec at 45c5d1e948794470293a22d7a0872db83ca85e05.
V1_REQUEST_BYTES = (
    '{"acceptance_profile_ref":{"id":"profile:fixture","sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","source_owner":"builderops_vm102_receipt_source","version":"1"},'
    '"authorization_ref":{"authority_epoch":1,"ref":"policy:owner","version":"1"},'
    '"candidate_ref":{"devui_config_fingerprint":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","devui_image_digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},'
    '"correction_reason":null,"criterion_refs":[{"id":"AC1","sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}],"decided_at":null,'
    '"environment_ref":{"component_id":"devui_projection","name":"fixture","vmid":102},"expected_previous_receipt_id":null,"fact_kind":"owner_trial","limitation_refs":[],'
    '"observation":[{"criterion_ref":{"id":"AC1","sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"},"status":"observed"}],"observed_at":"2026-09-17T00:00:00Z","outcome":"tried",'
    '"owner_actor":{"actor_type":"human","id":"human:owner"},"readiness_receipt_ref":{"id":"receipt:fixture","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","source_owner":"builderops_vm102_receipt_source"},'
    '"repository":"example/fixture","retention_policy_ref":{"ref":"BuilderOpsReceipt","version":"1"},"source_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","subject_ref":"github:example/fixture#5404","supersedes_receipt_id":null,"trial_receipt_ref":null}'
)


def test_bifrost_unconfigured_source_is_unavailable(monkeypatch):
    monkeypatch.delenv("BUILDEROPS_EXECUTOR_CREDENTIAL_MANIFEST_FILE", raising=False)
    from app.builderops.owner_fact_producers import BIFROST_AUTHORITY, read_bifrost_profile

    assert BIFROST_AUTHORITY == "bifrost_git_documentation_source"
    # An unconfigured source cannot borrow the VM102 profile or manufacture readiness.
    from app.builderops.owner_fact_producers import OwnerFactRefusal
    with pytest.raises(OwnerFactRefusal):
        read_bifrost_profile()


class OwnerWriter:
    def __init__(self, root, store, monkeypatch):
        self.root, self.store = root, store
        self.profile = {
            "id": "profile:devui-trial", "version": "1", "repository": REPO,
            "subject_ref": SUBJECT, "source_owner": "builderops_vm102_receipt_source",
            "owner_actor": {"actor_type": "human", "id": "human:owner"},
            "authorization_ref": {"ref": "policy:owner", "version": "1", "authority_epoch": 1},
            "criterion_refs": [{"id": "AC1", "sha256": "a" * 64}, {"id": "AC2", "sha256": "b" * 64}],
            "limitation_refs": [],
            "retention_policy_ref": {"ref": "BuilderOpsReceipt", "version": "1"},
        }
        self.bundle = _bundle()
        self.write_sources()
        monkeypatch.setenv("DEVUI_VM102_RECEIPT_DIR", str(root))
        self.manifest = root / "credentials.json"
        self.credentials = [
            self.entry("owner", "human:owner", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]),
            self.entry("agent", "agent:builder", "agent", ["records:write", "receipts:read"]),
            self.entry("other", "human:other", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]),
        ]
        self.write_credentials()
        self.registry = CredentialRegistry(self.manifest)
        self.client = TestClient(create_app(store=store, credentials=self.registry))

    def entry(self, key, principal, kind, scopes):
        return {"id": key, "principal": principal, "principal_kind": kind,
                "secret_ref": "host-secret:" + key,
                "verifier_sha256": hashlib.sha256((key + "-test-only-key").encode()).hexdigest(),
                "token_length": len(key + "-test-only-key"), "scopes": scopes,
                "repositories": [REPO], "rotation_generation": 1}

    def write_credentials(self):
        self.manifest.write_text(json.dumps({"credentials": self.credentials}))

    def write_sources(self):
        self.root.mkdir(exist_ok=True)
        self.chain = _chain(self.bundle)
        self.bundle["prerequisites"]["owner_acceptance_profiles"] = [self.profile]
        for index, receipt in enumerate(self.chain):
            (self.root / f"{index}-runtime.json").write_text(json.dumps(receipt))
        (self.root / "devui-runtime-prerequisites.json").write_text(json.dumps(self.bundle["prerequisites"]))

    def binding(self):
        return read_owner_binding(REPO, SUBJECT, authority_epoch=1)

    def request(self, kind="owner_trial", outcome="tried", **changes):
        binding = self.binding()
        request = {key: copy.deepcopy(binding[key]) for key in (
            "repository", "subject_ref", "source_revision", "candidate_ref", "environment_ref",
            "readiness_receipt_ref", "acceptance_profile_ref", "criterion_refs", "owner_actor",
            "authorization_ref", "limitation_refs", "retention_policy_ref",
        )}
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        request.update(fact_kind=kind, outcome=outcome,
                       observed_at=stamp if kind == "owner_trial" else None,
                       decided_at=stamp if kind == "owner_acceptance" else None,
                       observation=[{"criterion_ref": ref, "status": "observed"} for ref in request["criterion_refs"]] if kind == "owner_trial" else None,
                       trial_receipt_ref=None, expected_previous_receipt_id=None,
                       supersedes_receipt_id=None, correction_reason=None)
        request.update(changes)
        return request

    def submit(self, request, key="first", principal="owner", **changes):
        payload = {"contract": "builder_owner_outcome.v1", "request": request,
                   "request_sha256": outcome_request_hash(request), "confirm": "confirm"}
        payload.update(changes)
        return self.client.post("/v1/records", json={"record_type": "BuilderOpsReceipt",
                    "owner_outcome": payload, "idempotency_key": key},
                    headers={"Authorization": "Bearer " + principal + "-test-only-key", "X-BuilderOps-Authority-Epoch": "1"})

    def read(self, key=None):
        params = {"repository": REPO, "subject_ref": SUBJECT}
        if key is not None:
            params["idempotency_key"] = key
        return self.client.get("/v1/receipts/owner-outcomes/current", params=params,
            headers={"Authorization": "Bearer owner-test-only-key"})

    def count(self, table):
        assert table in {"builderops_records", "builderops_receipts", "builderops_idempotency", "builderops_outbox"}
        with self.store._connect() as conn:
            return conn.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"]


@pytest.fixture
def owner_writer(tmp_path, control_plane_store, monkeypatch):  # noqa: F811
    return OwnerWriter(tmp_path, control_plane_store, monkeypatch)


class BifrostWriter(OwnerWriter):
    """Real v2 delivery, authenticated clients/store, substituted external IO."""

    def __init__(self, build, monkeypatch, *, merge_change=None):
        from app.builderops import cockpit_github_plane, owner_fact_producers
        from app.builderops.epic_dispatch import dispatch_issue_sessions
        from app.builderops.issue_delivery_readback import admit_issue_delivery_task
        from tests.builderops.test_issue_delivery_readback import BODY, _issue
        from tests.builderops.test_issue_delivery_operation import _production_adapter
        from tests.builderops.test_issue_delivery_effect_executor import _bifrost_candidate_request

        monkeypatch.setenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", "10000")
        h = self.harness = build(bifrost=True, documentation_owner=True, issue_body=BODY)
        self.store, self.registry, self.manifest = h.store, h.registry, h.registry.manifest_path
        self.repository = h.approval["repository"]
        self.profile = h.source_state["documents"][self.repository]["owner_documentation"]["profile"]
        self.subject = self.profile["subject_ref"]
        number = h.approval["issue"]["number"]
        source = {**_issue(), "number": number, "node_id": h.approval["issue"]["node_id"],
            "title": h.approval["issue"]["title"], "html_url": h.approval["issue"]["url"],
            "url": f"https://api.github.com/repos/rasmustho/agentic-pkm-mvp/issues/{number}"}
        h.source_state["issue"] = source
        self.task = admit_issue_delivery_task(client=h.host, repository=self.repository,
            approval_id=h.approval["approval_id"], issue_reader=lambda *args: copy.deepcopy(source),
            observed_at=datetime.now(timezone.utc).isoformat())
        self.title = "Document the exact consumer"
        self.pr_body = f"Governing-Issue: rasmustho/agentic-pkm-mvp#{number}"

        def content():
            request = _bifrost_candidate_request(h, "publication")
            publication = request.target.model_dump(mode="json")
            publication.update(title_sha256=hashlib.sha256(self.title.encode()).hexdigest(),
                               body_sha256=hashlib.sha256(self.pr_body.encode()).hexdigest())
            merge = {k: v for k, v in publication.items() if k not in {"title_sha256", "body_sha256", "expected_remote_ref_state"}}
            merge.update(kind="merge", pr_number=6000)
            merge_sha = publication["head_sha"]
            if merge_change is not None:
                merge_sha = self.corrupt_merge(merge_sha, merge_change)
            h.source_state["merge_sha"] = merge_sha
            h.worker_transport.effect_targets = {"publication": publication, "merge": merge,
                "closure": {"kind": "closure", "issue_number": number, "pr_number": 6000,
                            "merge_commit_sha": merge_sha, "expected_issue_state": "open"}}

        h.worker_transport.effect_kind = "delivery"
        h.worker_transport.pre_entry_check = content
        h.transport.readbacks = ["applied"] * 4
        result = dispatch_issue_sessions(h.approval["context"]["dispatch_plan"], _production_adapter(h),
                                        expected_plan_hash=h.approval["context"]["expected_plan_hash"])
        assert result["stopped_reason"] == "worker-handoff", result
        assert h.transport.apply_calls == 4
        self.head, self.merge = h.source_state["head"], h.source_state["merge_sha"]
        source.update(state="closed", state_reason="completed", closed_at="2026-09-17T18:00:00Z", closed_by={"login": "fixture-owner"})
        # Read exact served bytes, including the final newline.
        content_bytes = subprocess.run(["git", "-C", str(h.worktree), "show", f"{self.merge}:docs/guide.md"], check=True, capture_output=True).stdout
        oid = self.git("rev-parse", f"{self.merge}:docs/guide.md")
        self.responses = h.source_state["responses"] = {
            f"git/commits/{self.merge}": {"sha": self.merge},
            f"compare/{self.merge}...{self.merge}": {"status": "identical", "merge_base_commit": {"sha": self.merge}},
            f"compare/{h.approval['destination']['base_sha']}...{self.merge}": {"status": "ahead", "merge_base_commit": {"sha": h.approval["destination"]["base_sha"]}},
            "contents/docs/guide.md": {"type": "file", "encoding": "base64", "sha": oid, "content": base64.encodebytes(content_bytes).decode()},
            "collaborators/fixture-owner/permission": {"permission": "read", "user": {"login": "fixture-owner"}},
        }
        for revision in (self.merge, h.approval["destination"]["base_sha"]):
            rows = []
            for entry in self.git("ls-tree", "-r", "-t", "-z", revision).split("\0"):
                if entry:
                    metadata, path = entry.split("\t", 1)
                    mode, kind, blob = metadata.split()
                    rows.append({"path": path, "mode": mode, "type": kind, "sha": blob})
            self.responses[f"git/trees/{revision}"] = {"sha": self.git("rev-parse", f"{revision}^{{tree}}"), "truncated": False, "tree": rows}

        def paged(owner, name, endpoint, **kwargs):
            if endpoint == "pulls":
                return [{"number": 6000, "body": self.pr_body, "head": {"ref": h.approval["destination"]["branch"]}}]
            if endpoint == "pulls/6000/reviews":
                return [{"id": 1, "state": "APPROVED", "commit_id": self.head,
                         "submitted_at": "2026-09-17T17:00:00Z", "user": {"login": "reviewer"}}]
            raise AssertionError(endpoint)

        def gh_read(args):
            endpoint = args[1]
            if endpoint.endswith(f"issues/{number}"):
                assert "rasmustho/agentic-pkm-mvp" in endpoint
                return copy.deepcopy(source)
            if endpoint.endswith("pulls/6000"):
                return {"number": 6000, "node_id": "PR_fixture6000", "state": "closed", "merged": True,
                    "merged_at": "2026-09-17T17:30:00Z", "title": self.title, "body": self.pr_body,
                    "head": {"ref": h.approval["destination"]["branch"], "sha": self.head},
                    "base": {"ref": "main", "sha": h.source_state.get("pr_base_sha", h.approval["destination"]["base_sha"])}, "merge_commit_sha": self.merge}
            return h.repository_authority._get("/" + endpoint)

        monkeypatch.setattr(cockpit_github_plane, "_paged_rest", paged)
        monkeypatch.setattr(cockpit_github_plane, "_run_gh", gh_read)
        # Both supplied objects are the real production classes. Only their
        # external HTTP/CLI transports are substituted by this harness.
        monkeypatch.setattr(owner_fact_producers, "_bifrost_sources", lambda: (h.repository_authority, h.host))
        self.credentials = json.loads(self.manifest.read_text())["credentials"]
        for key, principal, kind in (("facts-owner", "owner:human", "human"), ("facts-agent", "agent:builder", "agent")):
            self.credentials.append({"id": key, "principal": principal, "principal_kind": kind,
                "secret_ref": "host-secret:" + key, "verifier_sha256": hashlib.sha256((key + "-test-only-key").encode()).hexdigest(),
                "token_length": len(key + "-test-only-key"), "scopes": ["records:write", "receipts:read"] + (["owner_outcomes:confirm"] if kind == "human" else []),
                "repositories": [self.repository], "rotation_generation": 1})
        self.write_credentials()
        self.client = TestClient(create_app(store=self.store, credentials=self.registry))

    def git(self, *args, **kwargs):
        return subprocess.run(["git", "-C", str(self.harness.worktree), *args],
            check=True, capture_output=True, text=True, **kwargs).stdout.strip()

    def corrupt_merge(self, head, change):
        import os
        env = {**os.environ, "GIT_INDEX_FILE": str(self.harness.worktree.parent / "readiness-index")}
        self.git("read-tree", head, env=env)
        oid = self.git("hash-object", "-w", "--stdin", input="extra source change\n")
        if change in {"swift", "script", "policy"}:
            path = {"swift": "Client.swift", "script": "setup.sh", "policy": ".builderops/delivery-manifest.json"}[change]
            self.git("update-index", "--add", "--cacheinfo", f"100644,{oid},{path}", env=env)
        elif change in {"delete", "rename"}:
            self.git("update-index", "--force-remove", "tracked.txt", env=env)
            if change == "rename":
                old = self.git("rev-parse", f"{head}:tracked.txt")
                self.git("update-index", "--add", "--cacheinfo", f"100644,{old},docs/renamed.md", env=env)
        elif change == "copy":
            old = self.git("rev-parse", f"{head}:tracked.txt")
            self.git("update-index", "--add", "--cacheinfo", f"100644,{old},docs/copied.md", env=env)
        else:
            mode = "120000" if change == "symlink" else "100755"
            old = self.git("rev-parse", f"{head}:docs/guide.md")
            self.git("update-index", "--cacheinfo", f"{mode},{old},docs/guide.md", env=env)
        tree = self.git("write-tree", env=env)
        return self.git("commit-tree", tree, "-p", head, "-m", "external merge delta")

    def binding(self):
        return read_owner_binding(self.repository, self.subject, authority_epoch=1, store=self.store)

    def submit(self, request, key="first", principal="facts-owner", **changes):
        return super().submit(request, key=key, principal=principal, **changes)

    def read(self, key=None):
        params = {"repository": self.repository, "subject_ref": self.subject}
        if key is not None:
            params["idempotency_key"] = key
        return self.client.get("/v1/receipts/owner-outcomes/current", params=params,
            headers={"Authorization": "Bearer facts-owner-test-only-key"})


@pytest.fixture
def bifrost_writer(issue_delivery_production_harness, monkeypatch):
    return BifrostWriter(issue_delivery_production_harness, monkeypatch)


def test_bifrost_documentation_readiness_uses_protected_source(bifrost_writer):
    w = bifrost_writer
    binding = w.binding()
    assert binding["source_revision"] == w.merge
    assert binding["source_revision"] != w.harness.approval["workflow"]["source_revision"]
    assert binding["repository"] == "rasmustho/bifrost"
    assert binding["subject_ref"].startswith("github:rasmustho/agentic-pkm-mvp#")
    assert binding["candidate_ref"]["image_digests"] == "not_applicable"
    assert w.binding() == binding
    readback = w.read()
    assert readback.status_code == 200, readback.text
    assert readback.json()["facts"]["ready_to_try"]["binding_hash"] == binding["binding_hash"]
    submitted = w.submit(w.request())
    assert submitted.status_code == 200, submitted.text
    assert "Documented client behavior" not in json.dumps(w.read().json())


@pytest.mark.parametrize("failure", ["missing_blob", "wrong_blob", "profile", "criteria", "policy",
    "foreign_subject", "foreign_source", "access", "unavailable", "tree_conflict", "forged_readiness",
    "expired", "invalid_window", "late_access_loss"])
def test_bifrost_documentation_admission_rechecks_current_source(bifrost_writer, monkeypatch, failure):
    from app.builderops import owner_fact_producers as producer

    w = bifrost_writer
    request = w.request()
    baseline = w.count("builderops_records")
    doc = w.responses["contents/docs/guide.md"]
    policy = w.harness.source_state["documents"][w.repository]
    if failure == "missing_blob":
        doc["type"] = "missing"
    elif failure == "wrong_blob":
        doc["sha"] = "0" * 40
    elif failure == "profile":
        w.profile["version"] = "2"
    elif failure == "criteria":
        w.profile["criterion_refs"][0]["sha256"] = "0" * 64
    elif failure == "policy":
        policy["required_checks"].append("unpassed-check")
    elif failure == "foreign_subject":
        request["subject_ref"] = "github:rasmustho/bifrost#5550"
    elif failure == "foreign_source":
        request["candidate_ref"]["source_sha"] = w.harness.approval["workflow"]["source_revision"]
        request["source_revision"] = request["candidate_ref"]["source_sha"]
        request["environment_ref"]["commit"] = request["source_revision"]
    elif failure == "access":
        w.responses["collaborators/fixture-owner/permission"]["permission"] = "none"
    elif failure == "unavailable":
        w.harness.source_state["unavailable"] = True
    elif failure == "tree_conflict":
        w.responses[f"git/trees/{w.merge}"]["tree"][0]["sha"] = "0" * 40
    elif failure == "forged_readiness":
        request["readiness_receipt_ref"]["sha256"] = "0" * 64
    elif failure == "expired":
        class Future(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(hours=2)
        monkeypatch.setattr(producer, "datetime", Future)
    elif failure == "invalid_window":
        policy["owner_documentation"]["readiness_ttl_seconds"] = 0
    else:
        original = w.store._fault
        def lose_access(fault_at, point):
            if point == "before_owner_outcome_commit":
                w.responses["collaborators/fixture-owner/permission"]["permission"] = "none"
            return original(fault_at, point)
        monkeypatch.setattr(w.store, "_fault", lose_access)
    response = w.submit(request)
    assert response.status_code in {400, 409, 503}, response.text
    assert w.count("builderops_records") == baseline + (1 if failure == "expired" else 0)
    assert not any(row.get("receipt_body", {}).get("contract") == producer.CONTRACT
                   for row in w.read().json().get("history", []))


@pytest.mark.parametrize("change", ["swift", "script", "policy", "rename", "copy", "delete", "symlink", "executable", "base_substitution", "head_substitution", "remote_tree_substitution", "ancestry_substitution"])
def test_bifrost_readiness_enforces_complete_candidate_diff(issue_delivery_production_harness, monkeypatch, change):
    from app.builderops.owner_fact_producers import OwnerFactRefusal
    substitution = change.endswith("_substitution")
    w = BifrostWriter(issue_delivery_production_harness, monkeypatch, merge_change=None if substitution else change)
    if change == "base_substitution":
        w.harness.source_state["pr_base_sha"] = "0" * 40
    elif change == "head_substitution":
        w.responses[f"git/commits/{w.merge}"]["sha"] = w.harness.approval["workflow"]["source_revision"]
    elif change == "remote_tree_substitution":
        w.responses[f"git/trees/{w.merge}"]["tree"].append({"path": "Extra.swift", "mode": "100644", "type": "blob", "sha": "0" * 40})
    elif change == "ancestry_substitution":
        w.responses[f"compare/{w.harness.approval['destination']['base_sha']}...{w.merge}"]["merge_base_commit"]["sha"] = "0" * 40
    baseline = w.count("builderops_records")
    with pytest.raises(OwnerFactRefusal, match="owner_delivery_conflict|owner_readiness_withdrawn|owner_source_unavailable|owner_complete_tree_conflict" if substitution else "owner_complete_diff_conflict"):
        w.binding()
    assert w.count("builderops_records") == baseline


def test_bifrost_outcome_requires_human_and_current_exact_trial(bifrost_writer):
    w = bifrost_writer
    request = w.request()
    assert w.submit(request, principal="facts-agent").status_code == 403
    assert w.submit(request, confirm=None).status_code == 400
    assert w.submit(request, confirmation_ref={"human_principal": "owner:human"}).status_code == 400
    no_trial = w.request("owner_acceptance", "accepted")
    assert w.submit(no_trial, "premature").status_code == 409
    trial = w.submit(request, "trial").json()["receipt"]
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial["id"]), "accepted")
    assert accepted.status_code == 200, accepted.text
    assert w.read("accepted").json()["projection"]["status"] == "current"
    generic = {"envelope": {"repository": w.repository, "scope": "ordinary", "stack": "builderops", "source_refs": [w.subject]},
        "record_id": request["readiness_receipt_ref"]["id"], "record_type": "BuilderOpsReceipt", "state": "active",
        "payload": {}, "idempotency_key": "forged"}
    assert w.client.post("/v1/records", json=generic, headers={"Authorization": "Bearer facts-agent-test-only-key",
        "X-BuilderOps-Authority-Epoch": "1"}).status_code == 403
    from app.builderops.control_plane.models import AuthorityEnvelope
    from app.builderops.owner_fact_producers import OwnerFactRefusal
    with pytest.raises(OwnerFactRefusal, match="owner_readiness_source_required"):
        w.store.commit_record(envelope=AuthorityEnvelope(repository=w.repository, scope="owner-readiness", stack="builderops-control-plane",
            actor="bifrost_git_documentation_source", source_refs=(w.subject,)), record_id=generic["record_id"],
            record_type="BuilderOpsReceipt", state="active", payload={}, idempotency_key=generic["record_id"])


def test_bifrost_corrections_and_withdrawal_preserve_outcome_history(bifrost_writer, monkeypatch):
    w = bifrost_writer
    request = w.request()
    trial = w.submit(request, "trial").json()["receipt"]
    acceptance = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial["id"]), "acceptance").json()["receipt"]
    correction = {**request, "expected_previous_receipt_id": trial["id"], "supersedes_receipt_id": trial["id"], "correction_reason": "owner_correction"}
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda key: w.submit(correction, key), ("correction-a", "correction-b")))
    assert sorted(r.status_code for r in results) == [200, 409]
    current_trial = next(r.json()["receipt"] for r in results if r.status_code == 200)
    assert w.read("acceptance").json()["projection"]["reason"] == "trial_corrected"
    w.responses["collaborators/fixture-owner/permission"]["permission"] = "none"
    unable = {**correction, "outcome": "unable_to_try", "observation": [],
        "expected_previous_receipt_id": current_trial["id"], "supersedes_receipt_id": current_trial["id"]}
    result = w.submit(unable, "unable")
    assert result.status_code == 200, result.text
    withdrawn = w.read("unable").json()
    assert withdrawn["binding"]["readiness_status"] == "withdrawn"
    assert withdrawn["facts"]["ready_to_try"] is None
    assert w.read("acceptance").json()["receipt"] == acceptance
    missing = copy.deepcopy(unable)
    missing["readiness_receipt_ref"]["id"] = "bifrost-readiness:" + "0" * 64
    assert w.submit(missing, "missing-history").status_code in {409, 503}
    # A fully re-observed, refreshed source window is a new binding; it cannot
    # carry either earlier trial or acceptance into a new human decision slot.
    from app.builderops import owner_fact_producers as producer
    w.responses["collaborators/fixture-owner/permission"]["permission"] = "read"
    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=2)
    monkeypatch.setattr(producer, "datetime", Future)
    refreshed = w.read().json()
    assert refreshed["binding"]["readiness_receipt_ref"] != request["readiness_receipt_ref"]
    assert refreshed["facts"]["ready_to_try"] is not None
    assert refreshed["facts"]["owner_trial"] is refreshed["facts"]["owner_acceptance"] is None
    assert w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=current_trial["id"]), "carry-trial").status_code == 409


def test_bifrost_restart_and_source_outage_preserve_durable_fact(bifrost_writer, monkeypatch):
    w = bifrost_writer
    request = w.request()
    original = w.store._fault
    def lost_response(fault_at, point):
        if point == "after_owner_outcome_commit":
            raise TimeoutError("lost outcome response")
        return original(fault_at, point)
    monkeypatch.setattr(w.store, "_fault", lost_response)
    response = w.submit(request, "lost")
    assert response.status_code >= 500, response.text
    monkeypatch.setattr(w.store, "_fault", original)
    prior = w.read("lost").json()["receipt"]
    counts = tuple(w.count(table) for table in ("builderops_records", "builderops_receipts", "builderops_outbox"))
    w.client = TestClient(create_app(store=type(w.store)(w.store.dsn), credentials=CredentialRegistry(w.manifest)))
    w.harness.source_state["unavailable"] = True
    historical = w.read("lost")
    assert historical.status_code == 200, historical.text
    assert historical.json()["receipt"] == prior
    assert historical.json()["projection"]["status"] == "unavailable"
    assert w.submit(request, "lost").json()["receipt"] == prior
    assert tuple(w.count(table) for table in ("builderops_records", "builderops_receipts", "builderops_outbox")) == counts
    w.harness.source_state["unavailable"] = False
    w.harness.source_state["fail_access_at"] = 2
    late_outage = w.read("lost")
    assert late_outage.status_code == 200, late_outage.text
    assert late_outage.json()["receipt"] == prior
    assert late_outage.json()["projection"]["status"] == "unavailable"
    assert w.harness.source_state["access_reads"] == 2
    assert w.submit({**request, "outcome": "unable_to_try", "observation": []}, "outage-not-withdrawal").status_code == 503


@pytest.mark.parametrize("damage", ["journal", "idempotency", "envelope", "record_type", "payload"])
def test_bifrost_retained_readiness_requires_durable_lineage(bifrost_writer, damage):
    from psycopg.types.json import Jsonb

    w = bifrost_writer
    request = w.request(outcome="unable_to_try", observation=[])
    identity = request["readiness_receipt_ref"]["id"]
    w.responses["collaborators/fixture-owner/permission"]["permission"] = "none"
    with w.store._connect() as conn:
        if damage == "journal":
            conn.execute("DELETE FROM builderops_receipts WHERE repository=%s AND task_id=%s", (w.repository, identity))
        elif damage == "idempotency":
            conn.execute("DELETE FROM builderops_idempotency WHERE repository=%s AND idempotency_key=%s", (w.repository, identity))
        elif damage == "envelope":
            conn.execute("UPDATE builderops_records SET authority_envelope=%s WHERE record_id=%s", (Jsonb({"actor": "forged"}), identity))
        elif damage == "record_type":
            conn.execute("UPDATE builderops_records SET record_type='Untrusted' WHERE record_id=%s", (identity,))
        else:
            conn.execute("UPDATE builderops_records SET payload=jsonb_set(payload, '{receipt_body,observed_at}', '\"2026-01-01T00:00:00Z\"'::jsonb) WHERE record_id=%s", (identity,))
    refused = w.submit(request, "corrupt-retained")
    assert refused.status_code in {409, 503}, refused.text
    with w.store._connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM builderops_records WHERE authority_envelope->>'scope'='owner-outcome'").fetchone()["n"] == 0


def test_production_writer_is_authorized_version_bound_and_idempotent(owner_writer, monkeypatch):
    from app.builderops.owner_fact_producers import canonical_json, validate_outcome_request
    golden = json.loads(V1_REQUEST_BYTES)
    assert canonical_json(validate_outcome_request(golden, confirmed_at="2026-09-17T00:00:01Z")) == V1_REQUEST_BYTES
    assert outcome_request_hash(golden) == "eca0b1b1102ec509f4466445cc64acf8a16ae8b45bc283b0a3b710537185f426"
    w = owner_writer
    request = w.request()
    for principal in ("agent", "other"):
        assert w.submit(request, principal=principal).status_code == 403
    assert w.submit(request, confirm=None).status_code == 400
    assert w.submit(request, confirmation_ref={"principal": "human:owner"}).status_code == 400
    forged = {**request, "recorded_at": datetime.now(timezone.utc).isoformat()}
    assert w.submit(forged).status_code == 400
    stale = copy.deepcopy(request)
    stale["authorization_ref"]["version"] = "stale"
    assert w.submit(stale).status_code == 409
    # The raw production parser must reject duplicate keys before admission.
    raw = json.dumps({"record_type": "BuilderOpsReceipt", "owner_outcome": {"contract": "builder_owner_outcome.v1", "request": request,
        "request_sha256": outcome_request_hash(request), "confirm": "confirm"}, "idempotency_key": "first"})
    raw = raw.replace('"confirm": "confirm"', '"confirm": "confirm", "confirm": "confirm"')
    assert w.client.post("/v1/records", content=raw, headers={"Content-Type": "application/json", "Authorization": "Bearer owner-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 400
    for field, value in (("owner_actor", "human:owner"), ("outcome", {}), ("observed_at", "2030-01-01T00:00:00Z")):
        assert w.submit({**request, field: value}).status_code == 400
    original_now = w.store._database_now
    monkeypatch.setattr(w.store, "_database_now", lambda conn: datetime.now(timezone.utc) - timedelta(seconds=10))
    assert w.submit(request).json()["detail"] == "owner_confirmation_clock_unavailable"
    monkeypatch.setattr(w.store, "_database_now", original_now)
    assert w.count("builderops_records") == 0
    response = w.submit(request)
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["receipt_body"]["request"] == request
    assert receipt["receipt_body"]["request_sha256"] == outcome_request_hash(request)
    confirmation = receipt["receipt_body"]["confirmation_ref"]
    assert confirmation["request_sha256"] == outcome_request_hash(request)
    assert confirmation["confirmed_at"] <= receipt["receipt_body"]["recorded_at"]
    assert w.submit(request).json()["receipt"] == receipt
    assert w.count("builderops_records") == w.count("builderops_receipts") == w.count("builderops_idempotency") == w.count("builderops_outbox") == 1
    generic = {"envelope": {"repository": REPO, "scope": "owner-outcome", "stack": "builderops", "source_refs": [SUBJECT]},
        "record_id": "ordinary-record", "record_type": "BuilderOpsReceipt", "state": "active", "payload": {}, "idempotency_key": "ordinary-record"}
    assert w.client.post("/v1/records", json=generic, headers={"Authorization": "Bearer agent-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 403
    generic["envelope"]["scope"] = "ordinary"
    generic["idempotency_key"] = "owner-outcome:reserved"
    assert w.client.post("/v1/records", json=generic, headers={"Authorization": "Bearer agent-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 403
    assert w.read("first").json()["receipt"] == receipt
    w.credentials[1]["scopes"].append("leases:write")
    w.write_credentials()
    lease = w.client.post("/v1/leases/claim", json={"envelope": generic["envelope"],
        "resource_id": receipt["id"], "idempotency_key": "ordinary-lease"},
        headers={"Authorization": "Bearer agent-test-only-key", "X-BuilderOps-Authority-Epoch": "1"})
    assert lease.status_code == 200, lease.text
    readback = w.read("first")
    assert readback.status_code == 200, readback.text
    assert readback.json()["receipt"] == receipt
    assert w.submit(request).json()["receipt"] == receipt
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=receipt["id"]), "accepted").json()["receipt"]
    w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
    w.write_credentials()
    withdrawn = w.read("accepted").json()
    assert withdrawn["receipt"] == accepted
    assert withdrawn["facts"]["owner_trial"] is withdrawn["facts"]["owner_acceptance"] is None
    assert withdrawn["projection"]["reason"] == "owner_grant_unavailable"
    w.credentials.append(w.entry("replacement", "human:owner", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]))
    w.write_credentials()
    recovered = w.read("accepted").json()
    assert recovered["facts"]["owner_acceptance"] == accepted
    assert recovered["projection"]["status"] == "current"


@pytest.mark.parametrize("outcomes", [("accepted", "rejected"), ("accepted", "accepted")])
def test_conflicting_submissions_require_explicit_correction(owner_writer, outcomes):
    w = owner_writer
    trial = w.submit(w.request(), "trial").json()["receipt"]
    requests = [w.request("owner_acceptance", outcome, trial_receipt_ref=trial["id"]) for outcome in outcomes]
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda pair: w.submit(pair[1], pair[0]), zip(("a", "b"), requests)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["detail"] == "current_receipt_conflict"
    winner_index = next(i for i, r in enumerate(responses) if r.status_code == 200)
    key, request = ("a", "b")[winner_index], requests[winner_index]
    assert w.submit(request, key).json()["receipt"] == responses[winner_index].json()["receipt"]
    assert w.submit({**request, "decided_at": "2026-01-01T00:00:00Z"}, key).json()["detail"] == "idempotency_conflict"
    previous = responses[winner_index].json()["receipt"]["id"]
    correction = w.request("owner_acceptance", "rejected", expected_previous_receipt_id=previous,
        supersedes_receipt_id=previous, correction_reason="owner_correction")
    assert w.submit(correction, "correction", confirm=None).status_code == 400
    assert w.submit(correction, "correction").status_code == 200


@pytest.mark.parametrize("correction_first", [True, False])
def test_acceptance_and_trial_correction_share_serialization(owner_writer, correction_first, monkeypatch):
    from app.builderops.control_plane import store as owner_store

    w = owner_writer
    old = w.submit(w.request(), "trial").json()["receipt"]["id"]
    acceptance = w.request("owner_acceptance", "accepted", trial_receipt_ref=old)
    correction = w.request(expected_previous_receipt_id=old, supersedes_receipt_id=old, correction_reason="owner_correction")
    held, attempted, release = threading.Event(), threading.Event(), threading.Event()
    lock, fault = owner_store._owner_outcome_lock, w.store._fault
    calls = []
    def observed_lock(*args):
        calls.append(args[-1])
        if len(calls) == 2:
            attempted.set()
        return lock(*args)
    def hold_first(_requested, point):
        if point == "before_owner_outcome_commit" and not held.is_set():
            held.set()
            assert release.wait(5)
        return fault(_requested, point)
    monkeypatch.setattr(owner_store, "_owner_outcome_lock", observed_lock)
    monkeypatch.setattr(w.store, "_fault", hold_first)
    first, second = ((correction, "correction"), (acceptance, "acceptance")) if correction_first else ((acceptance, "acceptance"), (correction, "correction"))
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(w.submit, *first)
        assert held.wait(5)
        b = pool.submit(w.submit, *second)
        assert attempted.wait(5)
        release.set()
        responses = [a.result(), b.result()]
    assert calls[0] == calls[1]
    assert responses[0].status_code == 200
    if correction_first:
        assert responses[1].json()["detail"] == "trial_receipt_conflict"
    else:
        accepted = responses[0].json()["receipt"]
        assert responses[1].status_code == 200
        evidence = w.read("acceptance").json()
        assert evidence["receipt"]["id"] == accepted["id"]
        assert evidence["projection"]["status"] == "withdrawn"
        # A delayed rebuild of the actual acceptance intent reads the current
        # production source/chain. The old intent carries no projection state.
        with w.store._connect() as conn:
            intent = conn.execute("SELECT payload FROM builderops_outbox WHERE task_id=%s", (accepted["id"],)).fetchone()["payload"]
        delayed = w.store.get_owner_outcomes(REPO, intent["subject_ref"], idempotency_key="acceptance", grant_reader=w.registry.has_owner_outcome_grant)
        assert delayed["projection"]["status"] == "withdrawn"
    assert w.read().json()["facts"]["owner_acceptance"] is None


@pytest.mark.parametrize("field", ["candidate_ref", "environment_ref", "readiness_receipt_ref", "readiness_expiry"])
def test_changed_candidate_cannot_inherit_trial_or_acceptance(owner_writer, field, monkeypatch):
    w = owner_writer
    trial = w.submit(w.request(), "trial").json()["receipt"]["id"]
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial), "accepted").json()["receipt"]
    if field == "readiness_expiry":
        from app.builderops import devui_receipts
        from app.builderops.control_plane import store as owner_store

        observed = datetime.fromisoformat(w.chain[-1]["observed_at"])
        monkeypatch.setenv("DEVUI_VM102_RECEIPT_MAX_AGE_SECONDS", "1")
        monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed)
        original_lock = owner_store._owner_outcome_lock
        def expires_while_waiting(*args):
            original_lock(*args)
            monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed + timedelta(seconds=2))
        monkeypatch.setattr(owner_store, "_owner_outcome_lock", expires_while_waiting)
        result = w.read("accepted").json()
        assert result["facts"]["ready_to_try"] is None
        assert result["facts"]["owner_acceptance"] is None
        assert result["receipt"] == accepted and result["projection"]["status"] == "withdrawn"
        return
    changed = w.request()
    changed[field] = {**changed[field], "changed": "new-source-binding"}
    assert w.submit(changed, "changed").status_code in {400, 409}
    if field == "environment_ref":
        # This source owns only VM102. A foreign target is unavailable, never
        # an admitted E2 carrying the old owner's consent.
        for index, receipt in enumerate(copy.deepcopy(w.chain)):
            receipt["target_vm"]["vmid"] = 103
            (w.root / f"{index}-runtime.json").write_text(json.dumps(receipt))
        assert w.read().status_code == 503
        history = w.read("accepted").json()
        assert history["receipt"] == accepted and history["projection"]["status"] == "unavailable"
        return
    if field == "candidate_ref":
        w.bundle["evidence"]["candidate_identity"]["devui_config_fingerprint"] = "sha256:" + "9" * 64
        for row in w.bundle["evidence"]["topology"]:
            if row["component_id"] == "devui_projection":
                row["source_identity"]["config_fingerprint"] = "sha256:" + "9" * 64
    else:
        w.bundle["evidence"]["observed_at"] = datetime.now(timezone.utc).isoformat()
        for row in w.bundle["evidence"]["topology"]:
            row["observed_at"] = w.bundle["evidence"]["observed_at"]
    _component_evidence(w.bundle["evidence"], w.bundle["prerequisites"], "qualification")
    w.write_sources()
    current = w.read().json()
    assert current["facts"]["owner_trial"] is current["facts"]["owner_acceptance"] is None
    assert w.read("accepted").json()["receipt"] == accepted
    assert w.read("accepted").json()["projection"]["status"] == "withdrawn"


def test_changed_profile_and_trial_correction_withdraw_acceptance(owner_writer, monkeypatch):
    from app.builderops import devui_receipts

    w = owner_writer
    rejected = w.submit(w.request("owner_acceptance", "rejected"), "rejected")
    assert rejected.status_code == 200
    assert w.read().json()["facts"]["owner_trial"] is None
    w.profile["limitation_refs"] = [{"id": "limit:unavailable", "sha256": "c" * 64}]
    w.write_sources()
    unable = w.request(outcome="unable_to_try", observation=[])
    trial = w.submit(unable, "unable").json()["receipt"]["id"]
    assert w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial), "accept").status_code == 409
    w.profile["criterion_refs"][0]["sha256"] = "d" * 64
    w.write_sources()
    assert w.read().json()["facts"]["owner_trial"] is None
    unable = w.request(outcome="unable_to_try", observation=[])
    # Advance only the source freshness clock; retained typed bytes still prove
    # which candidate was attempted, without proving current readiness.
    observed = datetime.fromisoformat(w.chain[-1]["observed_at"])
    monkeypatch.setenv("DEVUI_VM102_RECEIPT_MAX_AGE_SECONDS", "1")
    monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed + timedelta(seconds=2))
    result = w.submit(unable, "unable-after-withdrawal")
    assert result.status_code == 200, result.text
    current = w.read().json()
    assert current["facts"]["ready_to_try"] is None
    assert current["facts"]["owner_trial"]["receipt_body"]["request"]["outcome"] == "unable_to_try"
    assert current["facts"]["owner_acceptance"] is None


def test_unavailable_writer_does_not_create_owner_outcome(owner_writer, monkeypatch):
    w = owner_writer
    request = w.request()
    (w.root / "devui-runtime-prerequisites.json").unlink()
    assert w.submit(request).status_code == 503
    assert w.count("builderops_records") == 0
    response = w.read()
    assert response.status_code == 503
    assert "facts" not in response.json()
    w.write_sources()
    w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
    w.write_credentials()
    assert w.submit(request).status_code == 403
    assert w.count("builderops_outbox") == 0
    w.credentials[0]["scopes"].append("owner_outcomes:confirm")
    w.write_credentials()
    fault = w.store._fault
    def revoke(_requested, point):
        if point == "before_owner_outcome_commit":
            w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
            w.write_credentials()
        return fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", revoke)
    assert w.submit(request).status_code == 403
    assert w.count("builderops_receipts") == 0


@pytest.mark.parametrize("missing_record", ["all", "terminal"])
def test_restart_reconciles_written_fact_before_projection(owner_writer, monkeypatch, missing_record):
    w = owner_writer
    request = w.request()
    original_fault = w.store._fault
    def fault(_requested, point):
        if point == "after_owner_outcome_receipt":
            raise RuntimeError("precommit interruption")
        return original_fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", fault)
    assert w.submit(request).status_code == 503
    for table in ("builderops_records", "builderops_receipts", "builderops_idempotency", "builderops_outbox"):
        assert w.count(table) == 0
    def lost_response(_requested, point):
        if point == "after_owner_outcome_commit":
            raise RuntimeError("response lost")
        return original_fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", lost_response)
    assert w.submit(request).status_code == 503
    assert w.count("builderops_records") == 1
    monkeypatch.setattr(w.store, "_fault", original_fault)
    original_read = w.store.get_owner_outcomes
    monkeypatch.setattr(w.store, "get_owner_outcomes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("projection unavailable")))
    unavailable = w.submit(request).json()
    assert unavailable["projection"]["status"] == "unavailable"
    original_receipt = unavailable["receipt"]
    monkeypatch.setattr(w.store, "get_owner_outcomes", original_read)
    restarted = type(w.store)(w.store.dsn)
    w.client = TestClient(create_app(store=restarted, credentials=w.registry))
    receipt = w.submit(request).json()["receipt"]
    assert receipt == original_receipt
    assert w.read("first").json()["receipt"] == receipt
    assert w.count("builderops_records") == 1
    terminal = None
    if missing_record == "terminal":
        accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=receipt["id"]), "accepted").json()["receipt"]
        terminal = w.submit(w.request("owner_acceptance", "rejected", expected_previous_receipt_id=accepted["id"], supersedes_receipt_id=accepted["id"], correction_reason="owner_correction"), "terminal").json()["receipt"]["id"]
    with w.store._connect() as conn:
        if terminal is not None:
            conn.execute("DELETE FROM builderops_records WHERE repository = %s AND record_id = %s", (REPO, terminal))
        else:
            conn.execute("DELETE FROM builderops_records WHERE repository = %s", (REPO,))
    assert w.read().status_code == 503
    assert w.submit(request).status_code == 503
    assert w.read("first").status_code == 503
