#!/usr/bin/env bash
# Shows all file changes in this repo, categorized by type.
# Designed to surface anything Claude changed that wasn't explicitly requested.
#
# Usage:
#   ./scripts/audit-changes.sh              # since last non-backup commit
#   ./scripts/audit-changes.sh <ref>        # since specific commit/branch/tag
#   ./scripts/audit-changes.sh --uncommitted # only working-tree changes
#
# "Backup commits" are Claude session-backup auto-commits (message starts with
# "Claude session backup:"). The default baseline skips over all of those to
# find the last commit that represents intentional human-approved work.

set -euo pipefail

BOLD='\033[1m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
RESET='\033[0m'

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ── helpers ──────────────────────────────────────────────────────────────────

categorize() {
  local f="$1"
  case "$f" in
    backend/*)           echo "Application (backend)" ;;
    frontend/*)          echo "Application (frontend)" ;;
    config/*)            echo "Config" ;;
    .claude/*|CLAUDE.md) echo "Claude/session files" ;;
    scripts/*)           echo "Scripts" ;;
    certs/*)             echo "Certs" ;;
    data/*)              echo "Data" ;;
    logs/*)              echo "Logs" ;;
    requirements.txt|pyproject.toml|setup*.sh|*.plist|start.sh|stop.sh|cli.py)
                         echo "Project/infra" ;;
    *)                   echo "Other" ;;
  esac
}

is_backup_commit() {
  local msg
  msg="$(git log -1 --format='%s' "$1" 2>/dev/null)"
  [[ "$msg" == "Claude session backup:"* ]]
}

find_last_real_commit() {
  local ref
  while IFS= read -r ref; do
    if ! is_backup_commit "$ref"; then
      echo "$ref"
      return
    fi
  done < <(git log --format='%H' HEAD)
  git rev-list --max-parents=0 HEAD
}

print_file_list() {
  local label="$1"; shift
  local files=("$@")
  local count=${#files[@]}
  if [[ $count -eq 0 ]]; then return; fi

  echo -e "${BOLD}${label}${RESET} (${count} file(s))"

  local cat f
  for cat in "Application (backend)" "Application (frontend)" "Config" "Claude/session files" "Scripts" "Project/infra" "Certs" "Data" "Logs" "Other"; do
    local matched=()
    for f in "${files[@]}"; do
      if [[ "$(categorize "$f")" == "$cat" ]]; then
        matched+=("$f")
      fi
    done
    if [[ ${#matched[@]} -gt 0 ]]; then
      echo -e "  ${CYAN}[$cat]${RESET}"
      for f in "${matched[@]}"; do
        echo -e "    ${DIM}$f${RESET}"
      done
    fi
  done
}

# ── parse args ───────────────────────────────────────────────────────────────

UNCOMMITTED_ONLY=false
BASE_REF=""

for arg in "$@"; do
  case "$arg" in
    --uncommitted) UNCOMMITTED_ONLY=true ;;
    *)             BASE_REF="$arg" ;;
  esac
done

if [[ -z "$BASE_REF" && "$UNCOMMITTED_ONLY" == false ]]; then
  BASE_REF="$(find_last_real_commit)"
fi

# ── header ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  CHANGE AUDIT — donut-intel${RESET}"
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "  Run at: $(date '+%Y-%m-%d %H:%M:%S')"
if [[ -n "$BASE_REF" ]]; then
  baseline_date="$(git log -1 --format='%ci' "$BASE_REF" 2>/dev/null | cut -d' ' -f1,2)"
  short="$(git rev-parse --short "$BASE_REF" 2>/dev/null || echo "$BASE_REF")"
  baseline_msg="$(git log -1 --format='%s' "$BASE_REF" 2>/dev/null || echo '')"
  echo -e "  Baseline: ${CYAN}$short${RESET}  ($baseline_date)"
  echo -e "  Baseline msg: ${DIM}$baseline_msg${RESET}"
fi
echo ""

# ── uncommitted changes ───────────────────────────────────────────────────────

uncommitted=()
while IFS= read -r line; do
  [[ -n "$line" ]] && uncommitted+=("$line")
done < <(git status --porcelain | awk '{print $2}' | sort -u)

if [[ ${#uncommitted[@]} -gt 0 ]]; then
  print_file_list "UNCOMMITTED (working tree / staged)" "${uncommitted[@]}"
  echo ""
else
  echo -e "  ${DIM}No uncommitted changes.${RESET}"
  echo ""
fi

if [[ "$UNCOMMITTED_ONLY" == true ]]; then
  exit 0
fi

# ── committed changes since baseline ─────────────────────────────────────────

echo -e "${BOLD}COMMITTED CHANGES since $short${RESET}"
echo ""

commits=()
while IFS= read -r line; do
  [[ -n "$line" ]] && commits+=("$line")
done < <(git log --format='%H' "${BASE_REF}..HEAD")

if [[ ${#commits[@]} -eq 0 ]]; then
  echo -e "  ${DIM}No commits since baseline.${RESET}"
  echo ""
else
  all_changed=()
  for hash in "${commits[@]}"; do
    msg="$(git log -1 --format='%s' "$hash")"
    commit_date="$(git log -1 --format='%ci' "$hash" | cut -d' ' -f1,2)"
    short_hash="$(git rev-parse --short "$hash")"

    if is_backup_commit "$hash"; then
      label="${YELLOW}[backup]${RESET}"
    else
      label="${CYAN}[commit]${RESET}"
    fi

    echo -e "  $label ${BOLD}$short_hash${RESET}  $commit_date"
    echo -e "         ${DIM}$msg${RESET}"

    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      echo -e "         ${DIM}  $f${RESET}"
      all_changed+=("$f")
    done < <(git diff-tree --no-commit-id -r --name-only "$hash")
    echo ""
  done

  # deduplicate
  unique_changed=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && unique_changed+=("$f")
  done < <(printf '%s\n' "${all_changed[@]}" | sort -u)

  echo -e "${BOLD}══ SUMMARY BY CATEGORY ══${RESET}"
  echo ""
  print_file_list "All files touched across ${#commits[@]} commit(s)" "${unique_changed[@]}"
fi

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo -e "  Tip: ${DIM}git diff ${short}..HEAD -- <file>${RESET}  to drill into any file."
echo -e "${BOLD}══════════════════════════════════════════════════════${RESET}"
echo ""
