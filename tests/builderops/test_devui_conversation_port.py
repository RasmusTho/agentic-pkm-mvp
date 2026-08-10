"""Contract tests for the external-first devUI Conversation Port (#4696)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.builderops.devui_conversation_port import (
    ConversationPortContractError,
    build_context_pack,
    canonical_context_pack_bytes,
    conversation_port_design_fixtures,
    open_external_conversation,
    validate_context_pack_bytes,
    validate_conversation_disposition,
)


NOW = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)
SUBJECT_REF = {
    "kind": "issue",
    "stable_id": "github:RasmusTho/agentic-pkm-mvp#4696",
    "authority_ref": {
        "source_type": "github_issue",
        "source_id": "RasmusTho/agentic-pkm-mvp#4696",
        "version": "updated-at:2026-08-09T13:23:44Z",
        "locator": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4696",
    },
    "title": "Open external Conversation Port",
}


def _source(source_id: str, *, digest: str = "a") -> dict:
    return {
        "source_type": "owner_document",
        "source_id": source_id,
        "content_hash": digest * 64,
        "locator": source_id,
    }


def _build(**overrides: object) -> dict:
    subject_ref = overrides.get("subject_ref", SUBJECT_REF)
    owner_intent_ref = _source("docs/DEVUI.md#DEVUI-FCP-BOUNDARY", digest="b")
    source_refs = [
        _source("docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md", digest="c")
    ]
    evidence_snapshot_refs = [
        {
            "source_type": "focus_projection",
            "source_id": "focus:github:RasmusTho/agentic-pkm-mvp#4696",
            "snapshot": "composed-at:2026-08-09T13:59:00+00:00",
            "locator": "devui:focus:4696",
        }
    ]
    material_refs = [
        subject_ref["authority_ref"],  # type: ignore[index]
        owner_intent_ref,
        *source_refs,
        *evidence_snapshot_refs,
    ]
    values: dict[str, object] = {
        "pack_id": "pack-4696-a",
        "subject_ref": subject_ref,
        "purpose": "Reason about the next governed disposition for FCP-03.",
        "owner_intent_ref": owner_intent_ref,
        "source_refs": source_refs,
        "evidence_snapshot_refs": evidence_snapshot_refs,
        "source_states": [
            {
                "source_ref": ref,
                "freshness": "fresh",
                "captured_at": (NOW - timedelta(minutes=1)).isoformat(),
                "fresh_until": (NOW + timedelta(minutes=30)).isoformat(),
                "read_watermark": f"source-read:{index}",
            }
            for index, ref in enumerate(material_refs)
        ],
        "includes": ["owner_intent", "governing_sources", "limitations"],
        "excludes": [
            "credentials",
            "hidden_system_prompts",
            "provider_sessions",
            "broad_repository_history",
        ],
        "limitations": [
            {
                "kind": "projection_only",
                "reason": "The context pack is provenance, not work authority.",
            }
        ],
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(overrides)
    return build_context_pack(**values)  # type: ignore[arg-type]


def test_context_pack_hash_is_canonical_and_scope_bounded() -> None:
    pack = _build()
    reordered = {key: pack[key] for key in reversed(pack)}

    assert canonical_context_pack_bytes(reordered) == canonical_context_pack_bytes(pack)
    assert validate_context_pack_bytes(
        canonical_context_pack_bytes(pack), now=NOW
    ) == pack

    noncanonical = json.dumps(pack, indent=2, ensure_ascii=False).encode("utf-8")
    with pytest.raises(ConversationPortContractError, match="canonical UTF-8 JSON"):
        validate_context_pack_bytes(noncanonical, now=NOW)

    duplicate = canonical_context_pack_bytes(pack).replace(
        b'{"allowed_dialogue_outcomes":',
        b'{"contract_version":"conversation-context-pack.v1","allowed_dialogue_outcomes":',
        1,
    )
    with pytest.raises(ConversationPortContractError, match="duplicate field"):
        validate_context_pack_bytes(duplicate, now=NOW)

    changed = {**pack, "purpose": "Changed after preview"}
    with pytest.raises(ConversationPortContractError, match="content hash"):
        validate_context_pack_bytes(canonical_context_pack_bytes(changed), now=NOW)

    with pytest.raises(ConversationPortContractError, match="expired"):
        validate_context_pack_bytes(
            canonical_context_pack_bytes(pack), now=NOW + timedelta(hours=1)
        )

    with pytest.raises(ConversationPortContractError, match="over-broad"):
        _build(includes=["*"])

    duplicate_source = _source("docs/duplicate.md", digest="d")
    with pytest.raises(ConversationPortContractError, match="duplicate or ambiguous"):
        _build(source_refs=[duplicate_source, duplicate_source])

    stale_states = list(_build()["source_states"])
    stale_states[0] = {**stale_states[0], "freshness": "stale"}
    with pytest.raises(ConversationPortContractError, match="not fresh enough"):
        _build(source_states=stale_states)

    expiring_states = list(_build()["source_states"])
    expiring_states[0] = {
        **expiring_states[0],
        "fresh_until": (NOW + timedelta(minutes=5)).isoformat(),
    }
    with pytest.raises(ConversationPortContractError, match="freshness deadline"):
        _build(source_states=expiring_states)


def test_context_pack_capability_subject_requires_owner_document_authority() -> None:
    capability_subject = {
        "kind": "capability",
        "stable_id": "devui.conversation-port",
        "authority_ref": _source(
            "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md#conversation-port-contract",
            digest="d",
        ),
        "title": "External Conversation Port",
    }
    calls: list[bytes] = []

    def build_and_open(subject_ref: dict) -> dict:
        pack = _build(subject_ref=subject_ref)
        exact = canonical_context_pack_bytes(pack)

        def opener(payload: bytes, _content_hash: str) -> dict:
            calls.append(payload)
            return {"provider_request_id": "codex-capability-subject"}

        return open_external_conversation(
            pack_bytes=exact,
            expected_hash=pack["content_hash"],
            provider="codex",
            availability="available",
            reason="Configured external adapter",
            opener=opener,
            now=NOW,
        )

    ckm_only_subject = {
        **capability_subject,
        "authority_ref": {
            **capability_subject["authority_ref"],
            "source_type": "ckm_capability",
        },
    }
    with pytest.raises(ConversationPortContractError, match="owner_document"):
        build_and_open(ckm_only_subject)
    assert calls == []

    result = build_and_open(capability_subject)
    assert result["state"] == "opened"
    assert calls == [canonical_context_pack_bytes(_build(subject_ref=capability_subject))]


def test_external_port_has_no_global_session_discovery() -> None:
    pack = _build()
    exact = canonical_context_pack_bytes(pack)
    calls: list[tuple[bytes, str]] = []

    def opener(payload: bytes, content_hash: str) -> dict:
        calls.append((payload, content_hash))
        return {"provider_request_id": "codex-request-4696"}

    result = open_external_conversation(
        pack_bytes=exact,
        expected_hash=pack["content_hash"],
        provider="codex",
        availability="available",
        reason="Configured external adapter",
        opener=opener,
        now=NOW,
    )

    assert calls == [(exact, pack["content_hash"])]
    assert result == {
        "state": "opened",
        "provider": "codex",
        "context_hash": pack["content_hash"],
        "provider_request_id": "codex-request-4696",
        "authority": "provenance_only",
        "durable_effect": False,
    }
    assert "session" not in result


def test_provider_failure_degrades_only_the_port() -> None:
    pack = _build()
    exact = canonical_context_pack_bytes(pack)
    calls = 0

    def opener(_payload: bytes, _content_hash: str) -> dict:
        nonlocal calls
        calls += 1
        raise AssertionError("degraded adapters must not be called")

    for state in ("unavailable", "unsupported", "refused"):
        result = open_external_conversation(
            pack_bytes=exact,
            expected_hash=pack["content_hash"],
            provider="claude",
            availability=state,
            reason=f"Provider is {state}",
            opener=opener,
            now=NOW,
        )
        assert result["state"] == state
        assert result["focus_usable"] is True
        assert result["durable_effect"] is False
    assert calls == 0


def test_disposition_is_provenance_not_command() -> None:
    pack = _build()
    disposition = validate_conversation_disposition(
        {
            "contract_version": "conversation-disposition.v1",
            "context_hash": pack["content_hash"],
            "outcome": "plan",
            "rationale": "Proceed through the governed FCP-04 workflow when admitted.",
            "source_refs": pack["source_refs"],
            "limitations": pack["limitations"],
            "provenance": {
                "provider": "codex",
                "model": "external-subscription",
                "provider_session_ref": "codex:session:optional-provenance",
            },
            "proposed_command": None,
        },
        expected_context_hash=pack["content_hash"],
    )

    assert disposition["authority"] == "provenance_only"
    assert disposition["durable_effect"] is False

    proposed = {
        key: disposition[key]
        for key in (
            "contract_version",
            "context_hash",
            "outcome",
            "rationale",
            "source_refs",
            "limitations",
            "provenance",
            "proposed_command",
        )
    }
    proposed["proposed_command"] = {
        "contract_version": "typed-command-proposal.v1",
        "context_pack_ref": {
            "pack_id": pack["pack_id"],
            "content_hash": pack["content_hash"],
        },
    }
    with pytest.raises(ConversationPortContractError, match="require.*FCP-04"):
        validate_conversation_disposition(
            proposed, expected_context_hash=pack["content_hash"]
        )

    hostile = dict(disposition)
    hostile["execute"] = True
    with pytest.raises(ConversationPortContractError, match="unknown field"):
        validate_conversation_disposition(
            hostile, expected_context_hash=pack["content_hash"]
        )

    with pytest.raises(ConversationPortContractError, match="outcome"):
        validate_conversation_disposition(
            {
                "contract_version": "conversation-disposition.v1",
                "context_hash": pack["content_hash"],
                "outcome": "apply",
                "rationale": "Direct effect",
                "source_refs": [],
                "limitations": [],
                "provenance": {},
                "proposed_command": None,
            },
            expected_context_hash=pack["content_hash"],
        )


def test_conversation_port_emits_design_handoff_fixtures() -> None:
    pack = _build()
    fixtures = conversation_port_design_fixtures(pack)

    assert set(fixtures) == {
        "exact_hash",
        "no_action",
        "unavailable",
        "unsupported",
        "stale",
        "unlinked",
    }
    assert fixtures["exact_hash"]["context_hash"] == pack["content_hash"]
    assert fixtures["no_action"]["outcome"] == "no_action"
    assert fixtures["stale"]["start_available"] is False
    assert fixtures["unlinked"]["linkage"] == "unlinked"
    assert all(item["visual_geometry"] == "unspecified" for item in fixtures.values())
