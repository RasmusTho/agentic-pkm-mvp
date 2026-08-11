State: Development reference. Not an auto-loaded instruction file.
Owner: Builder System governance

# Documentation Guard Contract

`scripts/docs_guard.py` is the repository's deterministic documentation
fitness command. It first evaluates every tracked Markdown, MDX, and reST
file through `scripts/docs_guard_logic.py :: non_english_documentation`.
The policy applies to repository documentation and builder guidance, but
excludes Product/vault content and multilingual test corpora. It removes
fenced and inline code, URLs, comments, and explicitly labelled localization
tables before using closed-class language markers; it is a fitness heuristic,
not general language identification.

`python3 scripts/docs_guard.py --language-only` runs only that repository-wide
language policy. Without the flag, the command also compares `HEAD` with the
pull-request base (`GITHUB_BASE_REF`, or `origin/main` when unset). An `app/`
change needs a documentation, API, event, or settings writeback. A temporal
code/config change needs one of the high-risk temporal owner documents.
`DOCS_GUARD_ALLOW_TEMPORAL_SKIP=1` is the explicit, narrow override for the
latter check; it does not bypass the language policy.

## Temporal-owner enforcement rules

`scripts/docs_guard_logic.py` owns the pure path and language-routing rules
consumed by the runner. Its `GOVERNANCE_TEMPORAL_ENFORCEMENT` mapping is a
deliberate exception for governance-only enforcement scripts: each listed
script has to change with its named `docs/development/` contract. An unrelated
development document is not sufficient, and mixing a non-governance temporal
path into the same change still requires the normal high-risk temporal owner
document.

This document is the paired owner contract for both `scripts/docs_guard.py`
and `scripts/docs_guard_logic.py`. When either script's policy, base/diff
handling, documentation scope, language heuristic, or temporal-owner routing
changes, update this document in the same pull request. The executable
regressions are `tests/scripts/test_docs_guard.py`.

## Validation

Run `pytest tests/scripts/test_docs_guard.py -q` for the production-path
guard contract, and run `GITHUB_BASE_REF=origin/main python3
scripts/docs_guard.py` before publishing changes to this enforcement surface.
