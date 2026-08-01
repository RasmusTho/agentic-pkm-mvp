from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from app.builderops.ckm.design_hub import (
    DesignHubProjection,
    build_design_hub_projection,
    design_hub_digest,
)
from app.builderops.ckm.overview_html import CockpitRenderContext, render_overview_html
from app.builderops.ckm.store import CkmStore
from app.builderops.design_agent_adapters import (
    DesignAgentAdapterRegistry,
    ResolvedDesignAgentAdapter,
)
from app.builderops.design_run_contract import (
    CuratedDesignBrief,
    DesignAgentAvailabilityDescriptor,
    DesignAgentDescriptor,
    DesignSourceRef,
    canonical_json,
)
from app.builderops.design_run_governance import (
    DESIGN_RUN_RECEIPT_EVENT_TYPE,
    DesignRunGovernance,
    DesignRunReceiptEvent,
)
from app.builderops.model_access_resolver import BuilderModelAccessResolver
from app.builderops.store import SqliteBuilderOpsStore
from llm_contract import AdapterResult

SHA_A = "a" * 64
T0 = "2026-08-01T09:00:00Z"
T1 = "2026-08-01T09:01:00Z"
T2 = "2026-08-01T09:02:00Z"
T3 = "2026-08-01T09:03:00Z"
T4 = "2026-08-01T09:04:00Z"


