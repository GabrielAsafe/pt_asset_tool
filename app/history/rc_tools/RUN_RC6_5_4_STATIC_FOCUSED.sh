#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"

echo "[rc6.5.4-static] exact prior selection via real per-domain chooser"
echo "[rc6.5.4-static] server inventory is disabled for this focused run"

PT_ASSET_BLENDER_TIMEOUT_SEC="${PT_ASSET_BLENDER_TIMEOUT_SEC:-120}" \
python3 pt_static_focused_rc6_5_4.py \
  --app-root "$APP_ROOT" \
  --client-root "$CLIENT_ROOT" \
  --server-root "$SERVER_ROOT"
