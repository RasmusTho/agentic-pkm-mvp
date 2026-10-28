from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, RLock, get_ident
import time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import yaml

from app.governance.governed_write import GovernedWriteAdapter, InvalidDecisionTokenError
from app.instance import context_bound_write
from app.instance.active_context_service import ActiveContextSelectionService
from app.instance.context_selection import ContextSelectionError, ContextSelectionStore
from app.knowledge import adapters, semantic
from app.knowledge.semantic import CLASSIFY, REORDER, TAGS_ADD, TAGS_REMOVE, KnowledgeSemanticOwner
from app.knowledge.write_ops import read_note_text_with_version
from app.operations import (
    JsonReceiptStore,
    OperationContext,
    OperationExecutionKernel,
    OperationRequest,
    OperationStatus,
    PolicyDecision,
)
from app.operations.contracts import ConvergenceState, OperationProvenance, SourceEffectStatus
from app.operations.semantic_operations import (
    SemanticOperationServerConfig,
    build_semantic_operation_handlers,
)
from tests._mvr03_principal_harness import provisioned_instance
from tests.api._vault_test_helpers import bind_initialized_vault


@dataclass
class Harness:
    config: SemanticOperationServerConfig
    identity: str
    members: list[str]
    note: Path
    approvals: dict[str, tuple[dict[str, Any], Any]]
    approval_lock: Any
    selections: ContextSelectionStore
    selection_record: Any
    bearer: str = field(repr=False)
    hooks: dict[str, Any]

    @property
    def owner(self):
        return self.config.owner

    def request(self, operation=REORDER, arguments=None, *, request_id=None, version=None):
        return OperationRequest(
            operation,
            request_id or str(uuid4()),
            self.config.context,
            targets=({"artifact_id": self.identity},),
            arguments=arguments if arguments is not None else {"ordered_ids": self.members[::-1]},
            expected_version=version or read_note_text_with_version(self.note)[1],
            provenance=OperationProvenance(self.owner.actor, "direct-test", "test"),
        )

    def approve(self, request, changes=None, *, write_class="vault_semantic_edit"):
        changes = changes if changes is not None else {"member_order": self.members[::-1]}
        gov = GovernedWriteAdapter()
        grant = gov.issue_human_decision_token(
            action=f"operation.{request.operation_id}",
            write_class=write_class,
            actor=self.owner.actor,
            resource="Notes/collection.md",
        )
        grant = gov.bind_context(
            grant, context=self.owner.active_context, target_binding_id=self.owner.target_binding_id
        )
        with self.approval_lock:
            self.approvals[request.request_id] = (
                {
                    "operation": request.operation_id,
                    "artifact_id": self.identity,
                    "expected_version": request.expected_version,
                    "changes": json.loads(json.dumps(changes)),
                    "resource": "Notes/collection.md",
                    "context_ref": self.config.context.active_context_ref,
                    "vault_generation": self.config.context.vault_generation,
                },
                grant,
            )
        return request

    def revoke_approval(self, request_id):
        with self.approval_lock:
            self.approvals.pop(request_id, None)

    def change_selection(self, action="clear"):
        arguments = dict(
            principal=self.selection_record.principal,
            instance_identity=self.selection_record.instance_identity,
        )
        if action == "clear":
            self.selections.clear(self.bearer, **arguments)
        elif action == "replace":
            self.selections.replace_bindings(
                self.bearer, binding_ids=self.selection_record.binding_ids, **arguments
            )
        else:
            self.selections.invalidate_digest(self.selection_record.selection_capability_digest)

    def selection_current(self):
        try:
            return (
                self.selections.inspect(
                    self.bearer,
                    principal=self.selection_record.principal,
                    instance_identity=self.selection_record.instance_identity,
                )
                is self.selection_record
            )
        except ContextSelectionError:
            return False

    def kernel(self, *, config=None, store=None):
        config = config or self.config
        return OperationExecutionKernel(
            context_resolver=lambda _: self.selection_current(),
            policy_evaluator=lambda *_: PolicyDecision.allowed("policy-1"),
            handlers=build_semantic_operation_handlers(config),
            receipt_store=store
            or JsonReceiptStore(self.note.parent.parent.parent / "operations.json"),
            version_checker=lambda _: True,
            token_validator=lambda *_: True,
        )

    def run(self, request, *, kernel=None):
        delegation = {
            "active_context_ref": self.config.context.active_context_ref,
            "vault_generation": self.config.context.vault_generation,
            "operation_ids": [request.operation_id],
            "allowed_effects": [request.operation_id],
            "policy_version": "policy-1",
            "principal": self.owner.actor,
            "client": "test",
            "surface": "test",
            "receipt_ref": "delegation-1",
            "authority_class": "governed_effect",
            "target_ids": [self.identity],
            "max_targets": 1,
            "expires_at": 4102444800,
            "revoked": False,
        }
        return (kernel or self.kernel()).execute(request, delegation)

    def records(self):
        return [
            json.loads(line)["payload"] for line in self.owner.receipt_path.read_text().splitlines()
        ]

    def metadata(self):
        return yaml.safe_load(self.note.read_text().split("---", 2)[1])


