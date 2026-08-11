"""Pure routing rules for the docs-guard temporal-owner check."""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType
import unicodedata


DOCUMENTATION_PREFIXES = (
    "docs/",
    ".codex/skills/",
    ".codex/agents/",
    "companion-ui/docs/",
    "companion-ui/design_handoff/",
)
DOCUMENTATION_SUFFIXES = (".md", ".mdx", ".rst")

# Closed-class markers are intentionally deterministic and dependency-free.
# They identify a document whose primary prose is non-English; they are not a
# grammar checker. A bounded foreign-language example in an otherwise-English
# document stays below the file-level threshold.
_ENGLISH_MARKERS = frozenset(
    """
    the and that this with from for not is are was were shall should could will
    would to of a an in on as by be been being it its these those they them
    their we you your our or but if then when where what how also must need
    through after before without under over every between because therefore
    """.split()
)
_NON_ENGLISH_MARKERS = MappingProxyType(
    {
        "swedish": frozenset(
            """
            och att det som för med inte är ska från den ett på av var hade
            detta denna dessa man vi du jag vad hur när där här sig sin sitt
            sina eller men också måste behöver blir blev genom efter före utan
            över mycket varje mellan eftersom därför
            """.split()
        ),
        "german": frozenset(
            """
            der die das und ist sind nicht mit für von zu auf ein eine einer
            einem als auch werden wird kann soll muss bei aus dem den des im
            über oder aber wenn wie was wo durch nach vor ohne zwischen weil
            daher
            """.split()
        ),
        "french": frozenset(
            """
            le la les un une des et est sont pas avec pour dans de du au aux ce
            cette ces que qui sur par comme aussi peut doit nous vous ils elles
            mais ou si quand où comment pourquoi après avant sans entre parce
            donc
            """.split()
        ),
        "spanish": frozenset(
            """
            el la los las un una unos unas y es son no con para en de del al
            este esta estos estas que quien sobre por como también puede debe
            nosotros ustedes ellos ellas pero o si cuando donde cómo porque
            después antes sin entre
            """.split()
        ),
        "italian": frozenset(
            """
            il lo la i gli le un una e è sono non con per in di del al questo
            questa questi queste che chi su da come anche può deve noi voi loro
            ma o se quando dove perché dopo prima senza tra quindi
            """.split()
        ),
        "dutch": frozenset(
            """
            de het een en is zijn niet met voor van naar op als ook worden
            wordt kan moet bij uit deze dit die dat wij jullie zij maar of
            wanneer waar hoe waarom na vóór zonder tussen omdat daarom
            """.split()
        ),
    }
)
_FENCED_BLOCK_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_NON_PROSE_RE = re.compile(r"`[^`\n]+`|https?://\S+|<!--.*?-->", re.DOTALL)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_MIN_NON_ENGLISH_MARKERS = 8
_MIN_NON_ENGLISH_SHARE = 0.35
_MIN_NON_LATIN_LETTERS = 20
_MIN_NON_LATIN_SHARE = 0.30

TEMPORAL_DOCS = frozenset(
    {
        "docs/STATUS.md",
        "docs/ROADMAP.md",
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
        "docs/HUMAN-FLOWS.md",
        "docs/AGENT-FLOWS.md",
    }
)
TEMPORAL_CODE_PREFIXES = ("app/", "scripts/", "config/", "docs/settings/")
# Maps each governance-only enforcement script to its docs/development/ owner
# doc. None means no doc has been assigned yet for that script: it falls back
# to accepting any docs/development/ touch (the pre-existing, looser
# behavior) instead of a false claim of a specific pairing that doesn't exist.
GOVERNANCE_TEMPORAL_ENFORCEMENT = MappingProxyType(
    {
        "scripts/docs_guard.py": None,
        "scripts/docs_guard_logic.py": None,
        "scripts/git_hygiene.py": None,
        "scripts/select_pr_tests.py": "docs/development/TEST_STRATEGY_HOT_PATH.md",
    }
)


