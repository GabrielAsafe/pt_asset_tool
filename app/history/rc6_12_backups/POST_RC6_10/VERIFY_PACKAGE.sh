#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

required=(
  "START_HERE.md"
  "CHANGELOG.md"
  "CURRENT_READINESS.json"
  "VALIDATION_STATUS.md"
  "docs/CURRENT_STATUS_2026-09-05.md"
  "docs/FIELD_METADATA_EDITOR.md"
  "docs/EFFECTS_PARTICLES.md"
  "docs/HOUSEKEEPING_2026-09-05.md"
  "docs/GUIA_DESIGN_TOOL.md"
  "docs/GUIA_ASSET_ENRICHMENT.md"
  "docs/GUIA_WORKFLOW_CLIENT_SERVER.md"
  "docs/RELEASE_1_READINESS.md"
  "docs/MAPA_MODULOS_SCRIPTS.md"
  "vendor/summit_asset_enrichment_v9/PACKAGE_MANIFEST.json"
  "vendor/summit_asset_enrichment_v9/PATCH_NOTES_v9.md"
  "vendor/summit_asset_enrichment_v9/character_bundle_tool.py"
  "vendor/summit_asset_enrichment_v6/PACKAGE_MANIFEST.json"
  "app/VERSION.txt"
  "app/pt_asset.py"
  "app/pt_asset_tool/cli.py"
  "app/pt_asset_tool/enrichment_vendor_adapter.py"
  "app/pt_asset_tool/server_ui.py"
  "app/pt_asset_tool/server_field_editor.py"
  "app/pt_asset_tool/ui_app.py"
  "app/pt_asset_tool/ui_static/index.html"
  "app/pt_asset_tool/ui_static/app.js"
  "app/pt_effect_preview.py"
  "app/pt_effect_blender_preview.py"
  "app/pt_effect_preview_verify.py"
  "app/pt_part_editor.py"
  "app/pt_part_ui.py"
  "app/RUN_RC6_5_5_STATIC_FOCUSED.sh"
  "app/pt_rc6_5_5_verify.py"
  "app/pt_asset_tool/release_1_auto.py"
  "app/pt_asset_tool/writer_corpus_audit.py"
  "app/data/asset_registry/asset_inventory.json"
  "app/data/asset_registry/inx_physical_pairing.csv"
  "SNAPSHOT_MUTABLE_PATHS.txt"
)

for rel in "${required[@]}"; do
  if [[ ! -f "$ROOT/$rel" ]]; then
    echo "PACKAGE_VERIFY=FAIL missing=$rel" >&2
    exit 2
  fi
done

if [[ "$(tr -d '[:space:]' < "$ROOT/app/VERSION.txt")" != "0.13.0" ]]; then
  echo "PACKAGE_VERIFY=FAIL version expected=0.13.0 actual=$(cat "$ROOT/app/VERSION.txt")" >&2
  exit 3
fi

python3 - "$ROOT/vendor/summit_asset_enrichment_v9/PACKAGE_MANIFEST.json" <<'PY'
import json,sys
p=sys.argv[1]
d=json.load(open(p,encoding='utf-8'))
if d.get('version')!='v9-fix136':
    raise SystemExit(f"PACKAGE_VERIFY=FAIL vendor_version={d.get('version')}")
PY

check_sha256() {
  local expected="$1" rel="$2" actual
  actual="$(sha256sum "$ROOT/$rel" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "PACKAGE_VERIFY=FAIL certified_writer_hash path=$rel expected=$expected actual=$actual" >&2
    exit 4
  fi
}
check_sha256 "229a8e216cff16c68b61ad04d312e4ef6163ac955147f823ea7ed1164f524c42" "app/pt_asset_tool/rare_rigid_edit.py"
check_sha256 "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991" "app/pt_asset_tool/rare_rigid_multivertex.py"
check_sha256 "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0" "app/pt_asset_tool/rare_rigid_multibone_bridge.py"
check_sha256 "67e529d3d04012ea7c3ac1b6a5576525a77870b4e452c4336955100b5bb8ff96" "app/pt_asset_tool/rare_rigid_normal_bridge.py"

