#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"

echo "[rc6.7-model062] physical Model0.62 corpus only"
echo "[rc6.7-model062] no Blender; no server inventory"

python3 pt_model062_focused_rc6_7.py \
  --app-root "$APP_ROOT" \
  --client-root "$CLIENT_ROOT"
