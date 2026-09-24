#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
echo "portable_build_warning=HOST_BUILD_USES_HOST_GLIBC release_build_recommended=../build_portable_container.sh" >&2

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; v=sys.version_info[:2]; raise SystemExit(0 if v in {(3,11),(3,12)} else 1)'; then
  echo "build_error=HOST_PYTHON_WHEEL_MATRIX_UNSUPPORTED expected=3.11_or_3.12" >&2
  echo "Use ../build_portable_container.sh for the release build; it pins CPython 3.11/manylinux2014." >&2
  exit 2
fi

REALESRGAN=""
for p in "$HERE/../tools/realesrgan/realesrgan-ncnn-vulkan" "$HERE/tools/realesrgan/realesrgan-ncnn-vulkan"; do
  [[ -f "$p" ]] && REALESRGAN="$p" && break
done
if [[ -z "$REALESRGAN" && "${PT_PORTABLE_ALLOW_NO_REALESRGAN:-0}" != "1" ]]; then
  echo "build_error=REALESRGAN_BUNDLE_MISSING" >&2
  echo "Place realesrgan-ncnn-vulkan under tools/realesrgan or set PT_PORTABLE_ALLOW_NO_REALESRGAN=1." >&2
  exit 2
fi

if [[ ! -d "$HERE/../vendor/summit_asset_enrichment_v9" ]]; then
  echo "build_error=ENRICHMENT_VENDOR_MISSING path=$HERE/../vendor/summit_asset_enrichment_v9" >&2
  exit 2
fi

VENV="${PT_PORTABLE_BUILD_VENV:-$HERE/.portable-build-venv}"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --only-binary=:all: -r requirements-portable-build.txt
"$VENV/bin/python" -c "import PIL, numpy; print('portable_binary_wheels=READY', 'Pillow='+PIL.__version__, 'NumPy='+numpy.__version__)"
rm -rf build/pt_asset_tool_portable dist/pt-asset-tool
"$VENV/bin/pyinstaller" --clean --noconfirm pt_asset_tool_portable.spec

BIN="$HERE/dist/pt-asset-tool"
[[ -x "$BIN" ]] || { echo "build_error=EXECUTABLE_NOT_CREATED" >&2; exit 2; }
"$BIN" --version
"$BIN" dependencies --json > "$HERE/dist/pt-asset-tool.dependencies.json" || true
sha256sum "$BIN" | tee "$HERE/dist/pt-asset-tool.sha256"
file "$BIN"
echo "portable_build=PASS path=$BIN"
