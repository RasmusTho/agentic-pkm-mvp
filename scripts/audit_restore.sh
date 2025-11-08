set -euo pipefail
while read TARGET; do
  safe="${TARGET//\//_}"
  if [ -s ".git/audit/selective.${safe}.restore.txt" ]; then
    git switch "$TARGET"
    xargs -I{} git checkout origin/main -- "{}" < ".git/audit/selective.${safe}.restore.txt"
    git add -A
    git commit -m "fix: selectively restore necessary files vs origin/main" || true
  fi
done <<EOF
main
chore/ingest-export-fixes
chore/merge-rrf-ingest-fixes
chore/outbox-compat
chore/interesting-exports
EOF