def is_governed_documentation_path(path: str) -> bool:
    """Return whether a tracked path is repository documentation.

    Product/vault content and test corpora are deliberately outside this
    Builder System policy even when they use Markdown; multilingual content is
    part of their behavior. Repository documentation is the owner/governance,
    skill, companion-doc, and design-handoff surface named here.
    """

    if not path.endswith(DOCUMENTATION_SUFFIXES):
        return False
    return "/" not in path or path.startswith(DOCUMENTATION_PREFIXES)


def _primary_non_english_language(text: str) -> tuple[str, int, int, float] | None:
    prose = _NON_PROSE_RE.sub(" ", _FENCED_BLOCK_RE.sub(" ", text))
    tokens = [token.lower() for token in _WORD_RE.findall(prose)]
    english_hits = sum(token in _ENGLISH_MARKERS for token in tokens)
    language, non_english_hits = max(
        (
            (name, sum(token in markers for token in tokens))
            for name, markers in _NON_ENGLISH_MARKERS.items()
        ),
        key=lambda item: item[1],
    )
    marker_total = english_hits + non_english_hits
    non_english_share = non_english_hits / marker_total if marker_total else 0.0
    if (
        non_english_hits >= _MIN_NON_ENGLISH_MARKERS
        and non_english_share >= _MIN_NON_ENGLISH_SHARE
    ):
        return language, non_english_hits, english_hits, non_english_share

    letters = [character for character in prose if character.isalpha()]
    non_latin_letters = sum(
        "LATIN" not in unicodedata.name(character, "") for character in letters
    )
    non_latin_share = non_latin_letters / len(letters) if letters else 0.0
    if (
        non_latin_letters >= _MIN_NON_LATIN_LETTERS
        and non_latin_share >= _MIN_NON_LATIN_SHARE
    ):
        return (
            "non_latin",
            non_latin_letters,
            len(letters) - non_latin_letters,
            non_latin_share,
        )
    return None


def non_english_documentation(
    paths: list[str], *, root: str = "."
) -> list[dict[str, object]]:
    """Return deterministic evidence for governed docs whose primary prose is not English."""

    base = Path(root)
    violations: list[dict[str, object]] = []
    for path in sorted(paths):
        if not is_governed_documentation_path(path):
            continue
        verdict = _primary_non_english_language(
            (base / path).read_text(encoding="utf-8", errors="replace")
        )
        if verdict is None:
            continue
        language, non_english_hits, english_hits, share = verdict
        violations.append(
            {
                "path": path,
                "detected_primary_language": language,
                "non_english_markers": non_english_hits,
                "english_markers": english_hits,
                "non_english_share": round(share, 3),
            }
        )
    return violations


def requires_temporal_owner_doc(changed: list[str]) -> bool:
    """Return true unless a changed temporal surface has an owner-doc writeback.

    A governance-only change to one of these enforcement scripts may use its
    `docs/development/` contract as the owner writeback. Presence of governance
    files is insufficient: every changed temporal surface must be one of those
    scripts, so a mixed runtime/config PR cannot inherit the exception. A
    script with an explicit paired doc in GOVERNANCE_TEMPORAL_ENFORCEMENT
    requires that exact doc; a script mapped to None accepts any
    docs/development/ touch until its own contract doc is assigned.
    """

    temporal_paths = [
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in TEMPORAL_CODE_PREFIXES)
    ]
    if not temporal_paths or any(path in TEMPORAL_DOCS for path in changed):
        return False

    governance_only = all(
        path in GOVERNANCE_TEMPORAL_ENFORCEMENT for path in temporal_paths
    )
    if not governance_only:
        return True

    any_development_doc_touched = any(
        path.startswith("docs/development/") for path in changed
    )

    def owner_doc_satisfied(path: str) -> bool:
        owner_doc = GOVERNANCE_TEMPORAL_ENFORCEMENT[path]
        if owner_doc is None:
            return any_development_doc_touched
        return owner_doc in changed

    owner_docs_satisfied = all(owner_doc_satisfied(path) for path in temporal_paths)
    return not owner_docs_satisfied
