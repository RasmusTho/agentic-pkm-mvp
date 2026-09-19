"""Contract tests for the Cockpit-to-devUI Overview input adapter (#4834)."""

from __future__ import annotations

from copy import deepcopy

from app.builderops.devui_overview_inputs import derive_overview_inputs


GENERATED_AT = "2026-08-22T12:00:00+00:00"
UPDATED_AT = "2026-08-22T11:59:00+00:00"


def _item(*, number: int = 4834, title: str = "Cockpit source title") -> dict:
    return {
        "repo": "RasmusTho/agentic-pkm-mvp",
        "issue_number": number,
        "title": title,
        "why_now": "The source-owned working predicate is active.",
        "updated_at": UPDATED_AT,
        "ignored": "not copied",
    }


def _work_provider(*, items: list[dict] | None = None) -> dict:
    current_items = items if items is not None else [_item()]
    return {
        "provider": "builderops_cockpit",
        "status": "available",
        "authority": "read_time_join",
        "captured_at": GENERATED_AT,
        "snapshot": {"generated_at": GENERATED_AT, "sources": []},
        "completeness": {
            "claim": {
                "kind": "counted",
                "text": "working threads counted",
                "as_of": GENERATED_AT,
            },
            "unread_planes": [],
            "withdrawn_counts": [],
        },
        "payload": {
            "authority": "read_time_join",
            "generated_at": GENERATED_AT,
            "claim": {
                "kind": "counted",
                "text": "working threads counted",
                "as_of": GENERATED_AT,
            },
            "sources": [
                {
                    "name": "dispatcher-store",
                    "state": "fresh",
                    "last_successful_read": GENERATED_AT,
                    "detail": "read succeeded",
                    "stale_after_days": 7,
                    "configured": True,
                }
            ],
            "unread_planes": [],
            "withdrawn_counts": [],
            "bands": [
                {
                    "key": "working",
                    "question": "What are we working on?",
                    "countable": True,
                    "count": len(current_items),
                    "items": current_items,
                }
            ],
        },
    }


def _context_item(*, number: int = 5599, **overrides: object) -> dict:
    item = _item(number=number, title="Contextual work")
    item.update(
        {
            "id": f"task-{number}",
            "claimed_by": "registered-holder",
            "status": "claimed",
            "capability_lane": {
                "key": "capability:fixture",
                "name": "Fixture capability",
                "rung": "proven",
            },
            "sources": ["dispatcher-store", "docs-frontmatter", "github-live"],
            "next_action": "read the source blocker",
            "next_action_evidence": "issue comment blocker_action.v1",
            "mirror_watermark": "2026-08-22T11:58:00+00:00",
            "chain_position": "in_progress",
            "position_evidence": {
                "dispatcher_status": "claimed",
                "last_movement_at": UPDATED_AT,
            },
            "position_unresolved_reason": None,
            "flaws": [
                {
                    "predicate": "blocked_without_next_link",
                    "text": "blocked: waiting for the source",
                    "evidence": {"dispatcher_status": "claimed"},
                }
            ],
        }
    )
    item.update(overrides)
    return item


def _context_work_provider(*, item: dict, docs_state: str = "fresh") -> dict:
    provider = _work_provider(items=[item])
    provider["payload"]["sources"][0]["transport"] = {
        "source_refs": [
            f"/v1/tasks/task-{item['issue_number']}?repository={item['repo']}#version=1",
            f"builderops-api:{item['repo']}@epoch=7#sha256={'b' * 64}",
        ]
    }
    provider["payload"]["sources"].extend(
        [
            {
                "name": "docs-frontmatter",
                "state": docs_state,
                "last_successful_read": GENERATED_AT,
                "detail": "candidate documents read",
                "stale_after_days": 7,
                "configured": True,
                "transport": {
                    "repository": "RasmusTho/agentic-pkm-mvp",
                    "candidate_sha": "a" * 40,
                    "outcome": "available" if docs_state == "fresh" else "stale",
                    "source_refs": [
                        "https://github.com/RasmusTho/agentic-pkm-mvp/blob/"
                        + "a" * 40
                        + "/docs/capabilities.yaml",
                        "https://github.com/RasmusTho/agentic-pkm-mvp/blob/"
                        + "a" * 40
                        + "/docs/FIXTURE/TASK.md",
                    ],
                },
            },
            {
                "name": "github-live",
                "state": "fresh",
                "last_successful_read": GENERATED_AT,
                "detail": "bounded GitHub read",
                "stale_after_days": 0,
                "configured": True,
                "transport": {
                    "source_refs": [
                        "github-rest:RasmusTho/agentic-pkm-mvp@"
                        + GENERATED_AT
                        + "#sha256="
                        + "c" * 64,
                        "https://github.com/RasmusTho/agentic-pkm-mvp/tree/"
                        + "d" * 40,
                    ]
                },
            },
        ]
    )
    return provider


