#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_ROOT="$(cd "$APP_ROOT/.." && pwd)"
cd "$APP_ROOT"
python3 -m pytest -q \
  dev_tests/test_rc6_11_autonomous.py \
  dev_tests/test_rc6_12_motion_batch.py \
  dev_tests/test_protected_tga_variants.py
python3 pt_rc6_12_verify.py --current-root "$CURRENT_ROOT"
printf 'RC6_12_LOCAL_FOCUSED=PASS\n'
