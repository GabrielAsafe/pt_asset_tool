#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CURRENT_ROOT="$(cd .. && pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"

echo "[rc6.8-model062] refresh only prior count-layout drift by physical SHA consensus"
python3 pt_model062_inventory_refresh_rc6_8.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"

echo "[rc6.8-model062] full Model0.62 corpus; no Blender; no server"
python3 pt_model062_focused_rc6_8.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"

echo "[rc6.8-model062] reconcile active snapshot manifest for RC-managed files only"
python3 pt_snapshot_manifest_reconcile_rc6_8.py --current-root "$CURRENT_ROOT"
