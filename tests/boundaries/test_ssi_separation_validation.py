"""
Cross-surface behavioral tests proving scope, sphere_memberships, and situated_identity
stay distinct across runtime payload, status surface, and receipt/event metadata.

Implements: docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md :: SSI-04
"""
from __future__ import annotations

from app.context_dimensions import ContextDimensions
from app.events.schema import make_outbox_event
from app.observability.status_model import ContextDimensionsStatus
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep


class _CaptureExecutor:
    def __init__(self) -> None:
        self.contexts: list = []

    def execute_step(self, step, context):
        self.contexts.append(context)
        return {"ok": True}


def _make_plan(plan_id: str, context: dict) -> Plan:
    return Plan(
        id=plan_id,
        meta=PlanMetadata(
            goal="ssi-test",
            source_object_uuid="obj-ssi",
            created_by="test",
            trace_id=f"trace-{plan_id}",
        ),
        steps=[PlanStep(id="step-1", kind="note", description="noop")],
        context=context,
    )


def _event(scope: str, spheres: list[str], identity: str | None) -> dict:
    event = make_outbox_event(
        "test.event",
        source="test",
        context_dimensions={
            "scope": scope,
            "sphere_memberships": spheres,
            "situated_identity": identity,
        },
    )
    assert event.context_dimensions is not None
    return event.context_dimensions


def test_scope_only_change_isolation() -> None:
    """Scenario Class 1: only scope changes; sphere_memberships and situated_identity are unaffected."""
    executor = _CaptureExecutor()
    orch = Orchestrator(executor=executor)

    ctx1 = {"scope": "work", "sphere_memberships": ["work"], "situated_identity": "professional"}
    ctx2 = {"scope": "writing", "sphere_memberships": ["work"], "situated_identity": "professional"}

    orch.run_plan(_make_plan("plan-sc1a", ctx1))
    orch.run_plan(_make_plan("plan-sc1b", ctx2))

    step1, step2 = executor.contexts

    # Runtime payload: scope changes, others are stable
    assert step1.scope == "work"
    assert step2.scope == "writing"
    assert step1.sphere_memberships == step2.sphere_memberships == ["work"]
    assert step1.situated_identity == step2.situated_identity == "professional"

    # Receipt/event metadata surface
    dims1 = _event("work", ["work"], "professional")
    dims2 = _event("writing", ["work"], "professional")
    assert dims1["scope"] == "work"
    assert dims2["scope"] == "writing"
    assert dims1["sphere_memberships"] == dims2["sphere_memberships"] == ["work"]
    assert dims1["situated_identity"] == dims2["situated_identity"] == "professional"

    # Status surface
    status1 = ContextDimensionsStatus(scope="work", sphere_memberships=["work"], situated_identity="professional")
    status2 = ContextDimensionsStatus(scope="writing", sphere_memberships=["work"], situated_identity="professional")
    assert status1.scope != status2.scope
    assert status1.sphere_memberships == status2.sphere_memberships
    assert status1.situated_identity == status2.situated_identity


def test_sphere_only_change_isolation() -> None:
    """Scenario Class 2: only sphere_memberships changes; scope and situated_identity are unaffected.
    Also asserts no legacy single-key domain/context merge appears."""
    executor = _CaptureExecutor()
    orch = Orchestrator(executor=executor)

    ctx1 = {"scope": "work", "sphere_memberships": ["work"], "situated_identity": "professional"}
    ctx2 = {"scope": "work", "sphere_memberships": ["work", "learning"], "situated_identity": "professional"}

    orch.run_plan(_make_plan("plan-sc2a", ctx1))
    orch.run_plan(_make_plan("plan-sc2b", ctx2))

    step1, step2 = executor.contexts

    # Runtime payload: sphere changes, scope and identity are stable
    assert step1.scope == step2.scope == "work"
    assert step1.sphere_memberships == ["work"]
    assert step2.sphere_memberships == ["work", "learning"]
    assert step1.situated_identity == step2.situated_identity == "professional"

    # Receipt surface: no legacy collapse into a single domain key
    dims1 = _event("work", ["work"], "professional")
    dims2 = _event("work", ["work", "learning"], "professional")
    assert "domain" not in dims1
    assert "domain" not in dims2
    assert "context" not in dims1
    assert "context" not in dims2
    assert dims1["scope"] == dims2["scope"] == "work"
    assert dims1["sphere_memberships"] == ["work"]
    assert dims2["sphere_memberships"] == ["work", "learning"]
    assert dims1["situated_identity"] == dims2["situated_identity"] == "professional"

    # Status surface
    status1 = ContextDimensionsStatus(scope="work", sphere_memberships=["work"], situated_identity="professional")
    status2 = ContextDimensionsStatus(scope="work", sphere_memberships=["work", "learning"], situated_identity="professional")
    assert status1.scope == status2.scope
    assert status1.sphere_memberships != status2.sphere_memberships
    assert status1.situated_identity == status2.situated_identity


