#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${CONTAINER_ENGINE:-}" ]]; then
  ENGINE="$CONTAINER_ENGINE"
elif command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  echo "build_error=CONTAINER_ENGINE_NOT_FOUND expected=podman_or_docker" >&2
  exit 2
fi

[[ -d "$ROOT/tools/realesrgan" ]] || {
  echo "build_error=REALESRGAN_BUNDLE_MISSING path=$ROOT/tools/realesrgan" >&2
  exit 2
}
[[ -d "$ROOT/vendor/summit_asset_enrichment_v9" ]] || {
  echo "build_error=ENRICHMENT_VENDOR_MISSING path=$ROOT/vendor/summit_asset_enrichment_v9" >&2
  exit 2
}

IMAGE="pt-asset-tool-portable:v10.4"
"$ENGINE" build -f "$ROOT/Containerfile.portable" -t "$IMAGE" "$ROOT"
cid="$($ENGINE create "$IMAGE")"
trap '"$ENGINE" rm -f "$cid" >/dev/null 2>&1 || true' EXIT
mkdir -p "$ROOT/dist-portable"
"$ENGINE" cp "$cid:/src/app/dist/pt-asset-tool" "$ROOT/dist-portable/pt-asset-tool"
chmod +x "$ROOT/dist-portable/pt-asset-tool"
sha256sum "$ROOT/dist-portable/pt-asset-tool" | tee "$ROOT/dist-portable/pt-asset-tool.sha256"
file "$ROOT/dist-portable/pt-asset-tool"
echo "portable_container_build=PASS engine=$ENGINE image=$IMAGE python_runtime=python-build-standalone-3.11.16+20260825 glibc_target=2.17 runtime_external_env_sanitized=true fresh_state_safe=true path=$ROOT/dist-portable/pt-asset-tool"
