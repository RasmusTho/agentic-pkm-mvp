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
