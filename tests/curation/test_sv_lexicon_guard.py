"""#2987 (G2-2) -- the Swedish safeguard (multilingual auto-fix gate).

Spec: ``docs/YGGDRASIL_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §3.

Covers the adversarial SV/EN fixture corpus (compounds, definite suffixes,
code-switching, diacritics, near-English Swedish) named by AC2: every case
must fail ``text_autofix_permitted`` (veto or demotion), never permit an
auto-apply candidate.
"""
from __future__ import annotations

import pytest

from app.curation.findings import LanguageVerdict
from app.curation.sv_lexicon_guard import (
    detect_language,
    has_diacritics,
    is_lexicon_valid_compound,
    preserves_diacritics,
    same_language_verdict,
    text_autofix_permitted,
)


# ---------------------------------------------------------------------------
# Lexicon veto: compounds, definite suffixes, adversarial near-English words
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "sjukvårdsförsäkring",  # compound: sjukvård + försäkring
        "boken",  # definite suffix of "bok"
        "husen",  # definite suffix of "hus"
        "fakta",  # adversarial near-English Swedish
        "snabbt",
        "event",
        "mejl",
    ],
)
def test_lexicon_valid_tokens_are_vetoed(token: str) -> None:
    assert is_lexicon_valid_compound(token) is True


@pytest.mark.parametrize(
    "token,span",
    [
        ("sjukvårdsförsäkring", "Jag har en sjukvårdsförsäkring som täcker allt."),
        ("boken", "Jag läste boken igår kväll."),
        ("husen", "Husen på gatan är gamla och fina."),
        ("fakta", "Detta är fakta, inte åsikter."),
        ("snabbt", "Det gick snabbt att fixa."),
    ],
)
def test_text_autofix_never_permitted_for_lexicon_valid_span(token: str, span: str) -> None:
    permitted, reason = text_autofix_permitted(
        source_token=token, result_token="something-else", span_text=span
    )
    assert permitted is False
    assert "lexicon veto" in reason


# ---------------------------------------------------------------------------
# Code-switching -> mixed verdict -> demotes text.* findings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "span",
    [
        "Jag hade ett great möte today med kunden.",
        "Boka ett meeting med teamet imorgon bitti.",
        "Det var helt fine men vi behöver mer fakta.",
    ],
)
def test_code_switching_span_is_mixed_verdict(span: str) -> None:
    detection = detect_language(span)
    assert detection.verdict == LanguageVerdict.MIXED


def test_mixed_verdict_demotes_text_autofix() -> None:
    span = "Jag hade ett great möte today med kunden."
    # Use a source token that is itself not a lexicon hit, so this test
    # isolates the mixed-language-verdict demotion path from the (separately
    # tested) lexicon-veto path.
    permitted, reason = text_autofix_permitted(
        source_token="kunden", result_token="customer", span_text=span
    )
    assert permitted is False
    assert "mixed" in reason or "demotes" in reason


def test_unknown_verdict_demotes_text_autofix() -> None:
    span = "12345 -- ??? !!!"
    detection = detect_language(span)
    assert detection.verdict == LanguageVerdict.UNKNOWN
    permitted, reason = text_autofix_permitted(
        source_token="xyz123", result_token="abc456", span_text=span
    )
    assert permitted is False


# ---------------------------------------------------------------------------
# Diacritic invariance: å/ä/ö/é never touched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,result",
    [
        ("dör", "dor"),  # removes ö
        ("kaffe", "kaffé"),  # adds é
        ("hår", "har"),  # removes å
        ("för", "for"),  # removes ö
    ],
)
def test_diacritic_removal_or_addition_is_never_preserved(source: str, result: str) -> None:
    assert preserves_diacritics(source, result) is False


@pytest.mark.parametrize(
    "source,result",
    [
        ("hår", "här"),  # å -> ä substitution, still a diacritic-bearing token
        ("stol", "stoll"),  # no diacritics involved either side -- preserved trivially
    ],
)
def test_diacritic_set_change_or_no_diacritics_both_covered(source: str, result: str) -> None:
    # "hår" -> "här": diacritic present in both but the *set* of diacritic
    # characters differs (å vs ä), which is exactly the substitution case
    # this check is designed to catch.
    if has_diacritics(source) or has_diacritics(result):
        assert preserves_diacritics(source, result) is False
    else:
        assert preserves_diacritics(source, result) is True


def test_diacritic_invariance_blocks_autofix_even_with_clean_language_verdict() -> None:
    span = "Det är dags att gå hem nu."
    permitted, reason = text_autofix_permitted(
        source_token="gå", result_token="ga", span_text=span
    )
    assert permitted is False


# ---------------------------------------------------------------------------
# Never-cross-language assertion
# ---------------------------------------------------------------------------


def test_same_language_verdict_true_for_matching_sv() -> None:
    assert same_language_verdict(LanguageVerdict.SV, LanguageVerdict.SV) is True


def test_same_language_verdict_false_across_languages() -> None:
    assert same_language_verdict(LanguageVerdict.SV, LanguageVerdict.EN) is False


@pytest.mark.parametrize("verdict", [LanguageVerdict.MIXED, LanguageVerdict.UNKNOWN])
def test_same_language_verdict_never_true_for_mixed_or_unknown(verdict: LanguageVerdict) -> None:
    assert same_language_verdict(verdict, verdict) is False


def test_cross_language_fix_never_permitted() -> None:
    # An English span whose token gets "corrected" toward Swedish -- should
    # fail even if this specific token isn't itself a lexicon word (the
    # never-cross-language assertion is independent of the veto check).
    span = "This event was great and well organized."
    permitted, reason = text_autofix_permitted(
        source_token="organized", result_token="organiserad", span_text=span
    )
    assert permitted is False
