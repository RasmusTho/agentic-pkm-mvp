#!/usr/bin/env bash
# install_skills.sh — sync repo-local and registered portable skills into ~/.claude/skills/
#
# .codex/skills/ is the source of truth for repo-local skills. Portable method
# skills remain in their external source root and are registered by name in
# .codex/skills/portable-skills.list. This script installs both sets into the
# Claude Code user skill directory without vendoring portable method text.
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
PORTABLE_SKILLS_MANIFEST="$SKILLS_SRC/portable-skills.list"
PORTABLE_SKILLS_SRC="${PKM_PORTABLE_SKILLS_DIR:-$HOME/.local/share/agent-skills}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  echo "[dry-run] No files will be written."
fi

if [[ ! -d "$SKILLS_SRC" ]]; then
  echo "ERROR: Source skill directory not found: $SKILLS_SRC" >&2
  exit 1
fi

if [[ ! -f "$PORTABLE_SKILLS_MANIFEST" ]]; then
  echo "ERROR: Portable skill registry not found: $PORTABLE_SKILLS_MANIFEST" >&2
  exit 1
fi

mkdir -p "$SKILLS_DST"

installed=0
updated=0
skipped=0

install_skill_dir() {
  local skill_dir="$1"
  local skill_name="$2"
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
}

for skill_dir in "$SKILLS_SRC"/*/; do
  skill_name="$(basename "$skill_dir")"
  install_skill_dir "$skill_dir" "$skill_name"
done

while IFS= read -r skill_name || [[ -n "$skill_name" ]]; do
  [[ -z "$skill_name" || "$skill_name" == \#* ]] && continue
  if [[ ! "$skill_name" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ ]]; then
    echo "ERROR: Invalid portable skill name in $PORTABLE_SKILLS_MANIFEST: $skill_name" >&2
    exit 1
  fi
  if [[ -d "$SKILLS_SRC/$skill_name" ]]; then
    echo "ERROR: Portable skill collides with repo-local skill: $skill_name" >&2
    exit 1
  fi

  portable_skill_dir="$PORTABLE_SKILLS_SRC/$skill_name/"
  if [[ ! -f "$portable_skill_dir/SKILL.md" ]]; then
    echo "ERROR: Registered portable skill is unavailable: $skill_name" >&2
    echo "Provision it under $PORTABLE_SKILLS_SRC or set PKM_PORTABLE_SKILLS_DIR." >&2
    exit 1
  fi
  install_skill_dir "$portable_skill_dir" "$skill_name"
done < "$PORTABLE_SKILLS_MANIFEST"

echo ""
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Would install: $installed  Would update: $updated  Already up to date: $skipped"
else
  echo "✓ Skills installed to $SKILLS_DST"
  echo "  Installed: $installed  Updated: $updated  Unchanged: $skipped"
fi
