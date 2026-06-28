# Handoff — chore/companion-ui-ux-audit
Goal:      Land Companion UI UX-audit fixes as PR #2612 (Fixes #2609), rebased onto origin/main
Issue/PR:  PR #2612; issues #2609 (tracking), #2610 (NAV-2), #2611 (NAV-3)
Now:       Rebase onto #2596 DONE + pushed (head d7006308). PR mergeable=true. Waiting on CI.
Next:      Watch CI: pr-contract (added BuilderOps Routing → should pass), smoke, not-pg, companion-ui-browser-runtime, CodeQL. Then Codex review. Merge is owner-gated.
Decisions: Kept #2596's _split_table_row (merged); my _table_alignments + relaxed separator + scroll wrapper + NAV-1 + ST-1/2/3 on top. MD-7 credited to #2596 in the doc.
Watch out: branch is ~7 behind main (no conflicts; new commits don't touch my files). Don't merge without CI green + Codex + owner OK.
Last test: companion_ui 1785 passed, 5 skipped (rebased branch).
