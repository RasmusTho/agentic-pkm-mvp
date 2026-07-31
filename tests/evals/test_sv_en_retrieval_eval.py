"""SV/EN retrieval eval — fixture integrity, scorecard truth, and live reproduction (G3-2, #2985).

Three layers, deliberately separated so the eval is honest about what CI can prove:

1. **Fixture integrity** (always runs, no Ollama): the corpus is synthetic and canonically tagged,
   every labelled gold/pair id resolves to a real document, and the label set is not degenerate.
2. **Scorecard truth** (always runs, no Ollama): the committed scorecard actually covers the
   committed fixtures — both identities over the full labelled query set, fusion held fixed for the
   identity comparison — and the eval note's recommendation matches the numbers it cites.
3. **Live reproduction** (skipped without an Ollama host carrying both models): re-runs the harness
   end to end and re-derives the scorecard's headline finding from live embeddings.

Layer 3 is what makes the scorecard reproducible rather than asserted. CI has no Ollama host, so it
skips there and runs on any embedding host (mac mini / test channel, or a laptop with both models
pulled).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.evals._helpers import value_family
from tests.evals.sv_en_retrieval import (
    CORPUS_DIR,
    IDENTITIES,
    QUERY_CLASSES,
    RECALL_KS,
    IdentityRun,
    identities_available,
    load_connect_pairs,
    load_corpus,
    load_query_set,
    load_scorecard,
    recall_at_k,
    reciprocal_rank,
)

EVAL_NOTE = Path(__file__).resolve().parent / "SV_EN_RETRIEVAL_EVAL_G3_2.md"

IDENTITY_COMPARISON_RUNS = ("nomic/linear", "bge_m3/linear")
FUSION_COMPARISON_RUNS = ("bge_m3/linear", "bge_m3/rrf")


# ---------------------------------------------------------------------------------------
# 1. Fixture integrity
# ---------------------------------------------------------------------------------------


def test_corpus_is_synthetic_and_canonically_tagged() -> None:
    source_roles = set(value_family("source_role"))
    authority_states = set(value_family("authority_state"))
    evidence_roles = set(value_family("evidence_role"))
    sensitivities = set(value_family("sensitivity"))
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

    docs = load_corpus()
    assert len(docs) >= 16, "corpus too small to score recall@5 meaningfully"
    for doc in docs:
        assert doc.meta.get("synthetic") == "true", f"{doc.doc_id} must declare synthetic: true"
        assert doc.lang in {"sv", "en"}, f"{doc.doc_id} has no sv/en lang tag"
        assert doc.topic, f"{doc.doc_id} has no topic tag"
        assert doc.meta["source_role"] in source_roles
        assert doc.meta["authority_state"] in authority_states
        assert doc.meta["evidence_role"] in evidence_roles
        assert doc.meta["sensitivity"] in sensitivities
        assert not email.search(doc.text), f"{doc.doc_id} contains an email-like identifier"


def test_each_labelled_topic_has_both_languages() -> None:
    """A cross-lingual gold label is only meaningful when the topic exists in both languages."""
    docs = load_corpus()
    by_topic: dict[str, set[str]] = {}
    for doc in docs:
        by_topic.setdefault(doc.topic, set()).add(doc.lang)

    labelled_topics = {entry["topic"] for entry in load_query_set()["queries"]}
    assert len(labelled_topics) >= 8, "too few labelled topics for a per-class breakdown"
    for topic in labelled_topics:
        assert by_topic.get(topic) == {"sv", "en"}, f"topic {topic} is not covered in both languages"

    distractors = set(by_topic) - labelled_topics
    assert distractors, "the corpus needs unlabelled distractor topics or recall is trivially high"


def test_query_set_labels_resolve_and_cover_every_class() -> None:
    doc_ids = {doc.doc_id for doc in load_corpus()}
    queries = load_query_set()["queries"]
    assert len({entry["id"] for entry in queries}) == len(queries), "duplicate query ids"

    seen_classes: dict[str, int] = {}
    for entry in queries:
        assert entry["class"] in QUERY_CLASSES, f"{entry['id']} has an unknown class"
        assert entry["query"].strip(), f"{entry['id']} has an empty query"
        assert entry["gold"], f"{entry['id']} has no gold label"
        unknown = set(entry["gold"]) - doc_ids
        assert not unknown, f"{entry['id']} golds unknown documents {sorted(unknown)}"
        seen_classes[entry["class"]] = seen_classes.get(entry["class"], 0) + 1

    assert set(seen_classes) == set(QUERY_CLASSES), f"missing query classes: {seen_classes}"
    assert min(seen_classes.values()) >= 5, f"each class needs enough queries to mean anything: {seen_classes}"


def test_cross_lingual_gold_is_the_other_language_document() -> None:
    """The class only measures what it claims if the gold is never the query's own language."""
    by_id = {doc.doc_id: doc for doc in load_corpus()}
    for entry in load_query_set()["queries"]:
        if entry["class"] != "cross_lingual":
            continue
        gold_langs = {by_id[gold].lang for gold in entry["gold"]}
        assert len(gold_langs) == 1, f"{entry['id']} golds mixed languages"
        same_language_sibling = [
            doc.doc_id
            for doc in by_id.values()
            if doc.topic == entry["topic"] and doc.doc_id not in entry["gold"]
        ]
        assert same_language_sibling, (
            f"{entry['id']} has no same-topic competitor, so the class is not actually cross-lingual"
        )


