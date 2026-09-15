#!/usr/bin/env bash
set -u
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
RESULT="pt_build/devtest/release_1_auto/result.json"
LOG="pt_build/devtest/rc6_1_2_release.log"
BASE="pt_build/devtest/rc6_baseline_triage_v3.json"
if [[ ! -f "$RESULT" ]]; then
  echo "RC6_POSTRUN_ERROR: missing $RESULT" >&2
  exit 2
fi
if [[ -f pt_rc6_1_verify.py ]]; then
  echo "=== RC6.1.2 verifier ==="
  python3 pt_rc6_1_verify.py --app-root . || true
fi
echo "=== Release delta / blocker summary ==="
args=(python3 pt_release_postrun.py --result "$RESULT" --log "$LOG")
if [[ -f "$BASE" ]]; then args+=(--baseline-triage "$BASE"); fi
"${args[@]}"
echo "=== Rigid context recovery candidates (diagnostic only) ==="
python3 pt_rigid_context_triage.py --result "$RESULT" --out pt_build/devtest/rc6_rigid_context_triage.json
echo "=== Model0.62 failure structure ==="
python3 pt_model062_failure_analysis.py --result "$RESULT" --out pt_build/devtest/rc6_model062_failure_analysis.json