@pytest.fixture
def bound(tmp_path, monkeypatch):
    runtime, registration, _, principal = provisioned_instance(tmp_path / "instance")
    root = Path(registration.path)
    bind_initialized_vault(monkeypatch, root, store_dir=tmp_path, channel=runtime.layout.channel_id)
    runtime.complete_initialization(
        registration.vault_binding_id,
        vault_id="vault-" + registration.vault_binding_id,
        local_instance_id=registration.local_instance_id,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    service = ActiveContextSelectionService(
        registry_store=runtime.registry,
        principal_record=principal,
        selection_store=ContextSelectionStore(),
    )
    derived = service.derive("trusted_loopback")
    bearer, selection_record = service.create(
        derived=derived, binding_ids=[registration.vault_binding_id]
    )
    context = service.resolve_request_context(
        derived=derived,
        session_bearer=bearer,
        override_bearer=None,
        action="operation.collection.reorder",
        write_class="vault_semantic_edit",
        required_permission="write",
    ).snapshot
    (root / "Notes").mkdir()
    identity = str(uuid4())
    members = [str(uuid4()), str(uuid4())]
    for index, member in enumerate(members):
        (root / f"Notes/member-{index}.md").write_text(
            f"---\nuuid: {member}\nartifact_class: human_knowledge\n---\nMember {index}.\n"
        )
    note = root / "Notes/collection.md"
    note.write_bytes(
        (
            f"---\r\nuuid: {identity}\r\nartifact_class: human_knowledge\r\nartifact_type: concept_note\r\n"
            "tags: [Research]\r\nmember_order:\r\n"
            + "".join(f"  - {member}\r\n" for member in members)
            + "trust: human\r\nlifecycle: active\r\nreview_state: reviewed\r\n"
            "unrelated: {meaning: 'keep this exact spelling'} # human comment\r\n---\r\n\r\n# Human body\r\nPreserve every body byte.\r\n"
        ).encode()
    )
    approvals: dict[str, tuple[dict[str, Any], Any]] = {}
    approval_lock = RLock()
    hooks = {}

    def matches(intent, approval):
        return approval is not None and all(
            getattr(intent, key) == value for key, value in approval[0].items()
        )

    def authorize(intent):
        with approval_lock:
            approval = approvals.get(intent.request_id)
            return approval[1] if matches(intent, approval) else None

    @contextmanager
    def authority_window(intent, grant):
        # The real WSP API owns the record lock; the exact human approval
        # producer owns this fixture-only data and every mutation of it.
        # No resolver is called while either owner lock is held.
        snapshot = owner.active_context
        if (
            snapshot.context_id != selection_record.context_id
            or snapshot.selection_capability_digest != selection_record.selection_capability_digest
            or snapshot.principal_context != selection_record.principal
            or snapshot.instance_identity != selection_record.instance_identity
            or snapshot.binding_ids != selection_record.binding_ids
            or snapshot.workspace != selection_record.workspace
            or snapshot.scope != selection_record.scope
            or snapshot.sphere_memberships != selection_record.sphere_memberships
            or snapshot.situated_identity != selection_record.situated_identity
            or snapshot.dimension_filter != selection_record.dimension_filter
            or snapshot.expires_at is None
            or snapshot.expires_at > selection_record.expires_at
        ):
            raise InvalidDecisionTokenError("selection record does not produce the frozen context")
        with (
            service.selection_store.read_effect_window(
                bearer,
                principal=selection_record.principal,
                instance_identity=selection_record.instance_identity,
                expected_record=selection_record,
            ) as require_selection,
            approval_lock,
        ):
            captured = approvals.get(intent.request_id)
            if not matches(intent, captured) or captured[1] != grant:
                raise InvalidDecisionTokenError("exact human approval is unavailable")
            thread = get_ident()
            active = True
            if hooks.get("lookup") is not None:
                hooks["lookup"](intent, grant)

            def require_current():
                # Owned, nonblocking reads only. Approval first, WSP record
                # last: no foreign callback follows either final observation.
                if (
                    not active
                    or get_ident() != thread
                    or approvals.get(intent.request_id) is not captured
                ):
                    raise InvalidDecisionTokenError("exact human approval changed")
                require_selection()

            try:
                require_current()
                yield require_current
            finally:
                active = False
                if hooks.get("exit_error") is not None:
                    raise hooks["exit_error"]

    owner = KnowledgeSemanticOwner(
        vault_root=root,
        active_context=context,
        target_binding_id=registration.vault_binding_id,
        registry_store=runtime.registry,
        authorize_semantic=authorize,
        semantic_authority_window=authority_window,
        receipt_path=tmp_path / "semantic-outbox.jsonl",
    )
    return Harness(
        SemanticOperationServerConfig(
            owner, OperationContext(context.context_id, str(context.generation))
        ),
        identity,
        members,
        note,
        approvals,
        approval_lock,
        service.selection_store,
        selection_record,
        bearer,
        hooks,
    )


def test_classification_and_tags_use_canonical_versioned_owner_paths(bound):
    original = bound.note.read_bytes()
    request = bound.request(
        CLASSIFY, {"artifact_class": " MEDIA_NOTE ", "artifact_type": " PHOTO "}
    )
    result = bound.run(
        bound.approve(request, {"artifact_class": "media_note", "artifact_type": "photo"})
    )
    assert result.status is OperationStatus.CONVERGENCE_PENDING
    assert bound.metadata()["artifact_class"] == "media_note"
    assert bound.metadata()["artifact_type"] == "photo"
    add = bound.request(TAGS_ADD, {"tags": [" #Work ", "#RESEARCH", "work"]})
    assert (
        bound.run(bound.approve(add, {"tags": ["research", "work"]})).status
        is OperationStatus.CONVERGENCE_PENDING
    )
    assert bound.metadata()["tags"] == ["research", "work"]
    remove = bound.request(TAGS_REMOVE, {"tags": [" #Research "]})
    assert (
        bound.run(bound.approve(remove, {"tags": ["work"]})).status
        is OperationStatus.CONVERGENCE_PENDING
    )
    assert bound.metadata()["tags"] == ["work"]
    assert bound.note.read_bytes().split(b"---\r\n", 2)[-1] == original.split(b"---\r\n", 2)[-1]
    assert (
        b"unrelated: {meaning: 'keep this exact spelling'} # human comment\r\n"
        in bound.note.read_bytes()
    )
    assert bound.metadata()["uuid"] == bound.identity
    assert (
        bound.metadata()["trust"],
        bound.metadata()["lifecycle"],
        bound.metadata()["review_state"],
    ) == ("human", "active", "reviewed")
    for record in bound.records():
        assert record["source_receipt"]["outcome"] == "written"
        assert record["source_receipt"]["locator"]["vault"] == bound.owner.target_binding_id
        assert record["authority_receipt"]["effect_id"] == record["request_id"]
        assert record["authority_receipt"]["actor"] == bound.owner.actor
        assert (
            record["decision_token"]["active_context"]["context_id"]
            == bound.config.context.active_context_ref
        )
        assert record["input_version"] != record["resulting_version"]


@pytest.mark.parametrize(
    "values", ["missing", None, "not-a-list", ["bad-uuid"], "duplicate", "unresolved"]
)
def test_reorder_rejects_invalid_source_members_before_mutation(bound, values):
    text = bound.note.read_text()
    start, end = text.index("member_order:"), text.index("trust:")
    if values == "missing":
        replacement = ""
    else:
        members = (
            [bound.members[0], bound.members[0]]
            if values == "duplicate"
            else [str(uuid4())]
            if values == "unresolved"
            else values
        )
        replacement = yaml.safe_dump({"member_order": members})
    bound.note.write_text(text[:start] + replacement + text[end:])
    original = bound.note.read_bytes()
    result = bound.run(bound.request())
    assert result.status is OperationStatus.INVALID
    assert bound.note.read_bytes() == original
    assert not bound.owner.receipt_path.exists()


def test_reorder_validates_complete_versioned_membership(bound):
    original = bound.note.read_bytes()
    for ordered in ([bound.members[0]], bound.members + [str(uuid4())], [bound.members[0]] * 2):
        result = bound.run(bound.request(arguments={"ordered_ids": ordered}))
        assert result.status is OperationStatus.INVALID
        assert bound.note.read_bytes() == original
    request = bound.request(version="0" * 64)
    assert bound.run(request).status is OperationStatus.CONFLICTED
    assert bound.note.read_bytes() == original
    request = bound.approve(bound.request())
    assert bound.run(request).status is OperationStatus.CONVERGENCE_PENDING
    assert bound.metadata()["member_order"] == bound.members[::-1]
    # A different operation identity still has to respect the source version.
    stale = replace(request, request_id=str(uuid4()))
    assert bound.run(stale).status is OperationStatus.CONFLICTED


def test_reorder_uses_hka_source_cas_and_durable_receipts(bound):
    original = bound.note.read_bytes()
    member_bytes = [
        (bound.owner.root / f"Notes/member-{index}.md").read_bytes() for index in range(2)
    ]
    request = bound.approve(bound.request())
    kernel = bound.kernel()
    result = bound.run(request, kernel=kernel)
    assert result.status is OperationStatus.CONVERGENCE_PENDING
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    after = bound.note.read_bytes()
    assert (
        after != original and sha256(after).hexdigest() == bound.records()[0]["resulting_version"]
    )
    assert bound.metadata()["member_order"] == bound.members[::-1]
    assert bound.metadata()["uuid"] == bound.identity
    assert after.split(b"---\r\n", 2)[-1] == original.split(b"---\r\n", 2)[-1]
    assert member_bytes == [
        (bound.owner.root / f"Notes/member-{index}.md").read_bytes() for index in range(2)
    ]
    first = bound.records()[0]
    assert first["authority_receipt"]["source_receipt_ref"].endswith(":Notes/collection.md")
    assert first["authority_receipt"]["target_binding_id"] == bound.owner.target_binding_id
    # Reconstruct both owner and receipt store; replay reads history without a
    # fresh approval, current source version, or a second HKA effect.
    previous = bound.owner
    restarted = KnowledgeSemanticOwner(
        vault_root=previous.root,
        active_context=previous.active_context,
        target_binding_id=previous.target_binding_id,
        registry_store=previous.registry_store,
        authorize_semantic=lambda _: pytest.fail("completed replay requested another approval"),
        semantic_authority_window=previous.semantic_authority_window,
        receipt_path=previous.receipt_path,
    )
    restarted_config = replace(bound.config, owner=restarted)
    assert (
        bound.run(request, kernel=bound.kernel(config=restarted_config)).to_dict()
        == result.to_dict()
    )
    assert bound.note.read_bytes() == after and bound.records() == [first]


def test_semantic_projection_failure_is_truthful_and_recoverable(bound):
    def fail_projection(_):
        raise OSError("projection is unavailable")

    bound.owner.reconcile_projection = fail_projection
    request = bound.approve(bound.request())
    result = bound.run(request)
    assert result.status is OperationStatus.CONVERGENCE_PENDING
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert result.convergence.index is ConvergenceState.REBUILD_REQUIRED
    assert bound.metadata()["member_order"] == bound.members[::-1]
    assert "repair" in result.warnings[0]
    assert bound.run(request).to_dict() == result.to_dict()
    assert len(bound.records()) == 1


def test_semantic_handlers_preserve_canvas_policy_and_dormant_activation_seal(bound):
    from app.api.app import app
    from app.chat.session_log import SessionLogWriter
    from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError

    before_routes = tuple(app.routes)
    build_semantic_operation_handlers(bound.config)
    assert tuple(app.routes) == before_routes
    assert not any("operations" in str(getattr(route, "path", "")) for route in app.routes)
    original = bound.note.read_bytes()
    request = bound.request(CLASSIFY, {"artifact_class": "evergreen_note"})
    assert bound.run(request).status is OperationStatus.REJECTED
    generic = bound.request(CLASSIFY, {"artifact_class": "evergreen_note"})
    bound.approve(generic, {"artifact_class": "evergreen_note"}, write_class="vault_body_edit")
    assert bound.run(generic).status is OperationStatus.REJECTED
    assert bound.note.read_bytes() == original
    logs = SessionLogWriter(vault_root=bound.owner.root)
    session = logs.open_session(bound.note, "human-present")
    writer = CanvasWriter(bound.owner.root, logs)
    writer.apply_edit(session, "Human body edit.", "Accepted present-session body policy")
    assert "Human body edit." in bound.note.read_text()
    assert bound.metadata()["artifact_class"] == "human_knowledge"
    with pytest.raises(GovernanceBearingMutationError):
        writer.apply_edit(
            session, "---\nartifact_class: evergreen_note\n---\n", "requires semantic approval"
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"artifact_class": "machine_mirror"},
        {"lifecycle": "durable"},
        {"authority": "human"},
        {"artifact_type": "invented"},
    ],
)
def test_classification_cannot_borrow_other_axes_or_invent_vocabulary(bound, fields):
    original = bound.note.read_bytes()
    assert bound.run(bound.request(CLASSIFY, fields)).status is OperationStatus.INVALID
    assert bound.note.read_bytes() == original


