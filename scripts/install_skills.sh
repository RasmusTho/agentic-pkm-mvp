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

# Resolve the portable registry through the same parser the repo lint uses, then
# prove every registered source before the first target-directory mutation.
# A missing dependency must not leave a newly installed owner-decision profile
# that cannot execute its required method.
if ! portable_skill_names="$(
  python3 "$ROOT/scripts/lint_skills_consistency.py" \
    --root "$ROOT" --print-portable-skills
)"; then
  echo "$portable_skill_names" >&2
  exit 1
fi

while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue
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
done <<< "$portable_skill_names"

mkdir -p "$SKILLS_DST"

installed=0
updated=0
skipped=0

install_skill_dir() {
  local skill_dir="$1"
  local skill_name="$2"
  local dst_dir="$SKILLS_DST/$skill_name"
  local file_list
  local src_file
  local rel
  local dst_file
  local install_failed=0

  file_list="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-install-skills.XXXXXX")"

  # Bash 3.2 does not propagate a failed process substitution into the while
  # loop's status. Enumerate in a foreground command so source traversal must
  # succeed before any file from this skill is copied.
  if ! find "$skill_dir" -type f -print0 > "$file_list"; then
    echo "ERROR: Unable to enumerate source skill: $skill_name" >&2
    rm -f "$file_list"
    return 1
  fi

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
      if ! mkdir -p "$(dirname "$dst_file")"; then
        install_failed=1
        break
      fi
      if [[ -f "$dst_file" ]]; then
        if ! cp "$src_file" "$dst_file"; then
          install_failed=1
          break
        fi
        ((updated++)) || true
      else
        if ! cp "$src_file" "$dst_file"; then
          install_failed=1
          break
        fi
        ((installed++)) || true
      fi
    fi
  done < "$file_list"

  rm -f "$file_list"
  if [[ $install_failed -ne 0 ]]; then
    echo "ERROR: Failed to install skill: $skill_name" >&2
    return 1
  fi
}

# Portable dependencies must be completely installed before repo-local
# profiles that may require them become active in the target directory.
while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue
  portable_skill_dir="$PORTABLE_SKILLS_SRC/$skill_name/"
  install_skill_dir "$portable_skill_dir" "$skill_name"
done <<< "$portable_skill_names"

for skill_dir in "$SKILLS_SRC"/*/; do
  skill_name="$(basename "$skill_dir")"
  install_skill_dir "$skill_dir" "$skill_name"
done

echo ""
if [[ $DRY_RUN -eq 1 ]]; then
  echo "Would install: $installed  Would update: $updated  Already up to date: $skipped"
else
  echo "✓ Skills installed to $SKILLS_DST"
  echo "  Installed: $installed  Updated: $updated  Unchanged: $skipped"
fi
