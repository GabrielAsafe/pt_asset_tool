#!/usr/bin/env bash
set -euo pipefail
export PT_ASSET_CACHE_MODE="${PT_ASSET_CACHE_MODE:-trust-readonly}"
export PT_ASSET_BLENDER_TIMEOUT_SEC="${PT_ASSET_BLENDER_TIMEOUT_SEC:-120}"
exec python3 pt_asset_cached.py validate release-1-auto --resume