def test_explicitly_authored_empty_order_is_valid(bound):
    text = bound.note.read_text()
    start, end = text.index("member_order:"), text.index("trust:")
    bound.note.write_text(text[:start] + "member_order: []\n" + text[end:])
    request = bound.request(arguments={"ordered_ids": []})
    assert (
        bound.run(bound.approve(request, {"member_order": []})).status
        is OperationStatus.CONVERGENCE_PENDING
    )
    assert bound.metadata()["member_order"] == []


def test_unresolved_ambiguous_and_out_of_context_members_are_refused(bound, tmp_path):
    original = bound.note.read_bytes()
    member = bound.owner.root / "Notes/member-0.md"
    raw = member.read_bytes()
    duplicate = bound.owner.root / "Notes/duplicate.md"
    duplicate.write_bytes(raw)
    assert bound.run(bound.request()).status is OperationStatus.INVALID
    duplicate.unlink()
    member.unlink()
    outside = tmp_path / "outside.md"
    outside.write_bytes(raw)
    member.symlink_to(outside)
    assert bound.run(bound.request()).status is OperationStatus.INVALID
    assert bound.note.read_bytes() == original


def test_concurrent_membership_change_conflicts_in_the_real_hka_cas(bound, monkeypatch):
    request = bound.approve(bound.request())
    original_write = semantic.write_note_from_absolute
    concurrent = bound.note.read_bytes().replace(bound.members[0].encode(), str(uuid4()).encode())

    def race(*args, **kwargs):
        bound.note.write_bytes(concurrent)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(semantic, "write_note_from_absolute", race)
    result = bound.run(request)
    assert result.status is OperationStatus.CONFLICTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == concurrent
    record = bound.records()[0]
    assert record["source_receipt"]["outcome"] == "conflict_staged"
    assert record["authority_receipt"]["outcome"] == "failed"
    assert (bound.owner.root / record["source_receipt"]["conflict_artifact"]).exists()