def test_connect_pair_labels_resolve_and_include_hard_negatives() -> None:
    doc_ids = {doc.doc_id for doc in load_corpus()}
    by_id = {doc.doc_id: doc for doc in load_corpus()}
    spec = load_connect_pairs()

    related = [tuple(pair) for pair in spec["related_pairs"]]
    negatives = [tuple(pair) for pair in spec["hard_negative_pairs"]]
    assert related and negatives, "a pair set without hard negatives flatters every identity"

    for pair in related + negatives:
        assert len(pair) == 2 and pair[0] != pair[1], f"malformed pair {pair}"
        unknown = set(pair) - doc_ids
        assert not unknown, f"pair {pair} references unknown documents {sorted(unknown)}"

    for pair in related:
        assert by_id[pair[0]].topic == by_id[pair[1]].topic, f"related pair {pair} spans topics"
        assert {by_id[pair[0]].lang, by_id[pair[1]].lang} == {"sv", "en"}, (
            f"related pair {pair} is not an SV/EN pair"
        )
    for pair in negatives:
        assert by_id[pair[0]].topic != by_id[pair[1]].topic, f"hard negative {pair} is same-topic"

    assert not (set(map(frozenset, related)) & set(map(frozenset, negatives))), (
        "a pair cannot be labelled both related and unrelated"
    )
    assert spec["finding_shape"]["source"].startswith("app/expansion/connect.py"), (
        "the connect section must name the real E3 finding shape it reproduces"
    )


# ---------------------------------------------------------------------------------------
# 2. Scorecard truth
# ---------------------------------------------------------------------------------------


def test_query_set_is_labelled_and_scored_under_both_identities() -> None:
    """AC1: the labelled SV/EN query set is scored with recall@k + MRR under both identities.

    Fusion is held fixed at the shipped default across the identity comparison, so the embedding
    identity is the only moving part between those two runs.
    """
    scorecard = load_scorecard()
    queries = load_query_set()["queries"]
    runs = scorecard["runs"]

    for label in IDENTITY_COMPARISON_RUNS:
        assert label in runs, f"scorecard is missing the {label} run"

    compared = {runs[label]["identity"]["key"] for label in IDENTITY_COMPARISON_RUNS}
    assert compared == set(IDENTITIES), f"identity comparison must cover both identities, got {compared}"

    fusions = {runs[label]["fusion"] for label in IDENTITY_COMPARISON_RUNS}
    assert fusions == {"linear"}, f"fusion must be held fixed for the identity comparison, got {fusions}"

    for label in IDENTITY_COMPARISON_RUNS:
        run = runs[label]
        spec = IDENTITIES[run["identity"]["key"]]
        assert run["identity"]["model"] == spec["model"]
        assert run["identity"]["dim"] == spec["dim"], "the run must record the real vector width"

        retrieval = run["retrieval"]
        assert len(retrieval["per_query"]) == len(queries), f"{label} did not score every query"
        assert {row["id"] for row in retrieval["per_query"]} == {q["id"] for q in queries}

        for section in (retrieval["overall"], *retrieval["by_class"].values()):
            for k in RECALL_KS:
                assert 0.0 <= section["recall"][f"@{k}"] <= 1.0
            assert 0.0 <= section["mrr"] <= 1.0
        assert set(retrieval["by_class"]) == set(QUERY_CLASSES), "missing a per-class breakdown"

        # Every per-query row must be internally consistent with its own ranking, so a scorecard
        # cannot carry a headline number its rows do not support.
        for row in retrieval["per_query"]:
            for k in RECALL_KS:
                assert row["recall"][f"@{k}"] == pytest.approx(
                    recall_at_k(row["ranked"], row["gold"], k), abs=1e-4
                ), f"{label} {row['id']} recall@{k} does not match its own ranking"
            assert row["rr"] == pytest.approx(
                reciprocal_rank(row["ranked"], row["gold"]), abs=1e-4
            ), f"{label} {row['id']} reciprocal rank does not match its own ranking"


