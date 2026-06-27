"""Invariant skeletons: bounded context only; denied scopes do not leak; bundle != envelope.

Invariant registry: docs/testing/invariant-tests.md
  :: context_envelope_has_no_raw_vault_or_index_access, denied_scope_does_not_leak_identity,
     context_bundle_is_not_context_envelope
Issues: #2550 (registry), #2552 (skeletons). Contract: docs/architecture/context-envelope.md (#2545).
"""

from __future__ import annotations

from tests.invariants._helpers import REPO_ROOT, load_defs, load_schema

# Fields that would reveal the existence/identity of a denied scope or its content.
_LEAK_KEYS = {"scope_id", "object_id", "content", "metadata_bundle", "provenance_event_ids", "source_role"}


def test_context_envelope_has_no_raw_vault_or_index_access() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: context_envelope_has_no_raw_vault_or_index_access
    # Static (schema_enforced): access_mode is pinned to bounded_context_only and no property grants
    # raw vault/index access.
    ce = load_schema("context-envelope.schema.json")
    assert ce["properties"]["access_mode"].get("const") == "bounded_context_only"
    raw = [k for k in ce.get("properties", {}) if "vault" in k.lower() or "raw_index" in k.lower()]
    assert raw == [], f"envelope must not expose a raw access field: {raw}"
    assert ce.get("additionalProperties") is False


def test_denied_scope_does_not_leak_identity() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: denied_scope_does_not_leak_identity
    # Static (schema_enforced): the shared scope_denial record is a closed object whose only fields
    # are non-identifying routing fields — no denied scope/object id, content, or provenance.
    scope_denial = load_defs()["$defs"]["scope_denial"]
    assert scope_denial.get("additionalProperties") is False
    props = set(scope_denial.get("properties", {}))
    leaked = props & _LEAK_KEYS
    assert not leaked, f"scope_denial must not carry identifying fields: {sorted(leaked)}"
    # Both the envelope's denied_scopes and the retrieval result's denied list use this closed record.
    ce = load_schema("context-envelope.schema.json")
    assert "scope_denial" in str(ce["properties"]["denied_scopes"]["items"])


def test_context_bundle_is_not_context_envelope() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: context_bundle_is_not_context_envelope
    # Static (schema_enforced): the envelope composes ContextBundles by id and marks them non_authority;
    # the ContextBundle remains a separate contract that the envelope does not replace.
    ce = load_schema("context-envelope.schema.json")
    bundle_item = ce["properties"]["context_bundles"]["items"]
    assert "context_bundle_id" in bundle_item.get("properties", {})
    assert bundle_item["properties"]["non_authority"].get("const") is True
    assert "non_authority" in bundle_item.get("required", [])
    # The ContextBundle contract exists independently and is not collapsed into the envelope.
    assert (REPO_ROOT / "docs" / "contracts" / "CONTEXT_BUNDLE.md").exists()