def test_adapter_is_pure_and_admits_only_trusted_unique_working_band() -> None:
    provider = _work_provider()
    original = deepcopy(provider)

    candidates = derive_overview_inputs(work_provider=provider)

    assert provider == original
    assert len(candidates["now"]) == 1

    for mutation in (
        lambda value: value.__setitem__("status", "refused"),
        lambda value: value["payload"]["claim"].__setitem__("kind", "refused"),
        lambda value: value["payload"]["sources"][0].__setitem__("state", "stale"),
        lambda value: value["payload"]["bands"].append(deepcopy(value["payload"]["bands"][0])),
    ):
        malformed = deepcopy(provider)
        mutation(malformed)
        assert derive_overview_inputs(work_provider=malformed) == {"now": []}


def test_working_threads_map_to_source_ordered_now_candidates() -> None:
    provider = _work_provider(items=[_item(number=1, title="First"), _item(number=2, title="Second")])

    candidates = derive_overview_inputs(work_provider=provider)

    assert [item["display_label"] for item in candidates["now"]] == ["First", "Second"]
    first = candidates["now"][0]
    assert first["reason"] == "The source-owned working predicate is active."
    assert first["subject_ref"] == {
        "source_type": "github_issue",
        "source_id": "github:RasmusTho/agentic-pkm-mvp#1",
        "locator": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1",
        "version": UPDATED_AT,
    }
    assert first["evidence"][0]["source_ref"]["source_type"] == "builderops_cockpit_working_projection"
    assert first["evidence"][0]["source_ref"]["version"] == UPDATED_AT


def test_now_candidates_copy_only_repo_issue_number_title_why_now_and_updated_at() -> None:
    candidate = derive_overview_inputs(work_provider=_work_provider())["now"][0]

    assert set(candidate) == {
        "subject_ref",
        "display_label",
        "reason",
        "evidence",
        "navigation_refs",
        "limitations",
    }
    assert "ignored" not in repr(candidate)


def test_now_candidates_preserve_order_cardinality_and_duplicates() -> None:
    repeated = _item(number=9, title="Repeated")
    items = [_item(number=1, title="First"), repeated, deepcopy(repeated)]

    candidates = derive_overview_inputs(work_provider=_work_provider(items=items))["now"]

    assert [item["display_label"] for item in candidates] == ["First", "Repeated", "Repeated"]
    assert len(candidates) == 3


def test_now_candidates_add_no_authority_delivery_or_navigation_claims() -> None:
    candidate = derive_overview_inputs(work_provider=_work_provider())["now"][0]

    assert "owner_authority" not in candidate
    assert "delivery_facts" not in candidate
    assert candidate["navigation_refs"] == []
    assert candidate["limitations"] == []


def test_refusal_uncountable_and_malformed_work_remain_explicit() -> None:
    provider = _work_provider()
    variants = []

    refused = deepcopy(provider)
    refused["status"] = "refused"
    variants.append(refused)

    uncountable = deepcopy(provider)
    uncountable["payload"]["bands"][0]["countable"] = False
    uncountable["payload"]["bands"][0]["count"] = None
    variants.append(uncountable)

    bad_count = deepcopy(provider)
    bad_count["payload"]["bands"][0]["count"] = 2
    variants.append(bad_count)

    malformed = deepcopy(provider)
    malformed["payload"]["bands"][0]["items"][0]["updated_at"] = "not-a-timestamp"
    variants.append(malformed)

    for variant in variants:
        assert derive_overview_inputs(work_provider=variant) == {"now": []}


def test_nonworking_bands_are_ignored_and_withdrawals_stay_closed() -> None:
    provider = _work_provider()
    for key in ("needs_you", "done", "flawed", "forgotten"):
        provider["payload"]["bands"].append(
            {"key": key, "countable": True, "count": 1, "items": [_item(title=key)]}
        )

    candidates = derive_overview_inputs(work_provider=provider)

    assert len(candidates["now"]) == 1
    assert candidates.keys() == {"now"}


def test_owner_context_preserves_source_linked_work_facts() -> None:
    item = _context_item()

    candidate = derive_overview_inputs(
        work_provider=_context_work_provider(item=item)
    )["now"][0]

    assert [row["display_label"] for row in [candidate]] == ["Contextual work"]
    assert candidate["reason"] == item["why_now"]
    claims = [entry["claim"] for entry in candidate["evidence"] if entry["claim"]]
    assert any("Fixture capability" in claim for claim in claims)
    assert any("registered-holder" in claim and "claimed" in claim for claim in claims)
    assert any("in_progress" in claim for claim in claims)
    assert any("read the source blocker" in claim for claim in claims)
    assert any("blocked: waiting for the source" in claim for claim in claims)
    assert any("Position evidence (source-declared)" in claim for claim in claims)
    assert any(
        "/v1/tasks/task-5599?repository=RasmusTho/agentic-pkm-mvp" in claim
        for claim in claims
    )
    flaw = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "builderops_cockpit_flaws"
    )
    assert '"dispatcher_status":"claimed"' in flaw["claim"]
    assert "/v1/tasks/task-5599?repository=RasmusTho/agentic-pkm-mvp" in flaw["claim"]
    assert candidate["evidence"][0]["source_ref"]["version"] == UPDATED_AT
    assert any(
        entry["source_ref"]["source_type"] == "docs-frontmatter"
        for entry in candidate["evidence"]
    )
    capability = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "docs-frontmatter"
    )
    assert "capabilities.yaml" in capability["source_ref"]["locator"]
    assert "TASK.md" in capability["source_ref"]["locator"]


