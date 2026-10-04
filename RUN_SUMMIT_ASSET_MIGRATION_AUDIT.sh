#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="${SUMMIT_SOURCE_ROOT:-/home/gabriel/Área de Trabalho/summit/SourceCode}"
cd "$ROOT/app"

echo "[1/4] canonical JSON -> asset relations"
python3 pt_asset.py audit summit-canonical-assets --source-root "$SOURCE_ROOT"

echo "[2/4] source hardcodes -> migration/cook/UI queues"
python3 pt_asset.py audit summit-asset-migration --source-root "$SOURCE_ROOT"

echo "[3/4] retention with canonical roots"
python3 pt_asset.py audit asset-retention --source-root "$SOURCE_ROOT"

echo "[4/4] reversible quarantine plan (plan only)"
python3 pt_asset.py audit quarantine-plan

echo
echo "Reports:"
echo "  $ROOT/pt_build/summit_asset_migration/result.json"
echo "  $ROOT/pt_build/summit_asset_migration/migration_queue.tsv"
echo "  $ROOT/pt_build/summit_asset_migration/ui_text_candidates.tsv"
echo "  $ROOT/pt_build/summit_asset_migration/runtime_cook_plan.tsv"
echo "  $ROOT/pt_build/asset_retention/result.json"
echo "  $ROOT/pt_build/quarantine_plan/plan.json"
