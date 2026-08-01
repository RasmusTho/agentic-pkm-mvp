"""CDH-06 (issue #4313): production-path acceptance matrix for the Design Hub.

`docs/CKM_DESIGN_AGENT_INTEGRATION/VALIDATE_DESIGN_HUB_END_TO_END.md ::
Acceptance Criteria` requires proof on the *composition* path, not on isolated
unit fixtures. These tests therefore drive the real
:class:`~app.builderops.design_run_governance.DesignRunGovernance`, the real
:class:`~app.builderops.design_agent_adapters.DesignAgentAdapterRegistry`, the
real repo-governed policy and Yggdrasil token files, the real SQLite BuilderOps
receipt store, and the real cockpit renderer.

Exactly one seam is doubled: the neutral ADR-0064 ``ModelAccessResolver`` port
and the ``ModelTurnAdapter`` behind it. That is deliberate and is itself part of
the contract being proven. The shipped production posture has **no**
``builderops-design-run`` credential grant: `codex` and `fable` resolve to
``model_access_unavailable`` without reading any credential, and
`claude-design-via-claude-code` is ``interactive_subscription_only`` and can
never be headless-available (INV-CDH-5A). Provisioning a provider to obtain a
"real" success would change the production posture under test, so the governed
success path is proven through the declared substrate seam while every refusal
path is proven against the genuinely dormant production registry.

Every case asserts the exact number of provider turns. Refusal cases assert
zero, governed execution asserts exactly one, and no case ever falls through to
a second adapter (INV-CDH-5).
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest
from click.testing import CliRunner

from app.builderops.ckm.design_hub import (
    build_design_hub_projection,
    design_hub_digest,
)
from app.builderops.ckm.overview_html import CockpitRenderContext, render_overview_html
from app.builderops.ckm.store import CkmStore
from app.builderops.cli import builderops
from app.builderops.design_agent_adapters import (
    DESIGN_AGENT_IDS,
    DESIGN_AGENT_ROLE_PROFILES,
    DesignAgentAdapterRegistry,
    UnknownDesignAgentError,
)
from app.builderops.design_run_contract import (
    CuratedDesignBrief,
    DesignSourceRef,
    DigestBoundAttachmentRef,
    YggdrasilGateReceipt,
)
from app.builderops.design_run_governance import (
    DESIGN_RUN_POLICY_PATH,
    DESIGN_RUN_RECEIPT_EVENT_TYPE,
    DesignRunApprovalRequiredError,
    DesignRunGovernance,
    DesignRunGovernanceError,
    DesignRunUnavailableError,
    load_design_run_policy,
)
from app.builderops.model_access_resolver import ModelAccessResolutionError
from app.builderops.store import SqliteBuilderOpsStore
from llm_contract import (
    AdapterResult,
    ModelCapabilities,
    ModelResolutionRequest,
    ResolvedModelAccess,
    validate_resolved_group,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
YGGDRASIL_TOKEN_SOURCE = "companion-ui/companion-app/colors_and_type.css"

SHA_A = "a" * 64
SHA_B = "b" * 64

T0 = "2026-08-01T09:00:00Z"
T1 = "2026-08-01T09:01:00Z"
T2 = "2026-08-01T09:02:00Z"
T3 = "2026-08-01T09:03:00Z"
T4 = "2026-08-01T09:04:00Z"

# The three registered domain adapters and the substrate target each resolves
# to. `claude-design-via-claude-code` is included on purpose: the matrix must
# prove it is refused rather than silently omitted.
SUBSTRATE_TARGETS: dict[str, tuple[str, str]] = {
    "design.codex": ("openai", "gpt-5.6-sol"),
    "design.claude": ("anthropic", "claude-fable-5"),
    "design.fable": ("anthropic", "claude-fable-5"),
}
HEADLESS_CAPABLE_AGENT_IDS = ("codex", "fable")
INTERACTIVE_ONLY_AGENT_IDS = ("claude-design-via-claude-code",)


# ---------------------------------------------------------------------------
# Test doubles limited to the one declared substrate seam.
# ---------------------------------------------------------------------------


class _TimeoutSentinel(Exception):
    """Marker so a timeout double cannot be confused with a generic failure."""


@dataclass
class _CountingAdapter:
    """Neutral ``ModelTurnAdapter`` that records every provider turn.

    ``mode`` selects the terminal behaviour under test. It never reads a
    credential, never opens a socket, and never spawns a process.
    """

    adapter_id: str
    provider: str
    model: str
    mode: Literal[
        "success",
        "timeout",
        "failure",
        "malformed_output",
        "foreign_binding",
    ] = "success"
    artifact_content: str = "bounded, cited design-run output"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        if self.mode == "timeout":
            raise TimeoutError("design agent did not answer in time")
        if self.mode == "failure":
            raise _TimeoutSentinel("design agent transport failed")
        if self.mode == "foreign_binding":
            # A correctly digested artifact whose handoff binds a *different*
            # run and evidence set. The digest alone is not enough: the handoff
            # must bind the exact run it was started for.
            content_hash = hashlib.sha256(
                self.artifact_content.encode("utf-8")
            ).hexdigest()
            binding = dict(request["handoff_binding"])
            binding["run_id"] = "run.acceptance.foreign"
            binding["handoff_id"] = "run.acceptance.foreign.handoff"
            binding["source_refs"] = [
                DesignSourceRef(
                    source_type="ckm_observation",
                    source_id="ckm:observation:foreign",
                    content_hash=SHA_B,
                ).model_dump(mode="json")
            ]
            payload = {
                "schema_version": request["handoff_output_schema_version"],
                "artifact_content": self.artifact_content,
                "handoff": {**binding, "content_hash": content_hash},
            }
            return AdapterResult(
                response_text=json.dumps(payload, sort_keys=True),
                provider_request_id="not-persisted",
            )
        if self.mode == "malformed_output":
            # Structurally parseable but the digest does not bind the content,
            # so the returned handoff cannot be validated.
            payload = {
                "schema_version": request["handoff_output_schema_version"],
                "artifact_content": self.artifact_content,
                "handoff": {
                    **dict(request["handoff_binding"]),
                    "content_hash": SHA_B,
                },
            }
            return AdapterResult(
                response_text=json.dumps(payload, sort_keys=True),
                provider_request_id="not-persisted",
            )
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
            provider_request_id="not-persisted",
        )


@dataclass
class _SubstrateResolver:
    """Double for the neutral ``ModelAccessResolver`` port only.

    It performs the same grouped validation the production resolver performs
    and never touches the host secret contract, so no credential is read.
    """

    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess:
        return self.resolve_group(
            (request,), runtime=runtime, channel=channel, consumer=consumer
        )[0]

    def resolve_group(
        self,
        requests: Sequence[ModelResolutionRequest],
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> tuple[ResolvedModelAccess, ...]:
        self.calls.append((runtime, channel, consumer))
        request_tuple = tuple(requests)
        resolutions = tuple(
            ResolvedModelAccess(
                request=request,
                provider=SUBSTRATE_TARGETS[request.role_profile][0],
                model=SUBSTRATE_TARGETS[request.role_profile][1],
                adapter_id=_adapter_id(request.role_profile),
                effective_identity=(
                    f"{SUBSTRATE_TARGETS[request.role_profile][0]}/"
                    f"{SUBSTRATE_TARGETS[request.role_profile][1]}"
                ),
                capabilities=ModelCapabilities(
                    structured_output=True,
                    system_prompt_channel=True,
                ),
                credential_identity_ref=(
                    f"{SUBSTRATE_TARGETS[request.role_profile][0]}.api-key"
                ),
            )
            for request in request_tuple
        )
        try:
            return validate_resolved_group(request_tuple, resolutions)
        except ValueError as exc:
            raise ModelAccessResolutionError(str(exc)) from exc


def _adapter_id(role_profile: str) -> str:
    provider, model = SUBSTRATE_TARGETS[role_profile]
    return f"{provider}-{model}"


# ---------------------------------------------------------------------------
# Production composition helpers.
# ---------------------------------------------------------------------------


def _production_repo_root(tmp_path: Path) -> Path:
    """Copy the *real* repo-governed policy and Yggdrasil token into a sandbox.

    The bytes are the shipped ones, so admission, policy identity, and
    Yggdrasil parity are evaluated against production truth while writes stay
    inside ``tmp_path``.
    """

    root = tmp_path / "repo"
    policy_path = root / DESIGN_RUN_POLICY_PATH
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_bytes((REPO_ROOT / DESIGN_RUN_POLICY_PATH).read_bytes())
    token_path = root / YGGDRASIL_TOKEN_SOURCE
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_bytes((REPO_ROOT / YGGDRASIL_TOKEN_SOURCE).read_bytes())
    return root


def _repo_token_hash(repo_root: Path) -> str:
    return hashlib.sha256(
        (repo_root / YGGDRASIL_TOKEN_SOURCE).read_bytes()
    ).hexdigest()


def _store(tmp_path: Path, name: str) -> SqliteBuilderOpsStore:
    store = SqliteBuilderOpsStore(tmp_path / name)
    store.initialize()
    return store


def _dormant_governance(tmp_path: Path, name: str) -> DesignRunGovernance:
    """The genuinely shipped composition: no adapter map, no credential grant."""

    return DesignRunGovernance.from_declared_sources(
        store=_store(tmp_path, name),
        channel="dev",
        repo_root=_production_repo_root(tmp_path),
    )


def _substrate_governance(
    tmp_path: Path,
    name: str,
    adapters: Mapping[str, _CountingAdapter],
) -> DesignRunGovernance:
    """Real registry + real governance, with only the substrate port doubled."""

    return DesignRunGovernance(
        store=_store(tmp_path, name),
        registry=DesignAgentAdapterRegistry(
            resolver=_SubstrateResolver(),
            model_turn_adapters=dict(adapters),
            channel="test",
        ),
        repo_root=_production_repo_root(tmp_path),
        lease_ttl_seconds=30,
    )


def _source_refs(count: int = 1) -> tuple[DesignSourceRef, ...]:
    refs = tuple(
        DesignSourceRef(
            source_type="ckm_observation",
            source_id=f"ckm:observation:acceptance-{index:03d}",
            content_hash=SHA_A,
        )
        for index in range(count)
    )
    return tuple(sorted(refs, key=lambda ref: ref.identity))


def _attachment() -> DigestBoundAttachmentRef:
    return DigestBoundAttachmentRef(
        attachment_id="preview.acceptance",
        media_type="image/png",
        content_hash=SHA_B,
    )


def _brief(
    *,
    brief_id: str,
    deliverable: str = "content_review",
    source_ref_count: int = 1,
    yggdrasil: YggdrasilGateReceipt | None = None,
) -> CuratedDesignBrief:
    visual = deliverable == "visual_handoff"
    return CuratedDesignBrief(
        brief_id=brief_id,
        projection_id="ckm.projection.acceptance",
        requested_deliverable=deliverable,
        source_refs=_source_refs(source_ref_count),
        constraints=("Use explicit evidence only.",),
        yggdrasil_gate_receipt=yggdrasil if visual else None,
        non_visual_exemption=None if visual else True,
    )


def _yggdrasil(
    *,
    repo_token_hash: str,
    live_token_hash: str | None = None,
    verified_at: str = "2026-08-01T08:00:00Z",
    expires_at: str = "2026-08-01T12:00:00Z",
) -> YggdrasilGateReceipt:
    return YggdrasilGateReceipt(
        receipt_id="receipt.yggdrasil.acceptance",
        system_name="Yggdrasil",
        system_id="yggdrasil.design.system",
        selection_mechanism="explicit_attachment",
        repo_token_source=YGGDRASIL_TOKEN_SOURCE,
        live_token_hash=live_token_hash or repo_token_hash,
        repo_token_hash=repo_token_hash,
        parity_passed=True,
        verified_at=verified_at,
        expires_at=expires_at,
        preview_refs=(_attachment(),),
    )


def _admit(
    governance: DesignRunGovernance,
    *,
    run_id: str,
    adapter_id: str,
    brief: CuratedDesignBrief,
    evaluated_at: str = T1,
) -> None:
    governance.admit(
        run_id=run_id,
        request_id=f"{run_id}.request",
        brief=brief,
        adapter_id=adapter_id,
        requested_at=T0,
        evaluated_at=evaluated_at,
    )


def _approve_and_execute(
    governance: DesignRunGovernance,
    *,
    run_id: str,
    started_at: str = T3,
    completed_at: str = T4,
) -> None:
    governance.approve(
        run_id=run_id,
        approval_id=f"{run_id}.approval",
        approved_at=T2,
    )
    governance.execute(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
    )


def _total_calls(adapters: Mapping[str, _CountingAdapter]) -> int:
    return sum(len(adapter.calls) for adapter in adapters.values())


def _fresh_adapters(
    mode: Literal[
        "success",
        "timeout",
        "failure",
        "malformed_output",
        "foreign_binding",
    ] = "success",
) -> dict[str, _CountingAdapter]:
    """One counting adapter per distinct substrate target."""

    adapters: dict[str, _CountingAdapter] = {}
    for role_profile in sorted(SUBSTRATE_TARGETS):
        provider, model = SUBSTRATE_TARGETS[role_profile]
        adapter_id = _adapter_id(role_profile)
        adapters.setdefault(
            adapter_id,
            _CountingAdapter(
                adapter_id=adapter_id,
                provider=provider,
                model=model,
                mode=mode,
            ),
        )
    return adapters


# ---------------------------------------------------------------------------
# AC1 — production composition proves the complete success/refusal matrix.
# ---------------------------------------------------------------------------


def _assert_cli_composition_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the real ``ckm overview --cockpit --design-hub`` composition root.

    This is the shipped operator path: it composes
    ``DesignRunGovernance.from_declared_sources``, so adapter availability is
    the genuinely dormant production posture even though the seeded receipts
    were produced through the substrate seam.
    """

    cli_root = tmp_path / "cli"
    cli_root.mkdir()
    db_path = cli_root / "builderops.sqlite3"
    seed_store = SqliteBuilderOpsStore(db_path)
    seed_store.initialize()
    CkmStore(db_path).ensure_schema()

    repo_root = _production_repo_root(cli_root)
    adapters = _fresh_adapters()
    seed_governance = DesignRunGovernance(
        store=seed_store,
        registry=DesignAgentAdapterRegistry(
            resolver=_SubstrateResolver(),
            model_turn_adapters=dict(adapters),
            channel="test",
        ),
        repo_root=repo_root,
        lease_ttl_seconds=30,
    )
    _admit(
        seed_governance,
        run_id="run.cli.succeeded",
        adapter_id="codex",
        brief=_brief(brief_id="brief.cli.succeeded"),
    )
    _approve_and_execute(seed_governance, run_id="run.cli.succeeded")
    _admit(
        seed_governance,
        run_id="run.cli.pending",
        adapter_id="fable",
        brief=_brief(brief_id="brief.cli.pending"),
    )
    assert _total_calls(adapters) == 1

    monkeypatch.setattr("app.builderops.ckm.overview_html.utc_now", lambda: T0)
    runner = CliRunner()
    outputs: list[str] = []
    for index in range(2):
        out_path = cli_root / f"overview-{index}.html"
        result = runner.invoke(
            builderops,
            [
                "--db-path",
                str(db_path),
                "ckm",
                "overview",
                "--cockpit",
                "--design-hub",
                "--repo-root",
                str(repo_root),
                "--out",
                str(out_path),
            ],
        )
        assert result.exit_code == 0, result.output
        outputs.append(out_path.read_text(encoding="utf-8"))

    # Byte-identical final cockpit HTML from fixed inputs (INV-CDH-9).
    assert outputs[0] == outputs[1]
    rendered = outputs[0]
    assert '<section class="design-hub"' in rendered
    assert 'data-design-hub-run="run.cli.succeeded"' in rendered
    assert 'data-design-hub-run="run.cli.pending"' in rendered

    # The operator path advertises the dormant production posture only: every
    # registered route is unavailable and no credential was read.
    section = rendered.split('<section class="design-hub"', 1)[1].split(
        "</section>", 1
    )[0]
    for agent_id in DESIGN_AGENT_IDS:
        assert f'data-design-hub-adapter="{agent_id}"' in section
    assert "design-hub-available" not in section
    assert section.count("design-hub-unavailable") == len(DESIGN_AGENT_IDS)
    for token in ("<form", "<button", "<select", "<textarea", "<script", "<a "):
        assert token not in section

    # No new provider turn was made by rendering, and the default cockpit is
    # unchanged when the opt-in flag is absent.
    assert _total_calls(adapters) == 1
    default_path = cli_root / "overview-default.html"
    default_result = runner.invoke(
        builderops,
        [
            "--db-path",
            str(db_path),
            "ckm",
            "overview",
            "--cockpit",
            "--out",
            str(default_path),
        ],
    )
    assert default_result.exit_code == 0, default_result.output
    assert '<section class="design-hub"' not in default_path.read_text(
        encoding="utf-8"
    )

    # The opt-in flag pair is fail-closed on its own preconditions.
    for args, expected in (
        (["--design-hub"], "ckm overview --design-hub requires --cockpit"),
        (
            ["--cockpit", "--design-hub"],
            "ckm overview --design-hub requires --repo-root",
        ),
    ):
        guarded = runner.invoke(
            builderops,
            ["--db-path", str(db_path), "ckm", "overview"]
            + args
            + ["--out", str(cli_root / "guard.html")],
        )
        assert guarded.exit_code != 0
        assert expected in guarded.output


