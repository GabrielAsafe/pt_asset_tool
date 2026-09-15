#!/usr/bin/env bash
set -uo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"

echo "[rc6.5.5-static] recover RC6.5.4 physical batch first; rerun only if unproven"
python3 pt_rc6_5_5_recover.py --app-root "$APP_ROOT"
recover_rc=$?

if [ "$recover_rc" -eq 0 ]; then
  echo "[rc6.5.5-static] RECOVERED: no Blender rerun needed"
  exit 0
fi

if [ "$recover_rc" -ne 4 ]; then
  echo "[rc6.5.5-static] recovery failed unexpectedly rc=$recover_rc"
  exit "$recover_rc"
fi

echo "[rc6.5.5-static] prior result stale/unproven; running exact 13 representatives"
echo "[rc6.5.5-static] server inventory remains disabled"
PT_ASSET_BLENDER_TIMEOUT_SEC="${PT_ASSET_BLENDER_TIMEOUT_SEC:-120}" \
python3 pt_static_focused_rc6_5_5.py \
  --app-root "$APP_ROOT" \
  --client-root "$CLIENT_ROOT" \
  --server-root "$SERVER_ROOT"
