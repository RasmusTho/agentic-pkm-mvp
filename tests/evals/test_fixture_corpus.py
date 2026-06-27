"""Static integrity checks for the anti-contamination eval corpus (these pass today).

They assert the corpus is well-formed, synthetic, canonically tagged, and *deliberately overlapping*
in vocabulary — the preconditions every behavioral eval skeleton depends on.

Invariant registry: docs/testing/invariant-tests.md (#2550). Corpus: tests/evals/fixtures/ (#2551).
"""

from __future__ import annotations

import re

from tests.evals._helpers import (
    GROUPS,
    REQUIRED_META_KEYS,
    SHARED_VOCAB,
    load_corpus,
    load_group,
    value_family,
)


def test_fixture_groups_exist() -> None:
    for group in GROUPS:
        docs = load_group(group)
        assert docs, f"fixture group {group} has no documents"


def test_each_group_has_minimum_documents() -> None:
    # Issue #2551 AC: each group contains at least 2-3 short documents.
    for group in GROUPS:
        docs = load_group(group)
        assert len(docs) >= 2, f"{group} must have >=2 documents, found {len(docs)}"


def test_each_doc_has_canonical_metadata() -> None:
    # Every fixture carries the required metadata, with role/state values drawn from the canonical
    # value families in schemas/_defs.schema.json — so the fixtures are consistent with the contracts.
    source_roles = set(value_family("source_role"))
    authority_states = set(value_family("authority_state"))
    evidence_roles = set(value_family("evidence_role"))
    sensitivities = set(value_family("sensitivity"))
    for doc in load_corpus():
        missing = set(REQUIRED_META_KEYS) - set(doc.meta)
        assert not missing, f"{doc.path} missing metadata {sorted(missing)}"
        assert doc.meta.get("synthetic") == "true", f"{doc.path} must declare synthetic: true"
        assert doc.meta["source_role"] in source_roles, f"{doc.path} bad source_role {doc.meta['source_role']}"
        assert doc.meta["authority_state"] in authority_states, f"{doc.path} bad authority_state"
        assert doc.meta["evidence_role"] in evidence_roles, f"{doc.path} bad evidence_role"
        assert doc.meta["sensitivity"] in sensitivities, f"{doc.path} bad sensitivity"


def test_metadata_distinguishes_scopes() -> None:
    # Scope / source / authority / evidence must distinguish the groups — behavior cannot be encoded
    # in filenames alone (issue #2551 constraint).
    corpus = load_corpus()
    scope_ids = {d.meta["scope_id"] for d in corpus}
    assert len(scope_ids) == len(GROUPS), f"each group must have its own scope_id, got {scope_ids}"
    spheres = {d.meta["sphere"] for d in corpus}
    assert spheres >= {"work", "private", "rpg", "general"}
    # Each group is internally consistent on its scope_id.
    for group in GROUPS:
        group_scopes = {d.meta["scope_id"] for d in load_group(group)}
        assert len(group_scopes) == 1, f"{group} mixes scope_ids: {group_scopes}"


def test_shared_vocabulary_overlaps_across_groups() -> None:
    # The collision is real: every shared term appears in at least 3 of the 5 groups, so textual
    # similarity alone cannot separate the scopes.
    for term in SHARED_VOCAB:
        pat = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        groups_with = {
            group for group in GROUPS if any(pat.search(d.body) for d in load_group(group))
        }
        assert len(groups_with) >= 3, f"shared term {term!r} only appears in {sorted(groups_with)}"


def test_no_real_looking_private_identifiers() -> None:
    # All content is synthetic: no email-like identifiers that could be real PII/client data.
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    for doc in load_corpus():
        assert not email.search(doc.body), f"{doc.path} contains an email-like identifier"


def test_no_general_knowledge_boolean_bypass() -> None:
    # No fixture may encode a universal `general_knowledge` bypass flag in its metadata. general
    # knowledge is a source_role / eligibility signal, never a boolean that waves material across
    # every scope (cross-scope-flow.md §3).
    for doc in load_corpus():
        assert "general_knowledge" not in doc.meta, (
            f"{doc.path} encodes a general_knowledge metadata flag — that is a forbidden bypass; "
            "general_knowledge is a source_role value, not a cross-scope boolean"
        )
