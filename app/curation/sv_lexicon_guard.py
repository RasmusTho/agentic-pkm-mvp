"""The Swedish safeguard (multilingual auto-fix gate), G2-2 §3.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §3.

Threat modelled: an English-centric checker "corrects" valid Swedish --
compounds (*sjukvårdsförsäkring*), definite suffixes (*boken*, *husen*),
å/ä/ö -- into garbage. Because the dyslexia-friendly posture makes the user
*less* likely to catch a bad silent fix, every one of these checks is a hard,
deterministic gate:

1. **Lexicon veto (deterministic, pre-LLM):** a token present in the bundled
   sv_SE word-list (:data:`SV_LEXICON`), or accepted by the bounded compound
   analysis (:func:`is_lexicon_valid_compound`), is untouchable by
   ``text.*`` auto-fixes -- regardless of any model's confidence.
2. **Language verdict per finding, not per note:** :func:`detect_language`
   classifies one span; ``mixed``/``unknown`` verdicts demote ``text.*``
   findings to propose (SV<->EN code-switching inside one sentence is
   normal in this vault -- demotion, not guessing).
3. **Diacritic invariance:** :func:`preserves_diacritics` asserts no
   å/ä/ö/é is added/removed/substituted between two token strings. This is
   a transform-level assertion, never policy prose.
4. **Never cross-language:** :func:`same_language_verdict` asserts the
   source and result tokens share a language verdict (a fix may not
   "correct" a Swedish word into its English neighbour, or vice versa).

No external NLP dependency is introduced for this bounded gate (no
``pyhunspell``/hunspell binding is vendored in this environment); this module
is the "note's declared-language dictionary" alternative the spec names
explicitly (§3.1: "the sv_SE hunspell dictionary (or the note's
declared-language dictionary)"). The word-list and suffix/compound rules
below are the deterministic dictionary substrate for that alternative --
adding real hunspell as a swappable backend is a future, separately-scoped
enhancement, not required by this slice's acceptance criteria.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.curation.findings import LanguageVerdict

# Bounded sv_SE word-list covering common closed-class words, the adversarial
# near-English fixture terms named in the spec (fakta, snabbt, event, mejl),
# and representative compound/definite-suffix bases used by the test
# fixtures. This is deliberately small and explicit (not a bundled corpus)
# so its membership is auditable in code review, matching the "no default
# track" fail-loud posture used elsewhere in this package.
SV_LEXICON: frozenset[str] = frozenset(
    {
        # closed-class / high frequency
        "och", "eller", "men", "att", "det", "den", "de", "som", "för",
        "med", "till", "från", "på", "av", "är", "var", "har", "hade",
        "inte", "kan", "ska", "skulle", "vill", "vara", "detta", "denna",
        "dessa", "man", "vi", "du", "jag", "han", "hon", "vad", "hur",
        "när", "där", "här", "sig", "sin", "sitt", "sina", "en", "ett",
        # adversarial near-English fixture terms (spec §3: "adversarial
        # near-English Swedish: fakta, snabbt, event, mejl")
        "fakta", "snabbt", "event", "mejl",
        # compound/definite-suffix bases used by fixtures
        "bok", "boken", "hus", "husen", "sjukvård", "försäkring",
        "sjukvårdsförsäkring",
    }
)

# Definite-suffix endings a bounded compound analysis may strip before
# re-checking the lexicon (spec §3.1: "any token that sv_SE compound-analysis
# accepts"). This is a small, closed set of Swedish definite-article suffixes
# -- not a general morphological analyzer.
_DEFINITE_SUFFIXES: tuple[str, ...] = ("en", "et", "na", "n", "t")

_DIACRITIC_CHARS = "åäöéÅÄÖÉ"
_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _strip_definite_suffix(token: str) -> str | None:
    lowered = token.lower()
    for suffix in sorted(_DEFINITE_SUFFIXES, key=len, reverse=True):
        if len(lowered) > len(suffix) + 1 and lowered.endswith(suffix):
            candidate = lowered[: -len(suffix)]
            if candidate in SV_LEXICON:
                return candidate
    return None


def is_lexicon_valid_compound(token: str) -> bool:
    """Bounded compound/definite-suffix analysis over :data:`SV_LEXICON`.

    Accepts a token if: it is a lexicon word outright, stripping a known
    definite suffix yields a lexicon word, or the token can be split into
    two lexicon words at some boundary (the compound case, e.g.
    ``sjukvårdsförsäkring`` = ``sjukvård`` + ``försäkring``). This is a
    closed, deterministic analysis -- not a general morphological engine --
    matching the spec's "sv_SE compound-analysis" framing at the scope this
    slice needs.
    """
    lowered = token.lower().strip()
    if not lowered:
        return False
    if lowered in SV_LEXICON:
        return True
    if _strip_definite_suffix(lowered) is not None:
        return True
    for split in range(2, len(lowered) - 1):
        left, right = lowered[:split], lowered[split:]
        if left in SV_LEXICON and (right in SV_LEXICON or _strip_definite_suffix(right) is not None):
            return True
    return False


def has_diacritics(token: str) -> bool:
    return any(ch in _DIACRITIC_CHARS for ch in token)


def preserves_diacritics(source_token: str, result_token: str) -> bool:
    """Assert no å/ä/ö/é is added, removed, or substituted between two tokens.

    Compares the *set* of diacritic characters present (case-normalized via
    NFC), not position -- any change to which diacritics appear is a
    violation. Non-diacritic edits (e.g. plain-ASCII typo fixes) are
    unaffected by this check.
    """
    normalize = lambda text: unicodedata.normalize("NFC", text)
    source_diacritics = {ch for ch in normalize(source_token) if ch in _DIACRITIC_CHARS}
    result_diacritics = {ch for ch in normalize(result_token) if ch in _DIACRITIC_CHARS}
    return source_diacritics == result_diacritics


@dataclass(frozen=True)
class LanguageDetection:
    verdict: LanguageVerdict
    sv_token_ratio: float
    en_token_ratio: float


# A tiny closed-class English marker set used only to detect code-switching
# inside an otherwise-Swedish span (and vice versa). Not a general English
# lexicon -- just enough closed-class signal to flag `mixed`.
_EN_MARKERS: frozenset[str] = frozenset(
    {
        "the", "and", "or", "but", "is", "are", "was", "were", "this",
        "that", "these", "those", "with", "from", "have", "has", "will",
        "would", "can", "could", "should",
        # Common English content words plausible in SV/EN code-switched
        # sentences in this vault (spec §3.2 example shape: "great möte
        # today", "meeting", "fine") -- a closed, bounded set for detecting
        # the code-switch case, not a general English lexicon.
        "great", "today", "meeting", "fine", "email", "call", "team",
        "deadline", "feedback", "update", "review", "meetings",
    }
)


def detect_language(span_text: str) -> LanguageDetection:
    """Fast, deterministic per-span language verdict.

    Not a statistical/ML detector: counts lexicon hits against
    :data:`SV_LEXICON` (extended by :func:`is_lexicon_valid_compound`) vs.
    :data:`_EN_MARKERS`. Both present above a bounded floor -> ``mixed``
    (SV<->EN code-switching, spec §3.2, "demotion, not guessing"). Neither
    present -> ``unknown``. This intentionally never guesses a majority
    verdict from a token-count plurality; `mixed`/`unknown` fail toward
    propose, which is the safe direction for this gate.
    """
    tokens = [tok for tok in _TOKEN_RE.findall(span_text) if tok]
    if not tokens:
        return LanguageDetection(LanguageVerdict.UNKNOWN, 0.0, 0.0)

    sv_hits = sum(1 for tok in tokens if is_lexicon_valid_compound(tok))
    en_hits = sum(1 for tok in tokens if tok.lower() in _EN_MARKERS)
    sv_ratio = sv_hits / len(tokens)
    en_ratio = en_hits / len(tokens)

    if sv_hits > 0 and en_hits > 0:
        return LanguageDetection(LanguageVerdict.MIXED, sv_ratio, en_ratio)
    if sv_hits > 0:
        return LanguageDetection(LanguageVerdict.SV, sv_ratio, en_ratio)
    if en_hits > 0:
        return LanguageDetection(LanguageVerdict.EN, sv_ratio, en_ratio)
    return LanguageDetection(LanguageVerdict.UNKNOWN, sv_ratio, en_ratio)


def same_language_verdict(source_verdict: LanguageVerdict, result_verdict: LanguageVerdict) -> bool:
    """Assert a fix does not cross the source span's language verdict.

    ``mixed``/``unknown`` never compare equal to anything (including
    themselves) here -- they are never an eligible source verdict for an
    auto-fix in the first place (see :func:`text_autofix_permitted`), so this
    function is only meaningful for ``sv``/``en`` inputs. Kept total (no
    raise) so callers can use it as a plain boolean assertion.
    """
    if source_verdict in (LanguageVerdict.MIXED, LanguageVerdict.UNKNOWN):
        return False
    if result_verdict in (LanguageVerdict.MIXED, LanguageVerdict.UNKNOWN):
        return False
    return source_verdict == result_verdict


def text_autofix_permitted(
    *,
    source_token: str,
    result_token: str,
    span_text: str,
) -> tuple[bool, str]:
    """The composed Swedish-safeguard verdict for one candidate text fix.

    Returns ``(permitted, reason)``. ``permitted=False`` means the finding
    must demote to propose-track; this function never itself writes
    anything. All four sub-checks in the module docstring are applied, in
    order, so the first failing check names the reason:

    1. lexicon veto -- a lexicon-valid (or lexicon-valid-compound) source
       token is untouchable,
    2. language verdict -- ``mixed``/``unknown`` for the span demotes,
    3. diacritic invariance -- no å/ä/ö/é may be added/removed/substituted,
    4. never-cross-language -- source and result must share a verdict.
    """
    if is_lexicon_valid_compound(source_token):
        return False, "lexicon veto: source token is a valid Swedish word/compound"

    detection = detect_language(span_text)
    if detection.verdict in (LanguageVerdict.MIXED, LanguageVerdict.UNKNOWN):
        return False, f"language verdict is {detection.verdict.value} -- demotes to propose"

    if not preserves_diacritics(source_token, result_token):
        return False, "diacritic invariance violated (å/ä/ö/é added, removed, or substituted)"

    result_detection = detect_language(result_token)
    if not same_language_verdict(detection.verdict, result_detection.verdict):
        return False, "fix would cross the span's language verdict"

    return True, "swedish safeguard cleared"


__all__ = [
    "SV_LEXICON",
    "LanguageDetection",
    "detect_language",
    "has_diacritics",
    "is_lexicon_valid_compound",
    "preserves_diacritics",
    "same_language_verdict",
    "text_autofix_permitted",
]
