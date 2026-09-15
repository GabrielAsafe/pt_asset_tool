#!/usr/bin/env bash
set -euo pipefail
CLIENT_ROOT="${CLIENT_ROOT:-/home/gabriel/Área de Trabalho/summit/Summit Tale Client Full/cliente}"
SERVER_ROOT="${SERVER_ROOT:-/home/gabriel/Área de Trabalho/summit/Servidor}"
export PT_ASSET_CACHE_MODE="${PT_ASSET_CACHE_MODE:-trust-readonly}"
export PT_ASSET_BLENDER_TIMEOUT_SEC=120
exec python3 pt_asset_cached.py \
  --client-root "$CLIENT_ROOT" \
  --server-root "$SERVER_ROOT" \
  validate release-1-auto --resume