@pytest.mark.parametrize("failure", ["authority", "outbox"])
def test_applied_source_receipt_failures_remain_recoverable_after_restart(
    bound, monkeypatch, failure
):
    request = bound.approve(bound.request())
    if failure == "authority":
        monkeypatch.setattr(
            GovernedWriteAdapter,
            "record_authority_receipt",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("receipt unavailable")),
        )
    else:
        monkeypatch.setattr(semantic, "append_jsonl_outbox_event", lambda *_a, **_k: False)
    result = bound.run(request)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert bound.metadata()["member_order"] == bound.members[::-1]
    source = result.receipt.extensions["write"]["source_receipt"]
    assert source["outcome"] == "written"
    assert bound.run(request).to_dict() == result.to_dict()


def test_receiptless_effect_is_unknown_and_cannot_be_replayed(bound, monkeypatch):
    request = bound.approve(bound.request())
    exchange = adapters._atomic_exchange_at
    calls = []

    def interrupted(*args):
        calls.append(args)
        exchange(*args)
        raise OSError("interrupted after exchange")

    monkeypatch.setattr(adapters, "_atomic_exchange_at", interrupted)
    result = bound.run(request)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.UNKNOWN
    assert bound.run(request).to_dict() == result.to_dict()
    assert len(calls) == 1


