#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"

echo "[rc6.5.3-static] replaying prior 13 static representatives only"
echo "[rc6.5.3-static] server_design_auto is intercepted in-process; no server inventory should run"

PT_ASSET_BLENDER_TIMEOUT_SEC="${PT_ASSET_BLENDER_TIMEOUT_SEC:-120}" \
python3 pt_static_focused_rc6_5_3.py \
  --app-root "$APP_ROOT" \
  --client-root "$CLIENT_ROOT" \
  --server-root "$SERVER_ROOT"