def test_owner_context_preserves_independent_source_withdrawals() -> None:
    item = _context_item(mirror_watermark="2026-08-01T11:58:00+00:00")

    candidate = derive_overview_inputs(
        work_provider=_context_work_provider(item=item, docs_state="stale")
    )["now"][0]

    docs = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "docs-frontmatter"
    )
    next_step = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "builderops_mirror"
    )
    assert docs["claim"] is None
    assert docs["freshness"] == "stale"
    assert docs["limitation"]
    assert next_step["source_ref"]["version"] == "2026-08-01T11:58:00+00:00"
    assert next_step["captured_at"] == "2026-08-01T11:58:00+00:00"
    assert next_step["read_watermark"] == "2026-08-01T11:58:00+00:00"
    assert next_step["freshness"] == "unknown"
    assert next_step["completeness"] == "partial"
    assert any("does not authorize execution" in limitation for limitation in candidate["limitations"])
    assert next_step["source_ref"]["version"] != GENERATED_AT
    assert any("unknown" in limitation.lower() for limitation in candidate["limitations"])


def test_owner_context_does_not_infer_execution_permission_or_maturity() -> None:
    candidate = derive_overview_inputs(
        work_provider=_context_work_provider(item=_context_item())
    )["now"][0]

    assert set(candidate) == {
        "subject_ref",
        "display_label",
        "reason",
        "evidence",
        "navigation_refs",
        "limitations",
    }
    serialized = repr(candidate).lower()
    assert "owner_authority" not in serialized
    assert "delivery_facts" not in serialized
    assert "permission" not in serialized
    assert "maturity" not in serialized
    assert "ready_to_try" not in serialized


def test_owner_context_preserves_predicate_sources_and_raw_evidence() -> None:
    item = _context_item(
        flaws=[
            {
                "predicate": "pr_ci_red_on_head_sha",
                "text": "PR #502 CI is failure on head SHA dddddddddddd",
                "evidence": {
                    "check_state": "failure",
                    "head_sha": "d" * 40,
                    "pr_number": 502,
                },
            }
        ]
    )
    candidate = derive_overview_inputs(
        work_provider=_context_work_provider(item=item)
    )["now"][0]

    flaw = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "builderops_cockpit_flaws"
    )
    assert '"head_sha":"' + "d" * 40 + '"' in flaw["claim"]
    assert "github-live[fresh] github-rest:RasmusTho/agentic-pkm-mvp@" in flaw["claim"]
    assert flaw["source_ref"]["locator"].startswith("github-rest:RasmusTho/agentic-pkm-mvp@")
    assert flaw["read_watermark"] == GENERATED_AT


def test_owner_context_preserves_flaw_evaluation_scope() -> None:
    provider = _context_work_provider(item=_context_item())
    provider["payload"]["bands"].append(
        {
            "key": "flawed",
            "countable": True,
            "count": 1,
            "items": [],
            "header": {
                "evaluated": ["blocked_without_next_link"],
                "not_evaluated": [
                    {
                        "predicate": "pr_ci_red_on_head_sha",
                        "requires": ["github-live"],
                        "reason": "required source(s) not fresh: github-live (unavailable)",
                    }
                ],
                "unread": [{"predicate": "owner_outcome", "reason": "not admitted"}],
            },
        }
    )
    candidate = derive_overview_inputs(work_provider=provider)["now"][0]

    assert any("Flaw evaluation scope (source-declared)" in limitation for limitation in candidate["limitations"])
    assert any("pr_ci_red_on_head_sha" in limitation for limitation in candidate["limitations"])
    assert any("owner_outcome" in limitation for limitation in candidate["limitations"])


def test_owner_context_does_not_join_another_task_reference() -> None:
    item = _context_item(number=503)
    provider = _context_work_provider(item=item)
    provider["payload"]["sources"][0]["transport"]["source_refs"] = [
        "/v1/tasks/task-1?repository=RasmusTho/agentic-pkm-mvp#version=1"
    ]

    candidate = derive_overview_inputs(work_provider=provider)["now"][0]
    work = next(
        entry
        for entry in candidate["evidence"]
        if entry["source_ref"]["source_type"] == "dispatcher-store"
    )
    assert "task-1" not in repr(work)
    assert work["source_ref"]["locator"] == "/api/cockpit/registry#working"
