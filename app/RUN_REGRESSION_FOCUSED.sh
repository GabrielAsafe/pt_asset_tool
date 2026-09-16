#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_ROOT"
python3 -m pytest -q \
  dev_tests/test_registry_bootstrap_fresh.py \
  dev_tests/test_rc6_11_autonomous.py \
  dev_tests/test_rc6_12_motion_batch.py \
  dev_tests/test_protected_tga_variants.py
printf 'REGRESSION_FOCUSED=PASS\n'