def test_authority_is_rechecked_after_hka_wait_before_source_exchange(bound, monkeypatch):
    request = bound.approve(bound.request())
    original = bound.note.read_bytes()
    entered, resume = Event(), Event()
    anchored = adapters._require_anchored_directory_identity
    stopped = False
    clock = SimpleNamespace(time=lambda: 1.0)
    monkeypatch.setattr(context_bound_write, "time", clock)
    expiry = bound.owner.active_context.expires_at or 4102444800.0

    def wait(*args, **kwargs):
        nonlocal stopped
        result = anchored(*args, **kwargs)
        if not stopped:
            stopped = True
            entered.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(adapters, "_require_anchored_directory_identity", wait)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(bound.run, request)
        assert entered.wait(10)
        clock.time = lambda: expiry + 1
        resume.set()
        result = future.result(timeout=10)
    assert result.status is OperationStatus.REJECTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == original
    assert not bound.owner.receipt_path.exists()


def test_selected_sources_zone_and_nested_vault_cannot_borrow_semantic_authority(
    bound, monkeypatch
):
    from app.settings.locations import canonical_settings_root

    settings = canonical_settings_root(bound.owner.root) / "system-settings.md"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("---\npaths:\n  sources_dir_rel: ConfiguredSources\n---\n")
    retained = bound.owner.root / "ConfiguredSources"
    retained.mkdir()
    raw = bound.note.read_bytes()
    bound.note.rename(retained / "collection.md")
    bound.note = retained / "collection.md"
    result = bound.run(bound.request())
    assert result.status is OperationStatus.INVALID
    assert bound.note.read_bytes() == raw and not bound.owner.receipt_path.exists()
    bound.note.rename(bound.owner.root / "Notes/collection.md")
    bound.note = bound.owner.root / "Notes/collection.md"
    member = bound.owner.root / "Notes/member-0.md"
    nested = bound.owner.root / "Nested"
    with monkeypatch.context() as child_patch:
        bind_initialized_vault(child_patch, nested, store_dir=nested.parent / "nested-local")
    member.rename(nested / "member.md")
    assert bound.run(bound.request()).status is OperationStatus.INVALID
    assert bound.note.read_bytes() == raw and not bound.owner.receipt_path.exists()


