#!/usr/bin/env bash
# install_skills.sh — sync .codex/skills/ into ~/.claude/skills/
#
# .codex/skills/ is the single source of truth for all agent skills.
# This script installs them into the Claude Code user skill directory.
#
# Usage:
#   bash scripts/install_skills.sh          # install all skills
#   bash scripts/install_skills.sh --dry-run # show what would change
#
# Run this after pulling changes that touch .codex/skills/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_SRC="$ROOT/.codex/skills"
SKILLS_DST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  echo "[dry-run] No files will be written."
fi

if [[ ! -d "$SKILLS_SRC" ]]; then
  echo "ERROR: Source skill directory not found: $SKILLS_SRC" >&2
  exit 1
fi

mkdir -p "$SKILLS_DST"

installed=0
updated=0
skipped=0

for skill_dir in "$SKILLS_SRC"/*/; do
  skill_name="$(basename "$skill_dir")"
  dst_dir="$SKILLS_DST/$skill_name"

  # Copy each file under the skill directory
  while IFS= read -r -d '' src_file; do
    rel="${src_file#$skill_dir}"
    dst_file="$dst_dir/$rel"

    # Skip if identical
    if [[ -f "$dst_file" ]] && cmp -s "$src_file" "$dst_file"; then
      ((skipped++)) || true
      continue
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
      if [[ -f "$dst_file" ]]; then
        echo "  [update] $skill_name/$rel"
        ((updated++)) || true
      else
        echo "  [new]    $skill_name/$rel"
        ((installed++)) || true
      fi
    else
      mkdir -p "$(dirname "$dst_file")"
      if [[ -f "$dst_file" ]]; then
        cp "$src_file" "$dst_file"
        ((updated++)) || true
      else
        cp "$src_file" "$dst_file"
        ((installed++)) || true
      fi
    fi
  done < <(find "$skill_dir" -type f -print0)
done

echo ""
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Would install: $installed  Would update: $updated  Already up to date: $skipped"
else
  echo "✓ Skills installed to $SKILLS_DST"
  echo "  Installed: $installed  Updated: $updated  Unchanged: $skipped"
fi
