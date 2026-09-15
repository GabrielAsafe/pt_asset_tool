#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"
echo "[rc6.5.2-static] exact run_release_1_automated_gate interception; no full-release fallback"
python3 pt_static_focused_rc6_5_2.py   --app-root "$APP_ROOT"   --client-root "$CLIENT_ROOT"   --server-root "$SERVER_ROOT"