@pytest.mark.parametrize(
    "source_change", ["duplicate-key", "malformed-yaml", "proposal", "wrong-family"]
)
def test_malformed_or_unaccepted_sources_cannot_gain_human_classification(bound, source_change):
    text = bound.note.read_text()
    if source_change == "duplicate-key":
        text = text.replace("tags: [Research]", "tags: [Research]\ntags: [Other]")
    elif source_change == "malformed-yaml":
        text = text.replace("tags: [Research]", "tags: [Research")
    elif source_change == "proposal":
        text = text.replace("tags: [Research]", "authority_state: proposal\ntags: [Research]")
    else:
        text = text.replace("artifact_class: human_knowledge", "artifact_class: ai_suggestion")
    bound.note.write_text(text)
    original = bound.note.read_bytes()
    request = bound.request(CLASSIFY, {"artifact_class": "evergreen_note"})
    bound.approve(request, {"artifact_class": "evergreen_note"})
    result = bound.run(request)
    assert result.status is OperationStatus.INVALID
    assert bound.note.read_bytes() == original and not bound.owner.receipt_path.exists()


@pytest.mark.parametrize("missing", ["approval", "window"])
def test_semantic_producer_refuses_missing_approval_port_at_construction(bound, missing):
    owner = bound.owner
    with pytest.raises(semantic.KnowledgeCapabilityError, match="authority window ports"):
        KnowledgeSemanticOwner(
            vault_root=owner.root,
            active_context=owner.active_context,
            target_binding_id=owner.target_binding_id,
            registry_store=owner.registry_store,
            authorize_semantic=None if missing == "approval" else owner.authorize_semantic,
            semantic_authority_window=None
            if missing == "window"
            else owner.semantic_authority_window,
            receipt_path=owner.receipt_path,
        )


def test_capability_failure_after_source_effect_remains_unknown(bound, monkeypatch):
    request = bound.approve(bound.request())
    write = semantic.write_note_from_absolute
    calls = []

    def lose_receipt(*args, **kwargs):
        calls.append(1)
        write(*args, **kwargs)
        raise semantic.KnowledgeCapabilityError("source receipt became unavailable")

    monkeypatch.setattr(semantic, "write_note_from_absolute", lose_receipt)
    result = bound.run(request)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is SourceEffectStatus.UNKNOWN
    assert bound.metadata()["member_order"] == bound.members[::-1]
    assert bound.run(request).to_dict() == result.to_dict() and calls == [1]


def test_unrelated_malformed_note_does_not_block_a_healthy_human_source(bound):
    (bound.owner.root / "Notes/unrelated.md").write_text(
        f"---\nuuid: {uuid4()}\nbroken: [yaml\n---\nHuman draft needing repair.\n"
    )
    request = bound.request(CLASSIFY, {"artifact_class": "project_note"})
    result = bound.run(bound.approve(request, {"artifact_class": "project_note"}))
    assert result.status is OperationStatus.CONVERGENCE_PENDING
    assert bound.metadata()["artifact_class"] == "project_note"


@pytest.mark.parametrize("mismatch", ["actor", "context", "target", "missing-version"])
def test_semantic_request_binding_refuses_before_effect(bound, mismatch):
    request = bound.approve(bound.request())
    original = bound.note.read_bytes()
    if mismatch == "actor":
        request = replace(request, provenance=replace(request.provenance, actor="other-human"))
    elif mismatch == "context":
        request = replace(request, context=replace(request.context, vault_generation="different"))
    elif mismatch == "target":
        request = replace(request, targets=({"artifact_id": str(uuid4())},))
    else:
        request = replace(request, expected_version=None)
    assert bound.run(request).status in {OperationStatus.REJECTED, OperationStatus.CONFLICTED}
    assert bound.note.read_bytes() == original and not bound.owner.receipt_path.exists()


def _observe_source_seam(bound, monkeypatch):
    observed = {"calls": 0, "final": False, "exchanges": []}
    require = context_bound_write.require_effect_locator
    exchange = adapters._atomic_exchange_at

    def require_observed(*args, **kwargs):
        observed["calls"] += 1
        observed["final"] = observed["calls"] == 2
        return require(*args, **kwargs)

    def exchange_observed(*args, **kwargs):
        observed["exchanges"].append(time.time())
        return exchange(*args, **kwargs)

    monkeypatch.setattr(context_bound_write, "require_effect_locator", require_observed)
    monkeypatch.setattr(adapters, "_atomic_exchange_at", exchange_observed)
    return observed


