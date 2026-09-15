#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CURRENT_ROOT="$(cd .. && pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
echo "[rc6.9-model062] refresh only RC6.8 inventory-drift target"
python3 pt_model062_inventory_refresh_rc6_9.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"
echo "[rc6.9-model062] validate only TmbC01 and reuse 3143 RC6.8 PASS rows"
python3 pt_model062_delta_rc6_9.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"
echo "[rc6.9-model062] reconcile active manifest; certification journal remains mutable"
python3 pt_snapshot_manifest_rc6_9.py --current-root "$CURRENT_ROOT"