def test_connect_precision_scored_on_labelled_pairs() -> None:
    """AC2: an Expansion-quality section scores connect precision on the labelled SV/EN pair set."""
    scorecard = load_scorecard()
    spec = load_connect_pairs()
    related_count = len(spec["related_pairs"])

    for label in IDENTITY_COMPARISON_RUNS:
        section = scorecard["runs"][label]["connect_precision"]
        assert section["labelled_related_pairs"] == related_count, (
            f"{label} scored a different pair set than the committed one"
        )
        assert 0.0 <= section["precision"] <= 1.0
        assert 0.0 <= section["recall"] <= 1.0
        assert section["true_positives"] <= section["proposed_pairs"]
        assert section["true_positives"] <= related_count
        if section["proposed_pairs"]:
            assert section["precision"] == pytest.approx(
                section["true_positives"] / section["proposed_pairs"], abs=1e-4
            )
        assert section["recall"] == pytest.approx(
            section["true_positives"] / related_count, abs=1e-4
        )
        assert len(section["missed_related_pairs"]) == related_count - section["true_positives"]


def test_committed_scorecard_matches_committed_fixtures() -> None:
    """AC3: the committed scorecard describes the committed fixture set, not a stale one."""
    scorecard = load_scorecard()
    docs = load_corpus()
    queries = load_query_set()["queries"]
    pairs = load_connect_pairs()

    assert scorecard["schema"] == "sv_en_retrieval_scorecard.v1"
    assert scorecard["issue"] == 2985
    assert scorecard["runner"] == "scripts/eval_sv_en_retrieval.py"
    assert (Path(__file__).resolve().parents[2] / scorecard["runner"]).is_file(), (
        "the scorecard names a runner that does not exist"
    )

    assert scorecard["corpus"]["docs"] == len(docs)
    assert scorecard["corpus"]["sv_docs"] == sum(1 for doc in docs if doc.lang == "sv")
    assert scorecard["corpus"]["en_docs"] == sum(1 for doc in docs if doc.lang == "en")
    assert scorecard["corpus"]["topics"] == sorted({doc.topic for doc in docs})

    assert scorecard["query_set"]["queries"] == len(queries)
    for cls in QUERY_CLASSES:
        assert scorecard["query_set"]["by_class"][cls] == sum(1 for q in queries if q["class"] == cls)

    assert scorecard["connect_pair_set"]["related_pairs"] == len(pairs["related_pairs"])
    assert scorecard["connect_pair_set"]["hard_negative_pairs"] == len(pairs["hard_negative_pairs"])
    assert scorecard["connect_pair_set"]["seed_queries"] == len(pairs["seed_queries"])

    doc_ids = {doc.doc_id for doc in docs}
    for label, run in scorecard["runs"].items():
        for row in run["retrieval"]["per_query"]:
            unknown = set(row["ranked"]) - doc_ids
            assert not unknown, f"{label} {row['id']} ranked documents not in the corpus: {sorted(unknown)}"


