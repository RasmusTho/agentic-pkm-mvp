"""Class-specific deterministic transforms for the mechanical-hygiene engine (G2-2).

Spec: ``docs/YGGDRASIL_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §2.

Design constraint carried over verbatim from the spec: **detection may be
cognitive (cheap local LLM or rules), application must be a deterministic
transform re-derived from file content**. Every candidate this module accepts
is recomputed here from ``observed``/``span`` -- if the transform cannot
reproduce the candidate's ``proposed`` text exactly, the candidate demotes to
propose-track (:class:`TransformResult` with ``matched=False``). No transform
in this module writes to a file; it only decides whether an ``exact``,
reproducible replacement exists for a given finding. The (currently
unreachable, ADR-0048-gated) ``act`` tier is the only tier that would ever
apply a transform's output as a body edit -- see
``docs/adr/ADR-0048-allowlisted-mechanical-hygiene-act-tier.md``. This slice
(G2-2) never writes a transform's output to a note body; it only uses the
match/no-match verdict to decide whether a finding demotes to propose (it
always materializes as propose while ``AUTOFIX_APPLY`` is unset, per
``app.curation.proposal_writer``).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.curation.findings import FindingClass


@dataclass(frozen=True)
class TransformResult:
    """Outcome of re-deriving a deterministic transform for one finding.

    ``matched`` is the graduation gate: only an exact, reproducible match may
    ever reach the (currently disabled) ``act`` tier. A non-match is not an
    error -- it is the expected outcome whenever detection produced a
    candidate the deterministic transform cannot prove safe, and the finding
    stays on (or demotes to) the propose track.
    """

    matched: bool
    transformed: str | None = None
    reason: str = ""


def transform_broken_wikilink(
    *, observed: str, candidate_targets: tuple[str, ...]
) -> TransformResult:
    """Deterministic transform for ``link.broken_wikilink``.

    Only matches when resolution is unambiguous: exactly one candidate
    target. Two or more candidates (or zero) cannot be resolved
    deterministically and the finding demotes to propose (spec §2 table:
    "only when exactly one unambiguous target resolves; else propose").
    """
    if len(candidate_targets) != 1:
        return TransformResult(
            matched=False,
            reason=(
                "ambiguous or unresolved wikilink target "
                f"({len(candidate_targets)} candidates) -- demotes to propose"
            ),
        )
    # `observed` is accepted for interface symmetry with the other
    # transforms (all of which re-derive from file content) but is not
    # itself consulted here: the replacement is fully determined by the
    # single resolved target, never by editing `observed` in place.
    target = candidate_targets[0]
    return TransformResult(matched=True, transformed=f"[[{target}]]")


def transform_malformed_markdown(*, span_text: str) -> TransformResult:
    """Deterministic transform for ``markdown.malformed_syntax``.

    Bounded to one reproducible repair: an unclosed fenced code block (an
    opening ` ``` ` line with no matching closer). The transform appends the
    missing closing fence -- nothing else is rewritten, so the result is
    exactly reproducible from ``span_text`` alone.
    """
    lines = span_text.splitlines()
    fence_count = sum(1 for line in lines if line.strip().startswith("```"))
    if fence_count % 2 == 0:
        return TransformResult(
            matched=False, reason="no unclosed fence detected -- not this transform's class"
        )
    transformed = span_text.rstrip("\n") + "\n```"
    return TransformResult(matched=True, transformed=transformed)


def transform_frontmatter_schema(*, raw_frontmatter_block: str) -> TransformResult:
    """Deterministic transform for ``frontmatter.schema_violation``.

    Bounded to the one structural repair the lint check can itself detect
    (`app.curation.lint._check_frontmatter_schema`): an unterminated
    frontmatter block. Repair is purely structural (append the closing
    delimiter) -- it never touches key casing or value semantics, matching
    the class's "format only, never value semantics" scope.
    """
    if raw_frontmatter_block.count("---") >= 2:
        return TransformResult(
            matched=False, reason="frontmatter already terminated -- not this transform's class"
        )
    transformed = raw_frontmatter_block.rstrip("\n") + "\n---\n"
    return TransformResult(matched=True, transformed=transformed)


def transform_text_span(
    *, observed: str, llm_candidate: str, language_gate_passed: bool
) -> TransformResult:
    """Deterministic transform for ``text.misspelling`` / ``text.transcription_artifact``.

    The engine never applies an LLM's replacement directly (spec §8:
    "LLM-applied fixes... rejected"). Here the "transform" is the identity
    function over the LLM's own candidate *only* when the Swedish safeguard
    (``app.curation.sv_lexicon_guard``) has already cleared the span
    (``language_gate_passed``); the transform re-derives nothing beyond
    confirming the candidate differs from the observed text and the gate
    passed, and refuses to match otherwise. If the gate rejected the span,
    the candidate can never reproduce a safe edit and always demotes to
    propose, regardless of how confident detection was.
    """
    if not language_gate_passed:
        return TransformResult(
            matched=False,
            reason="Swedish safeguard did not clear this span -- demotes to propose",
        )
    if not llm_candidate or llm_candidate == observed:
        return TransformResult(
            matched=False, reason="no differing candidate to reproduce"
        )
    return TransformResult(matched=True, transformed=llm_candidate)


# FindingClass import kept for callers that want to assert a finding's class
# is one this module has a transform for; re-exported for convenience.
SUPPORTED_TRANSFORM_CLASSES = frozenset(
    {
        FindingClass.LINK_BROKEN_WIKILINK,
        FindingClass.MARKDOWN_MALFORMED_SYNTAX,
        FindingClass.FRONTMATTER_SCHEMA_VIOLATION,
        FindingClass.TEXT_MISSPELLING,
        FindingClass.TEXT_TRANSCRIPTION_ARTIFACT,
    }
)


__all__ = [
    "SUPPORTED_TRANSFORM_CLASSES",
    "TransformResult",
    "transform_broken_wikilink",
    "transform_frontmatter_schema",
    "transform_malformed_markdown",
    "transform_text_span",
]