def test_design_hub_production_matrix_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, str] = {}

    # -- Case: no adapters ---------------------------------------------------
    # The genuinely shipped composition. Every registered route is unavailable,
    # nothing resolves a credential, and no run can be started at all.
    dormant = _dormant_governance(tmp_path, "dormant.sqlite3")
    dormant_descriptors = dormant.list_adapters(run_id="run.acceptance.dormant")
    assert tuple(item.design_agent_id for item in dormant_descriptors) == DESIGN_AGENT_IDS
    assert {
        item.design_agent_id: item.limitation_code for item in dormant_descriptors
    } == {
        "claude-design-via-claude-code": "interactive_subscription_only",
        "codex": "model_access_unavailable",
        "fable": "model_access_unavailable",
    }
    assert all(item.available is False for item in dormant_descriptors)
    assert all(item.provider_identity is None for item in dormant_descriptors)
    dormant_hub = build_design_hub_projection(governance=dormant)
    assert dormant_hub.runs == ()
    assert dormant_hub.excluded_run_ids == ()

    # A run against the dormant registry reaches `unavailable` and never calls
    # a provider, because there is no adapter to call.
    _admit(
        dormant,
        run_id="run.acceptance.dormant",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.dormant"),
    )
    dormant.approve(
        run_id="run.acceptance.dormant",
        approval_id="run.acceptance.dormant.approval",
        approved_at=T2,
    )
    with pytest.raises(DesignRunUnavailableError):
        dormant.execute(
            run_id="run.acceptance.dormant", started_at=T3, completed_at=T4
        )
    dormant_projection = dormant.projection("run.acceptance.dormant")
    assert dormant_projection.state == "unavailable"
    assert dormant_projection.refusal is not None
    assert dormant_projection.refusal.code == "adapter_unavailable"
    assert dormant_projection.result is None

    # -- Cases driven through the real registry over the doubled substrate ---
    adapters = _fresh_adapters()
    governance = _substrate_governance(tmp_path, "matrix.sqlite3", adapters)
    repo_token_hash = _repo_token_hash(governance.repo_root)
    policy = load_design_run_policy(governance.repo_root)

    # -- Case: unknown adapter ----------------------------------------------
    # Refused at the registry boundary; no run, no receipt, no provider turn.
    with pytest.raises(UnknownDesignAgentError):
        _admit(
            governance,
            run_id="run.acceptance.unknown",
            adapter_id="not-a-registered-design-agent",
            brief=_brief(brief_id="brief.acceptance.unknown"),
        )
    assert _total_calls(adapters) == 0
    assert not [
        record
        for record in governance.store.list_records("BuilderOpsReceipt")
        if "run.acceptance.unknown" in json.dumps(record.get("target_refs"))
    ]

    # -- Case: unavailable adapter (interactive-subscription-only route) -----
    # `claude-design-via-claude-code` stays unavailable even when the substrate
    # resolves and a matching model-turn adapter is registered, and the run
    # never falls through to `codex` or `fable`.
    interactive_descriptors = {
        item.design_agent_id: item
        for item in governance.list_adapters(run_id="run.acceptance.interactive")
    }
    for agent_id in INTERACTIVE_ONLY_AGENT_IDS:
        assert interactive_descriptors[agent_id].available is False
        assert (
            interactive_descriptors[agent_id].limitation_code
            == "interactive_subscription_only"
        )
    for agent_id in HEADLESS_CAPABLE_AGENT_IDS:
        assert interactive_descriptors[agent_id].available is True
    _admit(
        governance,
        run_id="run.acceptance.interactive",
        adapter_id="claude-design-via-claude-code",
        brief=_brief(brief_id="brief.acceptance.interactive"),
    )
    governance.approve(
        run_id="run.acceptance.interactive",
        approval_id="run.acceptance.interactive.approval",
        approved_at=T2,
    )
    with pytest.raises(DesignRunUnavailableError):
        governance.execute(
            run_id="run.acceptance.interactive", started_at=T3, completed_at=T4
        )
    observed["unavailable"] = governance.projection(
        "run.acceptance.interactive"
    ).state
    assert _total_calls(adapters) == 0

    # -- Case: policy denial -------------------------------------------------
    # The repo-governed policy caps explicit source refs; exceeding it denies
    # admission outright.
    _admit(
        governance,
        run_id="run.acceptance.denied",
        adapter_id="codex",
        brief=_brief(
            brief_id="brief.acceptance.denied",
            source_ref_count=policy.max_source_refs + 1,
        ),
    )
    denied = governance.projection("run.acceptance.denied")
    observed["denied"] = denied.state
    assert denied.refusal is not None and denied.refusal.code == "admission_denied"
    with pytest.raises(DesignRunGovernanceError):
        governance.execute(
            run_id="run.acceptance.denied", started_at=T3, completed_at=T4
        )
    assert _total_calls(adapters) == 0

    # -- Case: approval pending ---------------------------------------------
    _admit(
        governance,
        run_id="run.acceptance.pending",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.pending"),
    )
    pending = governance.projection("run.acceptance.pending")
    observed["approval_pending"] = pending.state
    assert pending.refusal is not None and pending.refusal.code == "approval_pending"
    with pytest.raises(DesignRunApprovalRequiredError):
        governance.execute(
            run_id="run.acceptance.pending", started_at=T3, completed_at=T4
        )
    assert _total_calls(adapters) == 0

    # -- Case: malformed request --------------------------------------------
    # A request whose refs do not bind the exact submitted inputs.
    other_brief = _brief(brief_id="brief.acceptance.other")
    malformed_brief = _brief(brief_id="brief.acceptance.malformed")
    descriptor = governance.registry.contract_descriptor("codex")
    mismatched_request = governance.build_request(
        request_id="run.acceptance.malformed.request",
        brief=other_brief,
        adapter=descriptor,
        requested_at=T0,
    )
    governance.submit(
        run_id="run.acceptance.malformed",
        request=mismatched_request,
        brief=malformed_brief,
        adapter=descriptor,
        evaluated_at=T1,
    )
    malformed = governance.projection("run.acceptance.malformed")
    observed["malformed"] = malformed.state
    assert malformed.refusal is not None
    assert malformed.refusal.code == "malformed_request"
    assert _total_calls(adapters) == 0

    # -- Case: missing Yggdrasil parity (visual deliverable) -----------------
    # A visual brief cannot even be constructed without a receipt, so the
    # contract refuses before any governance surface is reached.
    with pytest.raises(ValueError):
        _brief(
            brief_id="brief.acceptance.ygg-missing",
            deliverable="visual_handoff",
            yggdrasil=None,
        )

    # -- Case: drifted Yggdrasil parity -------------------------------------
    _admit(
        governance,
        run_id="run.acceptance.ygg-drift",
        adapter_id="codex",
        brief=_brief(
            brief_id="brief.acceptance.ygg-drift",
            deliverable="visual_handoff",
            yggdrasil=_yggdrasil(repo_token_hash=SHA_A),
        ),
    )
    drift = governance.projection("run.acceptance.ygg-drift")
    assert drift.state == "denied"
    assert drift.refusal is not None
    assert drift.refusal.code == "yggdrasil_token_drift"
    assert _total_calls(adapters) == 0

    # -- Case: stale Yggdrasil parity ---------------------------------------
    _admit(
        governance,
        run_id="run.acceptance.ygg-stale",
        adapter_id="codex",
        brief=_brief(
            brief_id="brief.acceptance.ygg-stale",
            deliverable="visual_handoff",
            yggdrasil=_yggdrasil(
                repo_token_hash=repo_token_hash,
                verified_at="2026-07-31T08:00:00Z",
                expires_at="2026-07-31T09:00:00Z",
            ),
        ),
    )
    stale_gate = governance.projection("run.acceptance.ygg-stale")
    assert stale_gate.state == "denied"
    assert stale_gate.refusal is not None
    assert stale_gate.refusal.code == "yggdrasil_gate_stale"
    assert _total_calls(adapters) == 0

    # -- Case: current Yggdrasil parity is admissible ------------------------
    # The negative cases above must not be passing for an unrelated reason.
    _admit(
        governance,
        run_id="run.acceptance.ygg-current",
        adapter_id="codex",
        brief=_brief(
            brief_id="brief.acceptance.ygg-current",
            deliverable="visual_handoff",
            yggdrasil=_yggdrasil(repo_token_hash=repo_token_hash),
        ),
    )
    assert governance.projection("run.acceptance.ygg-current").state == (
        "approval_pending"
    )
    assert _total_calls(adapters) == 0

    # -- Case: stale approval (recorded before admission) --------------------
    with pytest.raises(DesignRunApprovalRequiredError):
        governance.approve(
            run_id="run.acceptance.pending",
            approval_id="run.acceptance.pending.stale-approval",
            approved_at=T0,
        )
    assert _total_calls(adapters) == 0

    # -- Case: revoked approval ---------------------------------------------
    _admit(
        governance,
        run_id="run.acceptance.revoked",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.revoked"),
    )
    governance.approve(
        run_id="run.acceptance.revoked",
        approval_id="run.acceptance.revoked.approval",
        approved_at=T2,
    )
    governance.revoke(
        run_id="run.acceptance.revoked",
        revocation_id="run.acceptance.revoked.revocation",
        revoked_at=T2,
    )
    with pytest.raises(DesignRunApprovalRequiredError):
        governance.execute(
            run_id="run.acceptance.revoked", started_at=T3, completed_at=T4
        )
    assert governance.projection("run.acceptance.revoked").approval is not None
    assert (
        governance.projection("run.acceptance.revoked").approval.state == "revoked"
    )
    assert _total_calls(adapters) == 0

    # -- Case: non-causal approval (approved after the named start) ----------
    _admit(
        governance,
        run_id="run.acceptance.noncausal",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.noncausal"),
    )
    governance.approve(
        run_id="run.acceptance.noncausal",
        approval_id="run.acceptance.noncausal.approval",
        approved_at=T3,
    )
    with pytest.raises(DesignRunApprovalRequiredError):
        governance.execute(
            run_id="run.acceptance.noncausal", started_at=T2, completed_at=T4
        )
    assert _total_calls(adapters) == 0

    # -- Case: mismatched approval evidence at an exact start ----------------
    _admit(
        governance,
        run_id="run.acceptance.mismatch",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.mismatch"),
    )
    governance.approve(
        run_id="run.acceptance.mismatch",
        approval_id="run.acceptance.mismatch.approval",
        approved_at=T2,
    )
    mismatch_projection = governance.projection("run.acceptance.mismatch")
    assert mismatch_projection.admission is not None
    assert mismatch_projection.approval is not None
    with pytest.raises(DesignRunApprovalRequiredError):
        governance.execute_exact(
            run_id="run.acceptance.mismatch",
            started_at=T3,
            completed_at=T4,
            expected_request_id="run.acceptance.mismatch.request",
            expected_request_hash=(
                mismatch_projection.admission.request_ref.content_hash
            ),
            expected_admission_id=mismatch_projection.admission.admission_id,
            expected_admission_hash=mismatch_projection.admission.content_hash,
            expected_approval_id="run.acceptance.mismatch.approval",
            expected_approval_hash=SHA_A,
        )
    assert _total_calls(adapters) == 0

    # -- Case: exact matching approval evidence still starts -----------------
    # Proves the mismatch above was rejected for the binding, not by accident.
    governance.execute_exact(
        run_id="run.acceptance.mismatch",
        started_at=T3,
        completed_at=T4,
        expected_request_id="run.acceptance.mismatch.request",
        expected_request_hash=mismatch_projection.admission.request_ref.content_hash,
        expected_admission_id=mismatch_projection.admission.admission_id,
        expected_admission_hash=mismatch_projection.admission.content_hash,
        expected_approval_id=mismatch_projection.approval.approval_id,
        expected_approval_hash=mismatch_projection.approval.content_hash,
    )
    assert governance.projection("run.acceptance.mismatch").state == "succeeded"
    assert _total_calls(adapters) == 1

    # -- Case: one governed success per headless-registered adapter ----------
    for index, agent_id in enumerate(HEADLESS_CAPABLE_AGENT_IDS):
        success_adapters = _fresh_adapters()
        success_governance = _substrate_governance(
            tmp_path, f"success-{index}.sqlite3", success_adapters
        )
        run_id = f"run.acceptance.success-{agent_id}"
        _admit(
            success_governance,
            run_id=run_id,
            adapter_id=agent_id,
            brief=_brief(brief_id=f"brief.acceptance.success-{agent_id}"),
        )
        _approve_and_execute(success_governance, run_id=run_id)
        projection = success_governance.projection(run_id)
        assert projection.state == "succeeded"
        assert projection.result is not None
        assert projection.result.handoff is not None
        assert projection.result.refusal is None
        selected_adapter_id = _adapter_id(DESIGN_AGENT_ROLE_PROFILES[agent_id])
        assert len(success_adapters[selected_adapter_id].calls) == 1
        # No fallback: exactly one provider turn across every registered target.
        assert _total_calls(success_adapters) == 1
        observed["succeeded"] = projection.state

    # -- Case: timeout -------------------------------------------------------
    timeout_adapters = _fresh_adapters(mode="timeout")
    timeout_governance = _substrate_governance(
        tmp_path, "timeout.sqlite3", timeout_adapters
    )
    _admit(
        timeout_governance,
        run_id="run.acceptance.timeout",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.timeout"),
    )
    _approve_and_execute(timeout_governance, run_id="run.acceptance.timeout")
    timed_out = timeout_governance.projection("run.acceptance.timeout")
    observed["timed_out"] = timed_out.state
    assert timed_out.refusal is not None and timed_out.refusal.code == "timed_out"
    assert timed_out.result is not None and timed_out.result.handoff is None
    assert _total_calls(timeout_adapters) == 1

    # -- Case: provider failure ---------------------------------------------
    failure_adapters = _fresh_adapters(mode="failure")
    failure_governance = _substrate_governance(
        tmp_path, "failure.sqlite3", failure_adapters
    )
    _admit(
        failure_governance,
        run_id="run.acceptance.failed",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.failed"),
    )
    _approve_and_execute(failure_governance, run_id="run.acceptance.failed")
    failed = failure_governance.projection("run.acceptance.failed")
    observed["failed"] = failed.state
    assert failed.refusal is not None and failed.refusal.code == "execution_failed"
    assert failed.result is not None and failed.result.handoff is None
    assert _total_calls(failure_adapters) == 1

    # -- Case: malformed provider output ------------------------------------
    malformed_adapters = _fresh_adapters(mode="malformed_output")
    malformed_governance = _substrate_governance(
        tmp_path, "malformed-output.sqlite3", malformed_adapters
    )
    _admit(
        malformed_governance,
        run_id="run.acceptance.malformed-output",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.malformed-output"),
    )
    _approve_and_execute(
        malformed_governance, run_id="run.acceptance.malformed-output"
    )
    malformed_output = malformed_governance.projection(
        "run.acceptance.malformed-output"
    )
    assert malformed_output.state == "failed"
    assert malformed_output.result is not None
    assert malformed_output.result.handoff is None
    # A digest-invalid return never becomes a success or a linkable artifact.
    assert _total_calls(malformed_adapters) == 1

    # -- Case: correctly digested output bound to a foreign run --------------
    # The digest alone must not be sufficient: the returned handoff has to bind
    # the exact run, evidence set, and start receipt it was admitted for.
    foreign_adapters = _fresh_adapters(mode="foreign_binding")
    foreign_governance = _substrate_governance(
        tmp_path, "foreign-binding.sqlite3", foreign_adapters
    )
    _admit(
        foreign_governance,
        run_id="run.acceptance.foreign-binding",
        adapter_id="codex",
        brief=_brief(brief_id="brief.acceptance.foreign-binding"),
    )
    _approve_and_execute(
        foreign_governance, run_id="run.acceptance.foreign-binding"
    )
    foreign = foreign_governance.projection("run.acceptance.foreign-binding")
    assert foreign.state == "failed"
    assert foreign.result is not None
    assert foreign.result.handoff is None
    assert foreign.refusal is not None
    assert foreign.refusal.code == "execution_failed"
    assert _total_calls(foreign_adapters) == 1

    # -- The real CLI composition root renders the same fail-closed truth ----
    _assert_cli_composition_is_fail_closed(tmp_path, monkeypatch)

    # -- Distinctness of every terminal/refusal state ------------------------
    assert set(observed) == {
        "unavailable",
        "denied",
        "approval_pending",
        "malformed",
        "timed_out",
        "failed",
        "succeeded",
    }
    assert observed == {
        "unavailable": "unavailable",
        "denied": "denied",
        "approval_pending": "approval_pending",
        "malformed": "malformed",
        "timed_out": "timed_out",
        "failed": "failed",
        "succeeded": "succeeded",
    }
    assert len(set(observed.values())) == len(observed)