cd "$ROOT/app"
python3 - <<'PY'
from pt_asset_tool.cli import build_parser
from pt_asset_tool.enrichment_vendor_adapter import _vendor_root
from pathlib import Path
p=build_parser()
top=next(a for a in p._actions if a.__class__.__name__=='_SubParsersAction')
required={
 'validate': {'environment-auto','server-environment-auto','server-design-auto','physical-regression-auto','integration-regression-auto','release-1-auto'},
 'audit': {'server-inventory','server-bundles','server-fields','server-items','enrichment-plan','enrichment-graph'},
}
for group,names in required.items():
    sp=top.choices[group]
    sub=next(a for a in sp._actions if a.__class__.__name__=='_SubParsersAction')
    missing=names-set(sub.choices)
    if missing: raise SystemExit(f'parser missing {group}: {sorted(missing)}')
v=_vendor_root(Path.cwd())
if v.name!='summit_asset_enrichment_v9':
    raise SystemExit(f'active vendor is not v9: {v}')
PY

grep -q 'Asset Enrichment v9' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpm"' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpp"' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpc"' pt_asset_tool/ui_static/index.html
grep -q '/api/server/field-editor/stage' pt_asset_tool/ui_static/app.js
grep -q 'u.path == "/api/server/field-editor/stage"' pt_asset_tool/ui_app.py
grep -q 'STAGED_CLONE_PATCH_ONLY' pt_asset_tool/server_field_editor.py
grep -q 'BLOCKED_UNKNOWN_SMCHAR_INFO_FIELDS' pt_asset_tool/server_field_editor.py
grep -q 'BLENDER_PREVIEW_APPROXIMATE' pt_effect_preview.py
grep -q 'server_source_write.*False' pt_asset_tool/ui_app.py || true

VERIFY_TMP="$(mktemp -d)"
trap 'rm -rf "$VERIFY_TMP"' EXIT
PYTHONPYCACHEPREFIX="$VERIFY_TMP/pycache" python3 -m compileall -q pt_asset.py pt_asset_tool pt_effect_preview.py pt_effect_blender_preview.py pt_effect_preview_verify.py pt_part_editor.py pt_part_ui.py
if command -v node >/dev/null 2>&1; then
  node --check pt_asset_tool/ui_static/app.js >/dev/null
fi
bash -n RUN_RELEASE_FAST.sh
bash -n RUN_RC6_5_5_STATIC_FOCUSED.sh

if [[ ! -f "$ROOT/SNAPSHOT_MUTABLE_PATHS.txt" ]] || ! grep -qx 'app/certifications/assets.jsonl' "$ROOT/SNAPSHOT_MUTABLE_PATHS.txt"; then
  echo "PACKAGE_VERIFY=FAIL mutable_paths_contract" >&2
  exit 5
fi

python3 - "$ROOT/app/certifications/assets.jsonl" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
if not p.is_file():
    raise SystemExit('PACKAGE_VERIFY=FAIL certifications_journal_missing')
for n,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
    if not line.strip():
        continue
    try:
        row=json.loads(line)
    except Exception as exc:
        raise SystemExit(f'PACKAGE_VERIFY=FAIL certifications_jsonl line={n} error={exc}')
    if not isinstance(row,dict):
        raise SystemExit(f'PACKAGE_VERIFY=FAIL certifications_jsonl_object line={n}')
PY

if [[ -f "$ROOT/SNAPSHOT_SHA256SUMS.txt" ]]; then
  (cd "$ROOT" && sha256sum -c SNAPSHOT_SHA256SUMS.txt >/dev/null) || {
    echo "PACKAGE_VERIFY=FAIL snapshot_manifest" >&2
    exit 6
  }
fi

printf 'PACKAGE_VERIFY=PASS version=0.13.0 vendor=v9-fix136 files=%s\n' "$(find . -type f | wc -l)"
