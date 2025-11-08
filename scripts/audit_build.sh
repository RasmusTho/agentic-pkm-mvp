set -euo pipefail
git fetch --all --prune
mkdir -p .git/audit/branches .git/audit/selective
git ls-tree -r --name-only origin/main | sort > .git/audit/origin_main.txt
git ls-tree -r --name-only HEAD | sort > .git/audit/head.txt
printf "%s\n" "chore/repo-hygiene+ci-guard" "main" "chore/ingest-export-fixes" "chore/merge-rrf-ingest-fixes" "chore/outbox-compat" "chore/interesting-exports" > .git/audit/targets.txt
while read br; do safe="${br//\//_}"; git ls-tree -r --name-only "origin/${br#origin/}" >/dev/null 2>&1 || true; done < .git/audit/targets.txt
while read br; do safe="${br//\//_}"; git ls-tree -r --name-only "$br" | sort > ".git/audit/branches/${safe}.txt" || git ls-tree -r --name-only "origin/${br#origin/}" | sort > ".git/audit/branches/${safe}.txt" || true; done < .git/audit/targets.txt
while read br; do
  safe="${br//\//_}"
  a=".git/audit/branches/${safe}.txt"
  b=".git/audit/origin_main.txt"
  comm -23 "$b" "$a" > ".git/audit/missing_vs_main.${safe}.txt" || true
  awk '1' ".git/audit/missing_vs_main.${safe}.txt" > ".git/audit/selective.${safe}.all.txt"
  grep -E '^(app/|tests/|scripts/|docs/(ARCHITECTURE\.md|ROADMAP\.md|STATUS\.md)|\.github/workflows/|Makefile|pyproject\.toml|requirements\.txt|dev-requirements\.txt|alembic/|docker-compose\.ya?ml)' ".git/audit/selective.${safe}.all.txt" > ".git/audit/selective.${safe}.candidates.txt" || true
  grep -Ev '(^docs/diagrams/old/|^experiments/|^notebooks/|^legacy/|^tmp/|^samples?/|^playground/|\.bak$|\.old$|\.tmp$)' ".git/audit/selective.${safe}.candidates.txt" > ".git/audit/selective.${safe}.candidates.filtered.txt" || true
  cp ".git/audit/selective.${safe}.candidates.filtered.txt" ".git/audit/selective.${safe}.restore.txt" || true
done < .git/audit/targets.txt