def test_eval_note_states_g5_fusion_recommendation() -> None:
    """AC4: the eval note states a G5 default-fusion recommendation grounded in the scored numbers."""
    assert EVAL_NOTE.is_file(), "the eval note is missing"
    note = EVAL_NOTE.read_text(encoding="utf-8")

    assert "## G5 default-fusion recommendation" in note, "the note has no recommendation section"
    recommendation = note.split("## G5 default-fusion recommendation", 1)[1]
    assert re.search(r"\blinear\b", recommendation, re.I), "the recommendation names no fusion strategy"
    assert re.search(r"\brrf\b", recommendation, re.I), "the recommendation does not weigh RRF"

    scorecard = load_scorecard()
    linear = scorecard["runs"]["bge_m3/linear"]["retrieval"]["overall"]["mrr"]
    rrf = scorecard["runs"]["bge_m3/rrf"]["retrieval"]["overall"]["mrr"]

    # The recommendation must follow the numbers, not the other way round: whichever fusion the note
    # recommends keeping as default must be the one the scorecard actually favours.
    recommends_linear = bool(re.search(r"keep\s+`?linear`?", recommendation, re.I))
    recommends_rrf = bool(re.search(r"flip.*\brrf\b|adopt\s+`?rrf`?", recommendation, re.I))
    assert recommends_linear != recommends_rrf, "the note must recommend exactly one default"
    if recommends_linear:
        assert linear >= rrf, "the note recommends linear but the scorecard favours RRF"
    else:
        assert rrf > linear, "the note recommends RRF but the scorecard does not support it"

    # Every number the note cites in its headline table must appear in the scorecard, so the note
    # cannot drift away from the evidence it claims to rest on.
    for label in ("nomic/linear", "bge_m3/linear", "bge_m3/rrf"):
        assert label in note, f"the note does not cite the {label} run"
        overall = scorecard["runs"][label]["retrieval"]["overall"]
        assert f"{overall['mrr']:.4f}".rstrip("0").rstrip(".") in note or str(overall["mrr"]) in note, (
            f"the note does not cite the {label} overall MRR"
        )


# ---------------------------------------------------------------------------------------
# 3. Live reproduction
# ---------------------------------------------------------------------------------------


@pytest.mark.skipif(
    not identities_available(),
    reason="needs an Ollama host with both nomic-embed-text and bge-m3 pulled",
)
def test_live_run_reproduces_the_cross_lingual_finding() -> None:
    """The scorecard's headline finding re-derives from live embeddings, not from the JSON.

    The finding: with fusion held fixed, the BGE-M3 identity retrieves the other-language document
    for cross-lingual queries and the nomic identity does not. Asserted as a strict ordering rather
    than against pinned constants, so ordinary model-version drift does not make this test lie.
    """
    cross_lingual = [q for q in load_query_set()["queries"] if q["class"] == "cross_lingual"]
    assert cross_lingual

    hits: dict[str, int] = {}
    for identity_key in ("nomic", "bge_m3"):
        with IdentityRun(identity_key, "linear") as run:
            hits[identity_key] = sum(
                1
                for entry in cross_lingual
                if set(run.ranked(entry["query"], k=max(RECALL_KS))) & set(entry["gold"])
            )

    assert hits["bge_m3"] > hits["nomic"], (
        f"expected BGE-M3 to beat nomic on cross-lingual retrieval, got {hits}"
    )


@pytest.mark.skipif(
    not identities_available(),
    reason="needs an Ollama host with both nomic-embed-text and bge-m3 pulled",
)
def test_live_corpus_embeds_at_the_declared_dimensions() -> None:
    """Each identity really produces the vector width the scorecard records."""
    scorecard = load_scorecard()
    for identity_key, spec in IDENTITIES.items():
        with IdentityRun(identity_key, "linear") as run:
            identity = run.resolved_identity
            assert getattr(identity, "model") == spec["model"]
            assert getattr(identity, "dim") == spec["dim"]
        recorded = next(
            run_data["identity"]
            for run_data in scorecard["runs"].values()
            if run_data["identity"]["key"] == identity_key
        )
        assert recorded["dim"] == spec["dim"]


def test_scorecard_json_is_committed_and_parseable() -> None:
    path = CORPUS_DIR.parent / "scorecard.json"
    assert path.is_file(), "the eval must commit its scorecard so the note has a reproducible source"
    json.loads(path.read_text(encoding="utf-8"))
