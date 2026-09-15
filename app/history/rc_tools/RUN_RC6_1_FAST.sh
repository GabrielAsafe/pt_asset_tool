#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
mkdir -p pt_build/devtest
export PT_ASSET_MOTION_CONTEXT_BUDGET_SEC="${PT_ASSET_MOTION_CONTEXT_BUDGET_SEC:-120}"
LOG="pt_build/devtest/rc6_1_2_release.log"
echo "[rc6.1.2] motion_context_budget=${PT_ASSET_MOTION_CONTEXT_BUDGET_SEC}s"
echo "[rc6.1.2] log=${LOG}"
./RUN_RELEASE_FAST.sh 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[rc6.1.2] release_exit_code=${rc}"
exit "$rc"