def test_expiry_during_approval_window_acquisition_prevents_source_exchange(bound, monkeypatch):
    # Keep the real clock, immutable context, GOV window, actual HKA CAS and
    # approval result. Delay the held approval acquisition past expiry.
    bound.owner.active_context = replace(bound.owner.active_context, expires_at=time.time() + 3)
    observed = _observe_source_seam(bound, monkeypatch)
    waited = []

    def approval(intent, grant):
        remaining = bound.owner.active_context.expires_at - time.time()
        assert remaining > 0, "fixture expired before reaching approval acquisition"
        waited.append(True)
        time.sleep(remaining + 0.03)

    bound.hooks["lookup"] = approval
    before = bound.note.read_bytes()
    result = bound.run(bound.approve(bound.request()))
    assert waited == [True]
    assert result.status is OperationStatus.REJECTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not observed["exchanges"]
    assert not bound.owner.receipt_path.exists()


@pytest.mark.parametrize("revoke", ["approval", "clear", "replace", "invalidate"])
def test_revocation_during_final_member_reads_prevents_source_exchange(bound, monkeypatch, revoke):
    observed = _observe_source_seam(bound, monkeypatch)
    resolve = bound.owner._resolve_many
    revoked = []
    request = bound.approve(bound.request())

    def resolve_with_revocation(identities):
        result = resolve(identities)
        if observed["final"] and identities == set(bound.members):
            if revoke == "approval":
                bound.revoke_approval(request.request_id)
            else:
                bound.change_selection(revoke)
            revoked.append(True)
        return result

    monkeypatch.setattr(bound.owner, "_resolve_many", resolve_with_revocation)
    before = bound.note.read_bytes()
    result = bound.run(request)
    assert revoked == [True]
    assert result.status is OperationStatus.REJECTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not observed["exchanges"]
    assert not bound.owner.receipt_path.exists()


@pytest.mark.parametrize("position", ["first", "last", "merge"])
def test_all_matching_uuid_declarations_are_strictly_validated(bound, position):
    identity, other = bound.members[0], str(uuid4())
    if position == "merge":
        declaration = f"base: &identity {{uuid: {identity}}}\n<<: *identity\nuuid: {other}\n"
    else:
        values = (identity, other) if position == "first" else (other, identity)
        declaration = f"uuid: {values[0]}\nuuid: {values[1]}\n"
    (bound.owner.root / "Notes/ambiguous.md").write_text(
        f"---\n{declaration}artifact_class: human_knowledge\n---\nAmbiguous source.\n"
    )
    before = bound.note.read_bytes()
    result = bound.run(bound.approve(bound.request()))
    assert result.status is OperationStatus.INVALID
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not bound.owner.receipt_path.exists()


def test_context_revocation_during_final_registry_read_prevents_source_exchange(bound, monkeypatch):
    observed = _observe_source_seam(bound, monkeypatch)
    read = bound.owner.registry_store.read_existing
    revoked = []

    def read_then_revoke():
        snapshot = read()
        if observed["final"]:
            bound.change_selection()
            revoked.append(True)
        return snapshot

    monkeypatch.setattr(bound.owner.registry_store, "read_existing", read_then_revoke)
    before = bound.note.read_bytes()
    result = bound.run(bound.approve(bound.request()))
    assert revoked == [True]
    assert result.status is OperationStatus.REJECTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not observed["exchanges"]
    assert not bound.owner.receipt_path.exists()


@pytest.mark.parametrize("change", ["clear", "replace", "invalidate", "approval"])
def test_public_selection_or_approval_change_during_held_lookup_refuses(bound, monkeypatch, change):
    observed = _observe_source_seam(bound, monkeypatch)
    request = bound.approve(bound.request())
    before = bound.note.read_bytes()

    def lookup(intent, grant):
        if change == "approval":
            bound.revoke_approval(request.request_id)
        else:
            bound.change_selection(change)

    bound.hooks["lookup"] = lookup
    result = bound.run(request)
    assert result.status is OperationStatus.REJECTED
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not observed["exchanges"]
    assert not bound.owner.receipt_path.exists()


