"""Issue #4505: the semanticmd resolver must never silently discard committed
repository documentation. A repo doc (no `uuid:` frontmatter, e.g. docs/**,
README.md, AGENTS.md) whose two sides diverge must resolve to a conflict rather
than have the near-duplicate / "prefer concise" heuristic pick one side wholesale
and report MERGE_STATUS=resolved.

Issue #4616 (PR #4604 reviews r3700682703 / r3700682705) tightened the two
resolution mechanisms that could still produce a false-clean merge:
link carryover only counts when THEIRS' entire non-link prose survives in the
merged body, and the token-similarity near-duplicate bypass is scoped to vault
notes (uuid identity on both sides) so repository docs never resolve through a
lossy set-of-tokens comparison.
"""
import pathlib

import pytest

from app.agents.merge_resolver.agent import merge_note_from_blobs


def load(name):
    p = pathlib.Path("tests/fixtures/merge") / name
    return p.read_text(encoding="utf-8")


def test_repo_doc_merge_never_silently_drops_a_side():
    base = load("rd_base.md")
    a = load("rd_a.md")
    b = load("rd_b.md")

    merged, info = merge_note_from_blobs(base, a, b)

    # Neither side carries vault-note identity (no `uuid:` frontmatter) and the
    # bodies diverge, so the resolver must refuse to silently pick a side.
    assert info["status"] == "conflict"


def test_repo_doc_identical_sides_still_resolve():
    # No divergence, no vault identity -> nothing to lose, safe to resolve.
    base = load("rd_base.md")
    a = load("rd_a.md")
    b = load("rd_a.md")

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"


def test_link_carryover_does_not_hide_incoming_prose_loss():
    # PR #4604 review r3700682703 (#4616): OURS has no markdown link and THEIRS
    # has a link plus additional distinct prose. Carrying only the link into the
    # merged text does not account for that prose; reporting "resolved" would
    # let the git driver exit 0 while silently discarding THEIRS' non-link
    # content. The carryover bypass must require the complete incoming body
    # difference -- not merely its links -- to be preserved.
    base = "# Guide\n\nShared setup steps.\n"
    a = "# Guide\n\nShared setup steps, tightened by ours.\n"
    b = (
        "# Guide\n\n"
        "Shared setup steps.\n\n"
        "Theirs adds a distinct rollback warning that must not vanish.\n"
        "See the [runbook](https://example.com/runbook) for details.\n"
    )

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


def test_link_carryover_still_resolves_when_links_are_the_only_difference():
    # Safe counterpart to the test above: THEIRS differs from OURS only by a
    # markdown link. Appending the link preserves everything THEIRS brings, so
    # the carryover remains a trusted, lossless resolution.
    base = "# Guide\n\nShared setup steps.\n"
    a = "# Guide\n\nShared setup steps.\n"
    b = "# Guide\n\nShared setup steps. [runbook](https://example.com/runbook)\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"
    assert "https://example.com/runbook" in merged


def test_incoming_image_embed_is_not_treated_as_a_carried_link():
    # Carryover appends plain markdown links only, so an incoming image embed
    # can never be preserved verbatim in the merged body; the merge must
    # conflict instead of resolving with the image demoted to a bare link.
    base = "# T\n\nDeploy now! Done.\n"
    a = "# T\n\nDeploy now! Done.\n"
    b = "# T\n\nDeploy now![shot](https://example.com/s.png) Done.\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


def test_links_only_incoming_body_still_resolves_via_carryover():
    # THEIRS' body is nothing but a link; carrying it preserves everything
    # THEIRS brings, so this remains a lossless resolve.
    base = "shared base text\n"
    a = "ours prose kept intact\n"
    b = "[x](https://example.com/x)\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"
    assert "https://example.com/x" in merged