# ---------------------------------------------------------------------------
# AC2 — outputs stay unaccepted Builder material with validated lineage.
# ---------------------------------------------------------------------------

_AUTHORITY_CROSSING_TOKENS = (
    "subprocess",
    "requests.",
    "httpx",
    "urllib.request",
    "gh issue",
    "gh pr",
    "PyGithub",
    "load_runtime_secret_values",
)
_DESIGN_SURFACE_MODULES = (
    "app/builderops/design_run_contract.py",
    "app/builderops/design_agent_adapters.py",
    "app/builderops/design_run_governance.py",
    "app/builderops/ckm/design_hub.py",
)


def _repo_tree_digest(root: Path) -> str:
    entries = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in entries:
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def test_design_hub_outputs_remain_unaccepted_builder_material(
    tmp_path: Path,
) -> None:
    adapters = _fresh_adapters()
    governance = _substrate_governance(tmp_path, "lineage.sqlite3", adapters)
    repo_digest_before = _repo_tree_digest(governance.repo_root)

    run_id = "run.acceptance.lineage"
    brief = _brief(brief_id="brief.acceptance.lineage")
    _admit(governance, run_id=run_id, adapter_id="codex", brief=brief)
    _approve_and_execute(governance, run_id=run_id)

    projection = governance.projection(run_id)
    assert projection.state == "succeeded"
    assert projection.result is not None
    handoff = projection.result.handoff
    assert handoff is not None

    # --- Handoff is unaccepted Builder material, never accepted truth -------
    assert handoff.acceptance_state == "unaccepted_builder_material"
    assert handoff.limitations == (
        "Unaccepted Builder material; governed promotion is required.",
    )
    assert handoff.run_id == run_id
    assert handoff.source_refs == brief.source_refs
    assert handoff.adapter_ref.contract_id == "codex"

    # --- Validated digest: the handoff binds the exact returned artifact ----
    selected_adapter = adapters[_adapter_id("design.codex")]
    assert len(selected_adapter.calls) == 1
    assert _total_calls(adapters) == 1
    assert (
        handoff.content_hash
        == hashlib.sha256(
            selected_adapter.artifact_content.encode("utf-8")
        ).hexdigest()
    )

    # --- Causal receipt lineage --------------------------------------------
    records = [
        record
        for record in governance.store.list_records("BuilderOpsReceipt")
        if record.get("event_type") == DESIGN_RUN_RECEIPT_EVENT_TYPE
    ]
    events = {
        record["id"]: json.loads(record["receipt_body"])
        for record in records
        if json.loads(record["receipt_body"]).get("run_id") == run_id
    }
    assert handoff.receipt_ref.contract_id in events
    start_event = events[handoff.receipt_ref.contract_id]
    assert start_event["event_type"] == "start_accepted"
    assert start_event["state"] == "running"
    # Chain order and single-root causality via the design_hub projection.
    design_hub = build_design_hub_projection(governance=governance)
    assert design_hub.excluded_run_ids == ()
    assert [run.run_id for run in design_hub.runs] == [run_id]
    hub_run = design_hub.runs[0]
    assert hub_run.receipts[0].previous_receipt_id is None
    for earlier, later in zip(hub_run.receipts, hub_run.receipts[1:]):
        assert later.previous_receipt_id == earlier.receipt_id
    assert hub_run.receipts[-1].receipt_id == hub_run.latest_receipt_id
    assert hub_run.latest_receipt_id == projection.latest_receipt_id
    assert handoff.receipt_ref.contract_id in {
        receipt.receipt_id for receipt in hub_run.receipts
    }

    # --- No direct Issue/PR/owner-doc/Product/HKA mutation ------------------
    # Nothing outside the BuilderOps receipt store was written.
    assert _repo_tree_digest(governance.repo_root) == repo_digest_before
    object_types = {
        record.get("object_type") for record in governance.store.list_records()
    }
    assert object_types == {"BuilderOpsReceipt"}
    for record in records:
        for target in record.get("target_refs") or []:
            assert target["ref_type"] == "design_run"
            assert target["authority_surface"] == "builderops"
        for source in record.get("source_refs") or []:
            assert source["ref_type"] == "repo_doc"
    # No design surface owns a mutation transport at all.
    for module in _DESIGN_SURFACE_MODULES:
        source_text = (REPO_ROOT / module).read_text(encoding="utf-8")
        for token in _AUTHORITY_CROSSING_TOKENS:
            assert token not in source_text, f"{module} must not reference {token}"

    # --- Cockpit output labels it as unaccepted and never links it ----------
    ckm_store = CkmStore(tmp_path / "ckm.sqlite3")
    ckm_store.ensure_schema()
    rendered = render_overview_html(
        ckm_store,
        generated_at=T0,
        cockpit=CockpitRenderContext(
            batch=ckm_store.load_projection_batch(), design_hub=design_hub
        ),
    )
    section = rendered.split('<section class="design-hub"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "unaccepted_builder_material" in section
    assert "Unaccepted Builder material" in section
    assert handoff.content_hash in section
    assert "<a " not in section
    assert "<img" not in section
    assert design_hub_digest(design_hub) == design_hub_digest(
        build_design_hub_projection(governance=governance)
    )


# ---------------------------------------------------------------------------
# AC4 — the focused regression evidence is bound to this exact PR head.
# ---------------------------------------------------------------------------

# What binds "these regressions pass" to the exact PR head is CI, not this
# module: `scripts/select_pr_tests.py` expands this diff to the `builder_system`
# lane, which runs the whole `tests/builderops` tree — every suite named below —
# and `.github/workflows/pr-evidence-pack.yml` snapshots those check runs keyed
# on `pull_request.head.sha`. This test therefore does the one thing that
# evidence cannot do for itself: prove the *named set is complete and its
# targets resolve* at the head where it runs, so the head-bound pass evidence
# cannot quietly cover a smaller set than the slice claims.
#
# `tests/builderops/ckm` is named as a whole directory on purpose: AC4 says
# "CKM regressions", and naming two of its nineteen modules would understate
# what the cited head-SHA evidence actually covers.
FOCUSED_REGRESSION_SUITES: tuple[str, ...] = (
    "tests/builderops/ckm",
    "tests/builderops/test_design_agent_adapters.py",
    "tests/builderops/test_design_hub_acceptance.py",
    "tests/builderops/test_design_run_cli.py",
    "tests/builderops/test_design_run_contract.py",
    "tests/builderops/test_design_run_governance.py",
    "tests/builderops/test_model_inquiry_adapters.py",
    "tests/builderops/test_model_inquiry_cli.py",
    "tests/builderops/test_model_inquiry_contract.py",
    "tests/builderops/test_model_inquiry_promotion.py",
    "tests/builderops/test_model_inquiry_resume.py",
    "tests/builderops/test_model_inquiry_runner.py",
    "tests/builderops/test_model_inquiry_trace.py",
)
FOCUSED_REGRESSION_SURFACES: tuple[str, ...] = _DESIGN_SURFACE_MODULES + (
    "app/builderops/ckm/overview_html.py",
    "app/builderops/model_access_resolver.py",
    "config/builderops/design_run_policy.json",
)

# Acceptance-criteria targets this slice must keep resolvable.
ACCEPTANCE_VERIFY_TARGETS: tuple[tuple[str, str], ...] = (
    (
        "tests/builderops/test_design_hub_acceptance.py",
        "test_design_hub_production_matrix_is_fail_closed",
    ),
    (
        "tests/builderops/test_design_hub_acceptance.py",
        "test_design_hub_outputs_remain_unaccepted_builder_material",
    ),
    (
        "tests/builderops/ckm/test_design_cockpit.py",
        "test_design_hub_projection_preserves_direction_b_authority",
    ),
    (
        "tests/builderops/test_design_hub_acceptance.py",
        "test_focused_regression_set_is_complete_and_verify_targets_resolve",
    ),
)

def test_focused_regression_set_is_complete_and_verify_targets_resolve() -> None:
    """Prove the named focused-regression set is complete and resolvable here.

    This test runs inside the same head-SHA CI lane that runs every suite named
    below, so "complete at this head" is exactly what it can prove. It does not
    itself re-run those suites, and it deliberately records no content digest:
    the head-bound pass evidence is the CI check run for the lane, not a literal
    in this file.
    """

    # Every named focused suite and production surface exists at this head.
    for relative in FOCUSED_REGRESSION_SUITES:
        assert (REPO_ROOT / relative).exists(), f"missing focused suite {relative}"
    for relative in FOCUSED_REGRESSION_SURFACES:
        assert (REPO_ROOT / relative).is_file(), f"missing focused surface {relative}"

    # The registered design-agent identities the matrix partitions must stay
    # exhaustive: a newly registered adapter must land in exactly one of the
    # two buckets rather than silently escaping the governed-success matrix.
    assert set(HEADLESS_CAPABLE_AGENT_IDS) | set(INTERACTIVE_ONLY_AGENT_IDS) == set(
        DESIGN_AGENT_IDS
    )
    assert not set(HEADLESS_CAPABLE_AGENT_IDS) & set(INTERACTIVE_ONLY_AGENT_IDS)
    assert set(SUBSTRATE_TARGETS) == set(DESIGN_AGENT_ROLE_PROFILES.values())

    # Every acceptance-criteria Verify: target resolves to a real test function.
    for relative, test_name in ACCEPTANCE_VERIFY_TARGETS:
        module = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in module.body
            if isinstance(node, ast.FunctionDef)
        }
        assert test_name in defined, f"{relative} does not define {test_name}"

    # The named set covers every design-run, design-hub, and model-inquiry
    # regression module in the tree, so head-bound pass evidence cited for this
    # slice cannot quietly cover a smaller set than the slice claims.
    named = set(FOCUSED_REGRESSION_SUITES)
    discovered = {
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests" / "builderops").rglob("test_*.py")
        if "design" in path.name or "model_inquiry" in path.name
    }
    for relative in discovered:
        assert relative in named or any(
            relative.startswith(f"{candidate}/") for candidate in named
        ), f"{relative} is not covered by the named focused-regression set"

    # Every named suite is inside the tree the PR test selector expands this
    # diff to, so CI at the head SHA actually runs them.
    assert all(
        relative.startswith("tests/builderops/")
        for relative in FOCUSED_REGRESSION_SUITES
    )
