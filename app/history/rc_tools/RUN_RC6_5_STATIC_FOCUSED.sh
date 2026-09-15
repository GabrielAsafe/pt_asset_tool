#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
echo "[rc6.5-static] discovery"
python3 pt_static_focused.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT" --discover-only
echo "[rc6.5-static] focused run"
python3 pt_static_focused.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"
