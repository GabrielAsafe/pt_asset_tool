#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(pwd)"
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
echo "[rc6.10-rigid] validate only prior unresolved numbered-series candidates"
echo "[rc6.10-rigid] no Blender; no server inventory; prior 1941 rows reused"
python3 pt_rigid_context_delta_rc6_10.py --app-root "$APP_ROOT" --client-root "$CLIENT_ROOT"
