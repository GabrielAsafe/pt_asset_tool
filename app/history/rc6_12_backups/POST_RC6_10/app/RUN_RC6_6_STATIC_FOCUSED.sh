#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"

echo "[rc6.6-static] force rerun of the same 13 static representatives"
echo "[rc6.6-static] equal_normals API unpack fix; server inventory disabled"

PT_ASSET_BLENDER_TIMEOUT_SEC="${PT_ASSET_BLENDER_TIMEOUT_SEC:-120}" \
python3 pt_static_focused_rc6_6.py \
  --app-root "$APP_ROOT" \
  --client-root "$CLIENT_ROOT" \
  --server-root "$SERVER_ROOT"