def test_identity_only_change_isolation() -> None:
    """Scenario Class 3: situated_identity changes to null; scope and sphere_memberships are unaffected.
    null must appear explicitly in status and receipts — not omitted (SSI-01 Invariant 5)."""
    executor = _CaptureExecutor()
    orch = Orchestrator(executor=executor)

    ctx1 = {"scope": "work", "sphere_memberships": ["work"], "situated_identity": "professional"}
    ctx2 = {"scope": "work", "sphere_memberships": ["work"], "situated_identity": None}

    orch.run_plan(_make_plan("plan-sc3a", ctx1))
    orch.run_plan(_make_plan("plan-sc3b", ctx2))

    step1, step2 = executor.contexts

    # Runtime payload: identity changes, scope and sphere are stable
    assert step1.scope == step2.scope == "work"
    assert step1.sphere_memberships == step2.sphere_memberships == ["work"]
    assert step1.situated_identity == "professional"
    assert step2.situated_identity is None
    # null must not cause runtime to substitute a scope value (SSI-01 Invariant 5)
    assert step2.situated_identity != step2.scope

    # Receipt surface: situated_identity key present even when null
    dims2 = _event("work", ["work"], None)
    assert "situated_identity" in dims2
    assert dims2["situated_identity"] is None
    assert dims2["scope"] == "work"
    assert dims2["sphere_memberships"] == ["work"]

    # Status surface: situated_identity present and null, not omitted
    status2 = ContextDimensionsStatus(scope="work", sphere_memberships=["work"], situated_identity=None)
    dumped = status2.model_dump()
    assert "situated_identity" in dumped
    assert dumped["situated_identity"] is None
    assert dumped["scope"] == "work"
    assert dumped["sphere_memberships"] == ["work"]


def test_no_collapse_failure_signatures() -> None:
    """Collapse failure signatures: no domain/context merge, no scope_glob, single scope, multi-valued sphere."""
    dims = ContextDimensions(scope="work", sphere_memberships=["work", "learning"], situated_identity="maker")
    dumped = dims.model_dump()

    # No legacy single-key collapse
    assert "domain" not in dumped
    assert "context" not in dumped
    assert "scope_glob" not in dumped

    # scope is single-valued per invocation (str, not list)
    assert isinstance(dumped["scope"], str)

    # sphere_memberships is always a list (multi-valued semantics)
    assert isinstance(dumped["sphere_memberships"], list)
    assert len(dumped["sphere_memberships"]) > 1

    # Receipt: same collapse checks on the wire format
    event = make_outbox_event(
        "test.collapse.check",
        source="test",
        context_dimensions=dumped,
    )
    wire = event.context_dimensions
    assert wire is not None
    assert "domain" not in wire
    assert "context" not in wire
    assert "scope_glob" not in wire
    assert isinstance(wire["scope"], str)
    assert isinstance(wire["sphere_memberships"], list)

    # Status model: same checks
    status = ContextDimensionsStatus(
        scope="work",
        sphere_memberships=["work", "learning"],
        situated_identity="maker",
    )
    status_dumped = status.model_dump()
    assert "domain" not in status_dumped
    assert "context" not in status_dumped
    assert isinstance(status_dumped["scope"], str)
    assert isinstance(status_dumped["sphere_memberships"], list)