def test_joint_owner_windows_hold_concurrent_mutations_until_durable_receipts(bound, monkeypatch):
    request = bound.approve(bound.request())
    entered, resume, clearing, revoking = Event(), Event(), Event(), Event()
    exchange = adapters._atomic_exchange_at

    def pause(*args):
        entered.set()
        assert resume.wait(10)
        return exchange(*args)

    def clear():
        clearing.set()
        bound.change_selection()

    def revoke():
        revoking.set()
        bound.revoke_approval(request.request_id)

    monkeypatch.setattr(adapters, "_atomic_exchange_at", pause)
    with ThreadPoolExecutor(max_workers=3) as pool:
        effect = pool.submit(bound.run, request)
        assert entered.wait(10)
        clear_future, revoke_future = pool.submit(clear), pool.submit(revoke)
        assert clearing.wait(10) and revoking.wait(10)
        assert not clear_future.done() and not revoke_future.done()
        resume.set()
        result = effect.result(timeout=10)
        clear_future.result(timeout=10)
        revoke_future.result(timeout=10)
    assert result.status is OperationStatus.CONVERGENCE_PENDING
    assert result.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert len(bound.records()) == 1
    assert bound.records()[0]["authority_receipt"]["outcome"] == "applied"
    assert not bound.selection_current() and request.request_id not in bound.approvals
    # Current revocation cannot erase the original historical outcome.
    assert bound.run(request).to_dict() == result.to_dict()


@pytest.mark.parametrize("receipt_known", [True, False])
def test_window_exit_failure_preserves_prior_effect_truth(bound, monkeypatch, receipt_known):
    request = bound.approve(bound.request())
    bound.hooks["exit_error"] = ContextSelectionError("window release failed")
    if not receipt_known:
        exchange = adapters._atomic_exchange_at

        def lose_receipt(*args):
            exchange(*args)
            raise OSError("interrupted after exchange")

        monkeypatch.setattr(adapters, "_atomic_exchange_at", lose_receipt)
    result = bound.run(request)
    assert result.status is OperationStatus.RECOVERY_REQUIRED
    assert result.convergence.source_effect is (
        SourceEffectStatus.COMMITTED if receipt_known else SourceEffectStatus.UNKNOWN
    )
    if receipt_known:
        assert result.receipt.extensions["write"]["source_receipt"]["outcome"] == "written"
        assert result.receipt.extensions["write"]["authority_receipt"]["outcome"] == "applied"
    assert bound.run(request).to_dict() == result.to_dict()


@pytest.mark.parametrize(
    "shape",
    [
        "escaped",
        "escaped-key",
        "duplicate",
        "merge",
        "alias",
        "flow",
        "pending-uuid",
        "pending-nested-uuid",
        "pending-merge",
        "pending-merge-list",
    ],
)
def test_decoded_matching_uuid_survives_later_malformed_yaml(bound, shape):
    identity = bound.members[0]
    escaped = '"' + "".join(f"\\u{ord(char):04x}" for char in identity) + '"'
    definitions = {
        "escaped": f"uuid: {escaped}\nbroken: [yaml\n",
        "escaped-key": f'"\\u0075uid": {escaped}\nbroken: [yaml\n',
        "duplicate": f"uuid: {escaped}\nuuid: {uuid4()}\nbroken: [yaml\n",
        "merge": f"base: &base {{uuid: {escaped}}}\n<<: *base\nbroken: [yaml\n",
        "alias": f"identity: &identity {escaped}\nuuid: *identity\nbroken: [yaml\n",
        "flow": f"{{uuid: {escaped}, broken: [yaml\n",
        "pending-uuid": f"uuid: [{escaped}, [broken\n",
        "pending-nested-uuid": f"uuid: [[{escaped}, [broken\n",
        "pending-merge": f"<<: {{uuid: {escaped}, broken: [yaml\n",
        "pending-merge-list": f"<<: [{{uuid: {escaped}, broken: [yaml\n",
    }
    (bound.owner.root / "Notes/malformed.md").write_text(
        f"---\n{definitions[shape]}---\nMalformed relevant identity.\n"
    )
    before = bound.note.read_bytes()
    result = bound.run(bound.approve(bound.request()))
    assert result.status is OperationStatus.INVALID
    assert result.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    assert bound.note.read_bytes() == before and not bound.owner.receipt_path.exists()


@pytest.mark.parametrize("field", ["summary", "nested"])
def test_decoded_uuid_in_unrelated_malformed_field_is_not_identity(bound, field):
    identity = bound.members[0]
    escaped = '"' + "".join(f"\\u{ord(char):04x}" for char in identity) + '"'
    reference = f"summary: {escaped}" if field == "summary" else f"example: {{uuid: {escaped}}}"
    (bound.owner.root / "Notes/unrelated.md").write_text(
        f"---\nuuid: {uuid4()}\n{reference}\nbroken: [yaml\n---\nUnrelated draft.\n"
    )
    request = bound.approve(bound.request())
    assert bound.run(request).status is OperationStatus.CONVERGENCE_PENDING
    assert bound.metadata()["member_order"] == bound.members[::-1]