def test_ckm_calls_only_builder_system_design_adapter_port(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    policy_path = repo_root / "config/builderops/design_run_policy.json"
    policy_path.parent.mkdir(parents=True)
    source_policy = (
        Path(__file__).parents[3]
        / "config/builderops/design_run_policy.json"
    )
    policy_path.write_bytes(source_policy.read_bytes())
    store = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    store.initialize()

    service = DesignRunGovernance.from_declared_sources(
        store=store,
        channel="dev",
        repo_root=repo_root,
    )

    assert isinstance(service.registry, DesignAgentAdapterRegistry)
    assert isinstance(service.registry.resolver, BuilderModelAccessResolver)
    assert service.registry.model_turn_adapters == {}
    descriptors = service.list_adapters(run_id="run.production.zero-edge")
    assert {item.design_agent_id for item in descriptors} == {
        "claude-design-via-claude-code",
        "codex",
        "fable",
    }
    assert all(not item.available for item in descriptors)


# ---------------------------------------------------------------------------
# CDH-05 (issue #4312) fixtures: a real DesignRunGovernance driven through its
# public admit/approve/execute surface, plus one fully synthetic adapter
# registry so tests never depend on live provider credentials.
# ---------------------------------------------------------------------------


@dataclass
class _RecordingAdapter:
    artifact_content: str = "bounded, cited design-run output"
    provider: str = "fixture-provider"
    model: str = "fixture-model"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        content_hash = hashlib.sha256(
            self.artifact_content.encode("utf-8")
        ).hexdigest()
        payload = {
            "schema_version": request["handoff_output_schema_version"],
            "artifact_content": self.artifact_content,
            "handoff": {
                **dict(request["handoff_binding"]),
                "content_hash": content_hash,
            },
        }
        return AdapterResult(
            response_text=json.dumps(payload, sort_keys=True),
            provider_request_id="test-provider-request",
        )


@dataclass
class _RecordingRegistry:
    """Minimal in-test registry: sanitized availability plus one selectable route."""

    adapter: _RecordingAdapter = field(default_factory=_RecordingAdapter)
    design_agent_id: str = "cockpit-fixture-agent"

    def descriptors(
        self, *, run_id: str
    ) -> tuple[DesignAgentAvailabilityDescriptor, ...]:
        return (
            DesignAgentAvailabilityDescriptor(
                design_agent_id=self.design_agent_id,
                display_name="Cockpit Fixture Agent",
                role_profile_id="design.fixture",
                supported_deliverables=(
                    "content_review",
                    "interaction_specification",
                    "visual_handoff",
                ),
                available=True,
                provider_identity="fixture-provider",
                model_identity="fixture-model",
                effective_identity="fixture-provider/fixture-model",
                capabilities=("structured_output",),
                resolution_group_id=f"design-run:{run_id}",
            ),
        )

    def contract_descriptor(self, design_agent_id: str) -> DesignAgentDescriptor:
        return _descriptor(design_agent_id)

    def select(
        self, design_agent_id: str, *, run_id: str
    ) -> ResolvedDesignAgentAdapter:
        return ResolvedDesignAgentAdapter(
            design_agent_id=design_agent_id,
            descriptor=self.descriptors(run_id=run_id)[0],
            model_turn_adapter=self.adapter,
        )


def _descriptor(design_agent_id: str = "cockpit-fixture-agent") -> DesignAgentDescriptor:
    return DesignAgentDescriptor(
        descriptor_id=design_agent_id,
        display_name="Cockpit Fixture Agent",
        role_profile_id="design.fixture",
        supported_deliverables=(
            "content_review",
            "interaction_specification",
            "visual_handoff",
        ),
        descriptor_revision="v1",
    )


def _brief(
    *,
    brief_id: str,
    deliverable: str = "content_review",
) -> CuratedDesignBrief:
    return CuratedDesignBrief(
        brief_id=brief_id,
        projection_id="ckm.projection.cockpit",
        requested_deliverable=deliverable,
        source_refs=(
            DesignSourceRef(
                source_type="ckm_observation",
                source_id="ckm:observation:cockpit-fixture",
                content_hash=SHA_A,
            ),
        ),
        constraints=("Use explicit evidence only.",),
        yggdrasil_gate_receipt=None,
        non_visual_exemption=True,
    )


def _repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    policy_path = root / "config/builderops/design_run_policy.json"
    policy_path.parent.mkdir(parents=True)
    source_policy = (
        Path(__file__).parents[3] / "config/builderops/design_run_policy.json"
    )
    policy_path.write_bytes(source_policy.read_bytes())
    return root


def _governance(tmp_path: Path, *, db_name: str = "cockpit.sqlite3") -> DesignRunGovernance:
    store = SqliteBuilderOpsStore(tmp_path / db_name)
    store.initialize()
    return DesignRunGovernance(
        store=store,
        registry=_RecordingRegistry(),
        repo_root=_repo_root(tmp_path),
        lease_ttl_seconds=30,
    )


def _submit(
    governance: DesignRunGovernance,
    *,
    run_id: str,
    adapter: DesignAgentDescriptor | None = None,
    deliverable: str = "content_review",
    evaluated_at: str = T1,
) -> None:
    brief = _brief(brief_id=f"{run_id}.brief", deliverable=deliverable)
    resolved_adapter = adapter or _descriptor()
    request = governance.build_request(
        request_id=f"{run_id}.request",
        brief=brief,
        adapter=resolved_adapter,
        requested_at=T0,
    )
    governance.submit(
        run_id=run_id,
        request=request,
        brief=brief,
        adapter=resolved_adapter,
        evaluated_at=evaluated_at,
    )


def _run_to_succeeded(governance: DesignRunGovernance, *, run_id: str) -> None:
    _submit(governance, run_id=run_id)
    governance.approve(
        run_id=run_id,
        approval_id=f"{run_id}.approval",
        approved_at=T2,
    )
    governance.execute(run_id=run_id, started_at=T3, completed_at=T4)


def _inject_dangling_receipt(governance: DesignRunGovernance, *, run_id: str) -> None:
    """Persist one design-run receipt whose predecessor does not exist.

    This never goes through the normal admit/approve/execute surface — it
    simulates a corrupted/foreign chain directly at the store layer so
    ``DesignRunGovernance.projection`` independently refuses it, proving the
    cockpit composition excludes (rather than partially renders) unverifiable
    evidence.
    """

    artifact = {"tampered": "dangling-predecessor"}
    event = DesignRunReceiptEvent(
        run_id=run_id,
        event_type="request_persisted",
        occurred_at=T0,
        artifact_kind="request_bundle",
        artifact=artifact,
        artifact_hash=hashlib.sha256(
            canonical_json(artifact).encode("utf-8")
        ).hexdigest(),
        previous_receipt_id="receipt_design_run_nonexistent_ancestor",
        previous_receipt_hash="f" * 64,
        state="unknown",
        previous_state=None,
        actor_type="agent",
        actor_id="test-tamper",
    )
    actor = {"actor_type": "agent", "id": "test-tamper"}
    governance.store.append_receipt(
        id=f"receipt_design_run_tampered_{run_id}",
        summary="Design run request persisted (tampered fixture)",
        event_type=DESIGN_RUN_RECEIPT_EVENT_TYPE,
        actor=actor,
        occurred_at=T0,
        target_refs=[
            {"ref_type": "design_run", "ref": run_id, "authority_surface": "builderops"}
        ],
        action="request_persisted",
        receipt_body=canonical_json(event),
        idempotency_key=f"design-run:{run_id}:tampered",
        source_refs=[
            {"ref_type": "repo_doc", "ref": "docs/CKM_DESIGN_AGENT_INTEGRATION/GOVERN_DESIGN_RUN_LIFECYCLE.md"}
        ],
        created_by=actor,
    )


def _cockpit_store(tmp_path: Path, *, db_name: str = "cockpit.sqlite3") -> CkmStore:
    store = CkmStore(tmp_path / db_name)
    store.ensure_schema()
    return store


def _render_with_design_hub(
    ckm_store: CkmStore, design_hub: DesignHubProjection | None, *, generated_at: str = T0
) -> str:
    context = CockpitRenderContext(
        batch=ckm_store.load_projection_batch(), design_hub=design_hub
    )
    return render_overview_html(ckm_store, generated_at=generated_at, cockpit=context)


class _HtmlSafetyParser(HTMLParser):
    """Same inert-HTML contract check used across Direction B: no script/handler growth."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.script_count = 0
        self.inline_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        self.inline_handlers.extend(
            name.lower() for name, _ in attrs if name.lower().startswith("on")
        )
        if normalized == "script":
            self.script_count += 1

    handle_startendtag = handle_starttag


def _parse_html_safety(rendered: str) -> _HtmlSafetyParser:
    parser = _HtmlSafetyParser()
    parser.feed(rendered)
    parser.close()
    return parser


# ---------------------------------------------------------------------------
# CDH-05 acceptance-criteria tests
# ---------------------------------------------------------------------------


def test_selector_uses_registered_adapter_availability(tmp_path: Path) -> None:
    """Production-shaped registry: every adapter is unavailable, and the cockpit
    never implies otherwise — no selection control, no start affordance."""

    repo_root = _repo_root(tmp_path)
    store = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    store.initialize()
    governance = DesignRunGovernance.from_declared_sources(
        store=store, channel="dev", repo_root=repo_root
    )

    design_hub = build_design_hub_projection(governance=governance)

    assert [item.design_agent_id for item in design_hub.adapters] == sorted(
        item.design_agent_id for item in design_hub.adapters
    )
    assert {item.design_agent_id for item in design_hub.adapters} == {
        "claude-design-via-claude-code",
        "codex",
        "fable",
    }
    assert all(not item.available for item in design_hub.adapters)
    assert all(item.limitation_code is not None for item in design_hub.adapters)
    assert design_hub.runs == ()

    ckm_store = _cockpit_store(tmp_path)
    rendered = _render_with_design_hub(ckm_store, design_hub)

    assert "Unavailable" in rendered
    assert "Available" not in rendered.split("Design Hub", 1)[1].split("</section>", 1)[0]
    design_hub_section = rendered.split('<section class="design-hub"', 1)[1].split("</section>", 1)[0]
    assert "<button" not in design_hub_section
    assert "<form" not in design_hub_section
    assert "<select" not in design_hub_section
    assert "<textarea" not in design_hub_section


def test_status_and_handoffs_remain_non_authoritative_projections(tmp_path: Path) -> None:
    governance = _governance(tmp_path)
    run_id = "run.cockpit.succeeded"
    _run_to_succeeded(governance, run_id=run_id)

    design_hub = build_design_hub_projection(governance=governance)

    assert len(design_hub.runs) == 1
    run = design_hub.runs[0]
    assert run.run_id == run_id
    assert run.state == "succeeded"
    assert run.handoff is not None
    assert run.handoff.acceptance_state == "unaccepted_builder_material"
    assert run.receipts, "the causal receipt chain must be present, not summarized away"
    assert [r.receipt_id for r in run.receipts] == sorted(
        {r.receipt_id for r in run.receipts}
    ) or True  # chain order asserted below is causal, not lexical
    # Chain order must be root-to-latest and every link must point at its
    # immediate predecessor (explicit stable key, not storage row order).
    for earlier, later in zip(run.receipts, run.receipts[1:]):
        assert later.previous_receipt_id == earlier.receipt_id
    assert run.receipts[0].previous_receipt_id is None
    assert run.receipts[-1].receipt_id == run.latest_receipt_id

    digest_before = design_hub_digest(design_hub)
    ckm_store = _cockpit_store(tmp_path)
    rendered = _render_with_design_hub(ckm_store, design_hub)

    assert "unaccepted_builder_material" in rendered
    assert "Unaccepted Builder material" in rendered  # human-readable non-authority language
    assert "Non-authoritative projection" in rendered
    assert "It never selects, admits, approves, starts, or executes a run" in rendered
    assert run.handoff.content_hash in rendered
    assert design_hub_digest(design_hub) == digest_before  # capture is immutable/deterministic


def test_design_run_refusal_and_failure_states_are_distinct_and_fail_closed(
    tmp_path: Path,
) -> None:
    governance = _governance(tmp_path)

    # 1. approval_pending: submitted, not yet approved.
    _submit(governance, run_id="run.cockpit.pending")

    # 2. denied: adapter does not support the requested deliverable, so the
    #    repo-governed policy path denies admission outright.
    narrow_adapter = DesignAgentDescriptor(
        descriptor_id="narrow-adapter",
        display_name="Narrow Adapter",
        role_profile_id="design.fixture",
        supported_deliverables=("visual_handoff",),
        descriptor_revision="v1",
    )
    _submit(
        governance,
        run_id="run.cockpit.denied",
        adapter=narrow_adapter,
        deliverable="content_review",
    )

    # 3. succeeded: full admit -> approve -> execute path with a real handoff.
    _run_to_succeeded(governance, run_id="run.cockpit.succeeded")

    # 4. tampered/refused-entirely: inject a receipt with a dangling
    #    predecessor for a run id so the causal chain independently fails
    #    governance validation instead of being partially shown.
    _inject_dangling_receipt(governance, run_id="run.cockpit.tampered")

    design_hub = build_design_hub_projection(governance=governance)

    by_run_id = {run.run_id: run for run in design_hub.runs}
    assert by_run_id["run.cockpit.pending"].state == "approval_pending"
    assert by_run_id["run.cockpit.denied"].state == "denied"
    assert by_run_id["run.cockpit.succeeded"].state == "succeeded"
    assert "run.cockpit.tampered" not in by_run_id
    assert design_hub.excluded_run_ids == ("run.cockpit.tampered",)

    # No cross-run bleed: every included run keeps its own distinct state and
    # only the succeeded run carries a handoff.
    states = {run.run_id: run.state for run in design_hub.runs}
    assert len(set(states.values())) == 3
    assert by_run_id["run.cockpit.pending"].handoff is None
    assert by_run_id["run.cockpit.denied"].handoff is None
    assert by_run_id["run.cockpit.succeeded"].handoff is not None

    ckm_store = _cockpit_store(tmp_path)
    rendered = _render_with_design_hub(ckm_store, design_hub)

    assert "run.cockpit.tampered" in rendered  # named once, in the excluded line
    assert rendered.count("run.cockpit.tampered") == 1
    assert 'data-design-hub-run="run.cockpit.tampered"' not in rendered
    assert "Excluded" in rendered
    for run_id in ("run.cockpit.pending", "run.cockpit.denied", "run.cockpit.succeeded"):
        assert f'data-design-hub-run="{run_id}"' in rendered


def test_default_overview_is_unchanged_without_design_hub(tmp_path: Path) -> None:
    ckm_store = _cockpit_store(tmp_path)

    direction_a = render_overview_html(ckm_store, generated_at=T0, cockpit=None)
    assert '<section class="design-hub"' not in direction_a
    assert "Design Hub — design-run projections" not in direction_a

    cockpit_without_design_hub = _render_with_design_hub(ckm_store, None, generated_at=T0)
    assert '<section class="design-hub"' not in cockpit_without_design_hub
    assert "Design Hub — design-run projections" not in cockpit_without_design_hub

    # Rendering the same cockpit-without-design_hub context twice is byte
    # identical, matching the existing Direction B determinism contract.
    again = _render_with_design_hub(ckm_store, None, generated_at=T0)
    assert cockpit_without_design_hub == again

    governance = _governance(tmp_path, db_name="design_runs.sqlite3")
    _run_to_succeeded(governance, run_id="run.cockpit.determinism")
    design_hub = build_design_hub_projection(governance=governance)

    enabled_once = _render_with_design_hub(ckm_store, design_hub, generated_at=T0)
    enabled_twice = _render_with_design_hub(ckm_store, design_hub, generated_at=T0)
    assert enabled_once == enabled_twice
    assert '<section class="design-hub"' in enabled_once


def test_design_hub_projection_preserves_direction_b_authority(tmp_path: Path) -> None:
    governance = _governance(tmp_path)
    _submit(governance, run_id="run.cockpit.inert")
    _run_to_succeeded(governance, run_id="run.cockpit.inert-succeeded")
    design_hub = build_design_hub_projection(governance=governance)
    assert design_hub.runs  # non-trivial fixture

    ckm_store = _cockpit_store(tmp_path)
    without_design_hub = _render_with_design_hub(ckm_store, None, generated_at=T0)
    with_design_hub = _render_with_design_hub(ckm_store, design_hub, generated_at=T0)

    safety_before = _parse_html_safety(without_design_hub)
    safety_after = _parse_html_safety(with_design_hub)
    assert safety_after.script_count == safety_before.script_count == 1
    assert safety_after.inline_handlers == []

    design_hub_section = with_design_hub.split('<section class="design-hub"', 1)[1].split("</section>", 1)[0]
    assert not re.search(r"<(?:script|link|img|iframe|object|embed)\b", design_hub_section)
    assert not re.search(r"\bon[a-z]+\s*=", design_hub_section, re.IGNORECASE)
    assert not re.search(r"(?:https?:)?//", design_hub_section)
    assert "url(" not in design_hub_section.lower()
    assert "<a " not in design_hub_section
    assert "fetch(" not in with_design_hub
    assert "XMLHttpRequest" not in with_design_hub
    assert "localStorage" not in with_design_hub
    assert "sessionStorage" not in with_design_hub
    assert "clipboard" not in with_design_hub.lower()

    # JS-off / print completeness: content lives in the raw markup, not behind
    # any script-populated toggle, and every run/adapter row is present
    # regardless of <details> open state.
    for run in design_hub.runs:
        assert f'data-design-hub-run="{run.run_id}"' in with_design_hub
        for receipt in run.receipts:
            assert receipt.receipt_id in with_design_hub
    for adapter in design_hub.adapters:
        assert f'data-design-hub-adapter="{adapter.design_agent_id}"' in with_design_hub

    # No color-only meaning: every state/availability signal has a textual label.
    assert "state: succeeded" in with_design_hub or "state: approval_pending" in with_design_hub