def test_link_carryover_containment_is_word_aligned():
    # THEIRS' "enabled in prod" must not count as preserved merely because
    # OURS happens to contain it as a fragment of "unenabled in prod": the
    # lossless-carryover containment check is word-aligned, not raw-substring.
    base = "deployment status\n"
    a = "unenabled in prod\n"
    b = "enabled in prod [ref](https://example.com/r)\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


def test_repo_doc_token_overlap_still_conflicts_when_bodies_differ():
    # PR #4604 review r3700682705 (#4616): set-of-tokens similarity ignores
    # order, repetition, and meaning -- "deployment is enabled" versus
    # "deployment is not enabled" scores above the 0.85 near-duplicate
    # threshold while inverting the meaning. A repository doc (no vault
    # identity) must never resolve through that lossy comparison.
    base = "# Runbook\n\ndeployment status pending\n"
    a = "# Runbook\n\ndeployment is enabled\n"
    b = "# Runbook\n\ndeployment is not enabled\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


def test_bare_uuid_key_does_not_grant_vault_near_duplicate_bypass():
    # A `uuid:` key with no value is not vault identity. The near-duplicate
    # bypass must not treat it as one, or the token-overlap defect above comes
    # back for any doc carrying an empty uuid field.
    base = "---\nuuid:\n---\n# Runbook\n\ndeployment status pending\n"
    a = "---\nuuid:\n---\n# Runbook\n\ndeployment is enabled\n"
    b = "---\nuuid:\n---\n# Runbook\n\ndeployment is not enabled\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


@pytest.mark.parametrize(
    "uuid_line",
    [
        'uuid: ""',
        "uuid: null",
        "uuid: ~",
        "uuid: NULL",
        "uuid: # missing",
        "uuid: >",
        "uuid: *alias",
        "uuid: !!null",
    ],
    ids=[
        "quoted-empty",
        "null",
        "tilde",
        "upper-null",
        "comment-only",
        "block-scalar",
        "alias",
        "tagged-null",
    ],
)
def test_degenerate_uuid_scalars_do_not_grant_vault_near_duplicate_bypass(uuid_line):
    # PR #4626 Codex review r3712514848 (P1): `_extract_uuid` used to return
    # the raw text after `uuid:`, so degenerate YAML scalars produced truthy
    # strings ('""', 'null', '# missing') and both-sides-degenerate documents
    # took the vault-only near-duplicate bypass, silently discarding THEIRS'
    # high-overlap-but-distinct body. A degenerate scalar is no identity.
    base = f"---\n{uuid_line}\n---\n# Runbook\n\ndeployment status pending\n"
    a = f"---\n{uuid_line}\n---\n# Runbook\n\ndeployment is enabled\n"
    b = f"---\n{uuid_line}\n---\n# Runbook\n\ndeployment is not enabled\n"

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "conflict"


def test_quoted_and_unquoted_uuid_are_the_same_identity():
    # Quote normalization: `uuid: "u-q"` and `uuid: u-q` name the same logical
    # note, so a genuine near-duplicate still resolves (no spurious hard
    # conflict from the quoting difference), and the bypass stays limited to
    # equal logical ids because divergent ids still hard-conflict upstream.
    base = '---\nuuid: "u-q"\n---\n# Note\nBaseline text.\n'
    a = '---\nuuid: "u-q"\n---\n# Note\nConcise phrasing of the idea.\n'
    b = (
        "---\nuuid: u-q\n---\n# Note\n"
        "Concise phrasing of the idea, the idea, the idea, restated again.\n"
    )

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"
    assert "concise" in info["reason"].lower()


def test_vault_note_merge_behavior_is_unchanged():
    # Same near-duplicate scenario as test_near_duplicate_prefers_concise in
    # tests/agents/test_merge_resolver.py, using fixtures that carry `uuid:`
    # frontmatter (vault-note identity). The guard added for #4505 must not
    # touch this path: it should still resolve and still prefer the concise side.
    base = load("nd_base.md")
    a = load("nd_concise.md")
    b = load("nd_rambly.md")

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"
    assert "concise" in info["reason"].lower()
    assert merged.strip() == a.strip()
