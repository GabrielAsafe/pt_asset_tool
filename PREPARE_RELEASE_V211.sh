#!/usr/bin/env bash
set -Eeuo pipefail

# PT Asset Tool V2.11 — release preparation helper
#
# Default:
#   - preserves repository policy files from HEAD
#   - removes generated Python/test caches
#   - validates the focused 38-test V2.11 suite
#   - removes patch-package metadata
#   - regenerates the snapshot manifest
#   - synchronizes snapshot file-count metadata
#   - regenerates the snapshot manifest again after metadata changes
#   - runs snapshot/package verification
#   - smoke-tests the canonical CLI from app/
#   - shows release diff/status
#   - DOES NOT git add or commit
#
# Optional:
#   ./PREPARE_RELEASE_V211.sh --stage
#   ./PREPARE_RELEASE_V211.sh --stage --commit
#
# Run from anywhere inside the repository.

STAGE=0
COMMIT=0
COMMIT_MESSAGE="feat: integrate Summit canonical source V2.11"

usage() {
  cat <<'EOF'
Usage:
  PREPARE_RELEASE_V211.sh [--stage] [--commit] [--commit-message "message"]

Options:
  --stage
      Run `git add -A` after all validation gates pass.

  --commit
      Implies --stage and creates a git commit after validation.
      Default message:
        feat: integrate Summit canonical source V2.11

  --commit-message MESSAGE
      Override the commit message. Implies --commit and --stage.

  -h, --help
      Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --stage)
      STAGE=1
      shift
      ;;
    --commit)
      STAGE=1
      COMMIT=1
      shift
      ;;
    --commit-message)
      [[ $# -ge 2 ]] || { echo "ERROR: --commit-message requires a value" >&2; exit 2; }
      STAGE=1
      COMMIT=1
      COMMIT_MESSAGE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

say() {
  printf '\n==> %s\n' "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# Find repository root.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
cd "$REPO_ROOT"

[[ -f app/update_snapshot_manifest.py ]] || die "missing app/update_snapshot_manifest.py"
[[ -x VERIFY_PACKAGE.sh || -f VERIFY_PACKAGE.sh ]] || die "missing VERIFY_PACKAGE.sh"

say "Repository"
printf 'root=%s\n' "$REPO_ROOT"
git status --short

say "Preserve repository policy files from HEAD"
# The V2.11 overlay package is not authoritative over the repository's
# existing V3.1 hygiene/EOL policy.
git restore --source=HEAD -- .gitattributes .gitignore

say "Remove patch-package metadata"
rm -f PATCH_MANIFEST.json

say "Remove generated Python/test caches"
# Use two passes and avoid `find -delete` together with `-prune`.
find . \
  -path './.git' -prune -o \
  -path './app/pt_build' -prune -o \
  -type d \( \
    -name '__pycache__' -o \
    -name '.pytest_cache' -o \
    -name '.mypy_cache' -o \
    -name '.ruff_cache' \
  \) -print0 |
while IFS= read -r -d '' d; do
  rm -rf -- "$d"
done

find . \
  -path './.git' -prune -o \
  -path './app/pt_build' -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -print0 |
while IFS= read -r -d '' f; do
  rm -f -- "$f"
done

say "Check expected V2.11 test files"
TESTS=(
  app/dev_tests/test_summit_canonical_v211.py
  app/dev_tests/test_legacy_authoring_pipeline.py
  app/dev_tests/test_legacy_name_catalog.py
)
for f in "${TESTS[@]}"; do
  [[ -f "$f" ]] || die "missing required focused test: $f"
  printf 'OK %s\n' "$f"
done

say "Run focused V2.11 regression suite"
PYTHONDONTWRITEBYTECODE=1 \
python3 -m pytest -q -p no:cacheprovider "${TESTS[@]}"

say "Regenerate snapshot manifest after overlay cleanup"
manifest_output="$(
  PYTHONDONTWRITEBYTECODE=1 \
  python3 app/update_snapshot_manifest.py --current-root .
)"
printf '%s\n' "$manifest_output"

snapshot_count="$(
  printf '%s\n' "$manifest_output" |
  sed -n 's/.*SNAPSHOT_MANIFEST_UPDATED files=\([0-9][0-9]*\).*/\1/p' |
  tail -n1
)"
[[ -n "$snapshot_count" ]] || die "could not parse snapshot file count"

say "Synchronize release metadata to snapshot count=${snapshot_count}"
python3 - "$snapshot_count" <<'PY'
from pathlib import Path
import re
import sys

count = sys.argv[1]

dist = Path("DISTRIBUTION_INFO.json")
text = dist.read_text(encoding="utf-8")
new, n = re.subn(
    r'("snapshot"\s*:\s*\{\s*"file_count"\s*:\s*)\d+',
    rf'\g<1>{count}',
    text,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit("Could not update snapshot.file_count in DISTRIBUTION_INFO.json")
dist.write_text(new, encoding="utf-8")

status = Path("VALIDATION_STATUS.md")
text = status.read_text(encoding="utf-8")
new, n = re.subn(
    r'SNAPSHOT_MANIFEST_CHECK=PASS` \(\d+ static files\)',
    f'SNAPSHOT_MANIFEST_CHECK=PASS` ({count} static files)',
    text,
    count=1,
)
if n == 0:
    # Allow the file not to carry this prose line, but do not invent it.
    print("INFO: no static-file-count prose found in VALIDATION_STATUS.md")
else:
    status.write_text(new, encoding="utf-8")
PY

say "Confirm no stale 677 snapshot count remains in release metadata"
if grep -RIn \
  --exclude-dir=.git \
  --exclude=SNAPSHOT_SHA256SUMS.txt \
  '677' \
  DISTRIBUTION_INFO.json \
  VALIDATION_STATUS.md \
  docs/validation \
  docs/en \
  docs/tematicos
then
  echo "WARNING: references to 677 remain; review whether they are historical or stale." >&2
else
  echo "OK: no 677 reference remains in the checked release metadata scope"
fi

say "Regenerate snapshot manifest after metadata synchronization"
PYTHONDONTWRITEBYTECODE=1 \
python3 app/update_snapshot_manifest.py --current-root .

say "Validate snapshot manifest"
PYTHONDONTWRITEBYTECODE=1 \
python3 app/update_snapshot_manifest.py --current-root . --check

say "Run package verifier"
chmod +x VERIFY_PACKAGE.sh
PYTHONDONTWRITEBYTECODE=1 ./VERIFY_PACKAGE.sh

say "Smoke-test canonical CLI from app/"
(
  cd app

  cli_help="$(
    PYTHONDONTWRITEBYTECODE=1 \
    python3 -m pt_asset_tool --help
  )"
  printf '%s\n' "$cli_help" | grep -i canonical

  canonical_help="$(
    PYTHONDONTWRITEBYTECODE=1 \
    python3 -m pt_asset_tool canonical --help
  )"
  printf '%s\n' "$canonical_help"

  for cmd in status catalog capabilities stage publish-source publish-packs restore; do
    printf '%s\n' "$canonical_help" | grep -q "$cmd" ||
      die "canonical CLI missing subcommand: $cmd"
  done
)

say "Ensure no forbidden generated paths are visible to git"
bad_status="$(
  git status --short |
  grep -E '(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|PATCH_MANIFEST\.json|(^|/)app/pt_build/)' || true
)"
if [[ -n "$bad_status" ]]; then
  printf '%s\n' "$bad_status" >&2
  die "generated/patch/runtime artifacts are still visible to git"
fi

say "Working-tree status"
git status --short

say "Unstaged diff summary"
git diff --stat

if (( STAGE )); then
  say "Stage release changes"
  git add -A

  say "Staged status"
  git status --short

  say "Staged diff summary"
  git diff --cached --stat

  say "Check staged diff for whitespace/errors"
  git diff --cached --check
else
  cat <<'EOF'

Release preparation gates passed.

Review the status/diff above. To stage after review:
  git add -A
  git status --short
  git diff --cached --stat
  git diff --cached --check

Or rerun:
  ./PREPARE_RELEASE_V211.sh --stage
EOF
fi

if (( COMMIT )); then
  say "Create release commit"
  git commit -m "$COMMIT_MESSAGE"

  say "Last commit"
  git log -1 --stat

  say "Final working-tree status"
  git status --short
fi

say "V2.11 release preparation PASS"
printf 'snapshot_files=%s\n' "$snapshot_count"
printf 'staged=%s committed=%s\n' "$STAGE" "$COMMIT"
