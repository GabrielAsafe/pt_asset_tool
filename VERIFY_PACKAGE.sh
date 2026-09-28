#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

required=(
  ".gitattributes"
  ".gitignore"
  "README.md"
  "CURRENT_READINESS.json"
  "VALIDATION_STATUS.md"
  "READY_TO_DEPLOY.py"
  "docs/README.md"
  "docs/en/README.md"
  "docs/en/getting_started/INSTALLATION_QUICKSTART.md"
  "docs/en/getting_started/USER_MANUAL.md"
  "docs/en/getting_started/GUI_MANUAL.md"
  "docs/en/getting_started/CLI_REFERENCE.md"
  "docs/en/engineering/ARCHITECTURE.md"
  "docs/en/topics/SEMANTIC_AUTHORING_CATALOG.md"
  "docs/en/topics/ASSET_QUARANTINE_WORKFLOW.md"
  "docs/en/validation/LOCALIZATION_EN_V210.md"
  "docs/validation/validate_english_localization.py"
  "docs/CURRENT_STATUS_2026-09-14.md"
  "docs/comece_aqui/INSTALLATION_QUICKSTART_1_0.md"
  "docs/comece_aqui/DEPENDENCIES.md"
  "docs/comece_aqui/MANUAL_UTILIZADOR.md"
  "docs/comece_aqui/GUI_MANUAL_1_0.md"
  "docs/comece_aqui/CLI_REFERENCE_1_0.md"
  "docs/cobertura_funcional/FEATURE_MATRIX_1_0.md"
  "docs/cobertura_funcional/TROUBLESHOOTING_1_0.md"
  "docs/engenharia/MAPA_MODULOS_SCRIPTS.md"
  "docs/engenharia/SUMMIT_GAME_ASSET_ENRICHMENT.md"
  "docs/engenharia/SNAPSHOT_MANIFEST_POLICY.md"
  "docs/engenharia/VENDOR_BOUNDARY.md"
  "docs/release/RELEASE_1_READINESS.md"
  "docs/release/RELEASE_1_CERTIFICATION.md"
  "docs/release/KNOWN_LIMITATIONS_1_0.md"
  "docs/release/RELEASE_NOTES_1_0.md"
  "docs/tematicos/FIELD_METADATA_EDITOR.md"
  "docs/tematicos/EFFECTS_PARTICLES.md"
  "docs/tematicos/TEXTURE_UPSCALE_PIPELINE.md"
  "docs/tematicos/GUIA_DESIGN_TOOL.md"
  "docs/tematicos/GUIA_ASSET_ENRICHMENT.md"
  "docs/tematicos/GUIA_WORKFLOW_CLIENT_SERVER.md"
  "docs/tematicos/ASSET_RETENTION_AND_COOKED_DDS.md"
  "docs/tematicos/ASSET_QUARANTINE_WORKFLOW.md"
  "docs/validation/INTEGRATION_ASSET_QUARANTINE_V26_2026-09-27.md"
  "docs/validation/INTEGRATION_ASSET_QUARANTINE_Q1_RANK_V27_2026-09-27.md"
  "docs/validation/INTEGRATION_ASSET_QUARANTINE_Q1_MANUAL_V28_2026-09-27.md"
  "docs/validation/INTEGRATION_EFFECT_RUNTIME_COMPONENTS_V25_2026-09-27.md"
  "vendor/summit_asset_enrichment_v9/PACKAGE_MANIFEST.json"
  "vendor/summit_asset_enrichment_v9/PATCH_NOTES_v9.md"
  "vendor/summit_asset_enrichment_v9/character_bundle_tool.py"
  "vendor/summit_asset_enrichment_v9/build_dependency_graph.py"
  "vendor/summit_asset_enrichment_v9/asset_common.py"
  "app/VERSION.txt"
  "app/requirements.txt"
  "app/requirements-dev.txt"
  "app/pt_asset.py"
  "app/update_snapshot_manifest.py"
  "app/RUN_RELEASE_FAST.sh"
  "app/RUN_REGRESSION_FOCUSED.sh"
  "app/pt_asset_tool/cli.py"
  "app/pt_asset_tool/app_config.py"
  "app/pt_asset_tool/config.py"
  "app/pt_asset_tool/dependencies.py"
  "app/pt_asset_tool/particle_service.py"
  "app/pt_asset_tool/registry.py"
  "app/pt_asset_tool/registry_bootstrap.py"
  "app/pt_asset_tool/certified_writers.py"
  "app/pt_asset_tool/legacy_runtime/__init__.py"
  "app/pt_asset_tool/legacy_runtime/pt_smd_blender_import_v3_static_armature.py"
  "app/pt_asset_tool/legacy_runtime/pt_smb_motion_evaluator_v1.py"
  "app/pt_asset_tool/enrichment_vendor_adapter.py"
  "app/pt_asset_tool/server_ui.py"
  "app/pt_asset_tool/server_field_editor.py"
  "app/pt_asset_tool/ui_app.py"
  "app/pt_asset_tool/general_asset_census.py"
  "app/pt_asset_tool/asset_retention.py"
  "app/pt_asset_tool/asset_quarantine.py"
  "app/pt_asset_tool/cooked_texture_evidence.py"
  "app/pt_asset_tool/effect_runtime_coverage.py"
  "app/pt_asset_tool/general_asset_recovery.py"
  "app/pt_asset_tool/client_manifest_evidence.py"
  "app/pt_asset_tool/server_lifecycle.py"
  "app/pt_asset_tool/server_bundle_census.py"
  "app/pt_asset_tool/superset_aggregation.py"
  "app/pt_asset_tool/source_evidence.py"
  "app/pt_asset_tool/texture_overlay.py"
  "app/pt_asset_tool/texture_upscale.py"
  "app/pt_texture_upscale.py"
  "app/pt_asset_tool/ui_catalog.py"
  "app/pt_asset_tool/ui_static/index.html"
  "app/pt_asset_tool/ui_static/app.js"
  "app/pt_effect_preview.py"
  "app/pt_effect_blender_preview.py"
  "app/pt_effect_preview_verify.py"
  "app/pt_part_editor.py"
  "app/pt_part_ui.py"
  "app/dev_tests/test_registry_bootstrap_fresh.py"
  "app/dev_tests/test_texture_upscale.py"
  "app/dev_tests/test_texture_upscale_integration.py"
  "app/tests/conftest.py"
  "app/dev_tests/test_rc6_11_autonomous.py"
  "app/dev_tests/test_rc6_12_motion_batch.py"
  "app/dev_tests/test_protected_tga_variants.py"
  "app/dev_tests/test_client_manifest_evidence.py"
  "app/dev_tests/test_general_asset_census.py"
  "app/dev_tests/test_general_asset_census_helpers.py"
  "app/dev_tests/test_general_asset_recovery.py"
  "app/dev_tests/test_asset_retention.py"
  "app/dev_tests/test_asset_quarantine.py"
  "app/dev_tests/test_cooked_texture_evidence.py"
  "app/dev_tests/test_effect_runtime_coverage.py"
  "app/dev_tests/test_vendor_spm_semantics.py"
  "app/data/reference/entity_catalog/monster_npc_entities_v1.json"
  "app/dev_tests/fixtures/character_profiles/pikeman_c01_m4.json"
  "app/dev_tests/fixtures/character_profiles/priestess_c01_m5.json"
  "SNAPSHOT_MUTABLE_PATHS.txt"
)

for rel in "${required[@]}"; do
  if [[ ! -f "$ROOT/$rel" ]]; then
    echo "PACKAGE_VERIFY=FAIL missing=$rel" >&2
    exit 2
  fi
done

# A clean package contains code/static reference data only. Machine-local state,
# old generated registries, development evidence and historical backups must not
# silently become release dependencies again.
forbidden=(
  "app/pt_asset_app_config.json"
  "app/certifications/assets.jsonl"
  "app/data/asset_registry/asset_inventory.json"
  "app/data/asset_registry/inx_physical_pairing.csv"
  "app/data/asset_registry/root_skeleton_bindings_v7.json"
  "app/data/asset_registry/smb_skeleton_signatures_v1.json"
  "app/data/character_profiles"
  "app/data/development_evidence"
  "app/history"
  "app/history_py"
  "evidence"
  "history"
  "docs/togpt_dont_bother_reading"
)
for rel in "${forbidden[@]}"; do
  if [[ -e "$ROOT/$rel" ]]; then
    echo "PACKAGE_VERIFY=FAIL packaged_runtime_or_history=$rel" >&2
    exit 3
  fi
done

# Runtime/user state is allowed to exist on the developer's disk.  A clean
# source/release contract means it is untracked and absent from the static
# snapshot; it does NOT mean user data must be deleted before verification.
# This distinction is essential for large enhancement outputs and transaction
# backups.  When Git metadata is available, fail only if runtime data is tracked.
if [[ -d "$ROOT/.git" ]]; then
  tracked_runtime="$(git -C "$ROOT" ls-files -- 'app/pt_build/**' 'enhancement/**' | head -1)"
  if [[ -n "$tracked_runtime" ]]; then
    echo "PACKAGE_VERIFY=FAIL tracked_runtime_path=$tracked_runtime reason=runtime_or_user_artifacts_must_be_gitignored_not_deleted" >&2
    exit 3
  fi
fi
if [[ -e "$ROOT/app/pt_build" ]]; then
  echo "PACKAGE_VERIFY=INFO preserved_runtime_path=app/pt_build reason=local_runtime_user_data_is_allowed_on_disk_but_excluded_from_git_and_snapshot"
fi
if [[ -e "$ROOT/enhancement" ]]; then
  echo "PACKAGE_VERIFY=INFO preserved_runtime_path=enhancement reason=legacy_user_enhancement_data_is_allowed_on_disk_but_excluded_from_git_and_snapshot"
fi
cache_path="$(find "$ROOT" \
  -path "$ROOT/.git" -prune -o \
  -path "$ROOT/app/pt_build" -prune -o \
  -path "$ROOT/enhancement" -prune -o \
  \( -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) -print -quit)"
if [[ -n "$cache_path" ]]; then
  rel="${cache_path#"$ROOT/"}"
  echo "PACKAGE_VERIFY=FAIL generated_path=$rel reason=ephemeral_python_or_test_cache_is_recreated_locally_and_must_not_be_release_input" >&2
  exit 3
fi

if find "$ROOT/docs/validation" -maxdepth 1 -type f -name 'VALIDATION_STATUS*' -print -quit | grep -q .; then
  echo "PACKAGE_VERIFY=FAIL archived_validation_status_reintroduced" >&2
  exit 3
fi

if [[ "$(tr -d '[:space:]' < "$ROOT/app/VERSION.txt")" != "1.0.0" ]]; then
  echo "PACKAGE_VERIFY=FAIL version expected=1.0.0 actual=$(cat "$ROOT/app/VERSION.txt")" >&2
  exit 4
fi

python3 - "$ROOT/vendor/summit_asset_enrichment_v9/PACKAGE_MANIFEST.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
if d.get('version')!='v9-fix136':
    raise SystemExit(f"PACKAGE_VERIFY=FAIL vendor_version={d.get('version')}")
PY

check_sha256() {
  local expected="$1" rel="$2" actual
  actual="$(sha256sum "$ROOT/$rel" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "PACKAGE_VERIFY=FAIL certified_writer_hash path=$rel expected=$expected actual=$actual" >&2
    exit 5
  fi
}
check_sha256 "3ff2769bbc9762c04fb992fbad52ba7d60ae6a53f19c22d4f1d68e274697eec3" "app/pt_asset_tool/rare_rigid_edit.py"
check_sha256 "0b43a3ced314c719bd1c6165a6715f37230b4d3d2d21586d6158a844d8f91991" "app/pt_asset_tool/rare_rigid_multivertex.py"
check_sha256 "010c77d73e7579cbdda622548f07df95ca68471fd4eacba058b3c83e79e853b0" "app/pt_asset_tool/rare_rigid_multibone_bridge.py"
check_sha256 "2c0f75931e54a72cd87be2bc6694370f849c24c3f2b4b44afbdbc288dcaf622c" "app/pt_asset_tool/rare_rigid_normal_bridge.py"

cd "$ROOT/app"
python3 - <<'PY'
from pathlib import Path
from pt_asset_tool.cli import build_parser
from pt_asset_tool.enrichment_vendor_adapter import _vendor_root
from pt_asset_tool.app_config import config_path
from pt_asset_tool.config import Settings

p=build_parser()
top=next(a for a in p._actions if a.__class__.__name__=='_SubParsersAction')
required={
 'validate': {'environment-auto','server-environment-auto','server-design-auto','physical-regression-auto','integration-regression-auto','release-1-auto'},
 'audit': {'server-inventory','server-bundles','server-fields','server-items','enrichment-plan','enrichment-graph','class-ui-aliases','cooked-textures','effect-runtime-coverage','asset-retention','asset-retention-query','quarantine-plan','general-asset-census','t5-assets'},
 'recover': {'general-closed-bundles'},
}
for group,names in required.items():
    sp=top.choices[group]
    sub=next(a for a in sp._actions if a.__class__.__name__=='_SubParsersAction')
    missing=names-set(sub.choices)
    if missing: raise SystemExit(f'parser missing {group}: {sorted(missing)}')
q=top.choices.get('quarantine')
if q is None: raise SystemExit('parser missing top-level quarantine')
qsub=next(a for a in q._actions if a.__class__.__name__=='_SubParsersAction')
qmissing={'status','review','apply','apply-component','restore'}-set(qsub.choices)
if qmissing: raise SystemExit(f'parser missing quarantine: {sorted(qmissing)}')
v=_vendor_root(Path.cwd())
if v.name!='summit_asset_enrichment_v9':
    raise SystemExit(f'active vendor is not v9: {v}')
expected=(Path.cwd()/'pt_build/state/pt_asset_app_config.json').resolve()
if config_path(Path.cwd()) != expected:
    raise SystemExit(f'config is not machine-local runtime state: {config_path(Path.cwd())}')
PY


# English UI/documentation localization contract.
python3 "$ROOT/docs/validation/validate_english_localization.py"

# Static UI/contracts.
grep -q 'Asset Enrichment' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpm"' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpp"' pt_asset_tool/ui_static/index.html
grep -q 'id="fieldOpenSpc"' pt_asset_tool/ui_static/index.html
grep -q '/api/server/field-editor/stage' pt_asset_tool/ui_static/app.js
grep -q 'u.path == "/api/server/field-editor/stage"' pt_asset_tool/ui_app.py
grep -q 'id="generalCensusBtn"' pt_asset_tool/ui_static/index.html
grep -q '/api/general-census' pt_asset_tool/ui_static/app.js
grep -q 'path == "/api/general-census"' pt_asset_tool/ui_app.py
grep -q 'id="assetRetentionPanel"' pt_asset_tool/ui_static/index.html
grep -q '/api/asset-retention' pt_asset_tool/ui_static/app.js
grep -q 'path == "/api/asset-retention"' pt_asset_tool/ui_app.py
grep -q 'general-asset-census' pt_asset_tool/cli.py
grep -q 'cooked-textures' pt_asset_tool/cli.py
grep -q 'asset-retention' pt_asset_tool/cli.py
grep -q 'asset-retention-query' pt_asset_tool/cli.py
grep -q 'effect-runtime-coverage' pt_asset_tool/cli.py
grep -q 'quarantine-plan' pt_asset_tool/cli.py
grep -q 'MOVE_Q0_TO_QUARANTINE' pt_asset_tool/asset_quarantine.py
grep -q 'MOVE_Q1_COMPONENT_TO_QUARANTINE' pt_asset_tool/asset_quarantine.py
grep -q 'apply-component' pt_asset_tool/cli.py
grep -q 'PT_LEGACY_AUTHORING_NAME_CATALOG_V1' pt_asset_tool/legacy_name_catalog.py
grep -q 'priston_asset_name_map_v1.json' pt_asset_tool/legacy_name_catalog.py
test -f pt_asset_tool/contracts/priston_asset_name_map_v1.json
grep -q 'legacyAuthoringCatalogEntry' pt_asset_tool/ui_static/index.html
grep -q 'semantic_related_refs' pt_asset_tool/ui_static/app.js
grep -q 'RESTORE_QUARANTINE' pt_asset_tool/asset_quarantine.py
grep -q 'Q0_HIGH_CONFIDENCE_INVALID_ORPHAN' pt_asset_tool/asset_quarantine.py
grep -q 'q1_is_review_only' pt_asset_tool/asset_quarantine.py
grep -q 'review_score_is_not_delete_authority' pt_asset_tool/asset_quarantine.py
grep -q 'Q1_PRIORITY_' pt_asset_tool/asset_quarantine.py
grep -q 'ambiguous_basename_is_review_not_root' pt_asset_tool/effect_runtime_coverage.py
grep -q 'component_membership_is_review_not_delete_authority' pt_asset_tool/asset_retention.py
grep -q 'monster_npc_asset_removal_requires_zero_linkage' pt_asset_tool/asset_retention.py
grep -q 'contract_graph_edge_alone_is_review_not_runtime_protection' pt_asset_tool/asset_retention.py
grep -q 'failed_cook_does_not_make_source_removable' pt_asset_tool/cooked_texture_evidence.py
grep -q 'class-ui-aliases' pt_asset_tool/cli.py
grep -q 'donor_gap_is_not_runtime_need' pt_asset_tool/general_asset_census.py
grep -q 'RECOVERY_APPLY_REQUIRES_EXPECTED_ROOTS' pt_asset_tool/general_asset_recovery.py
grep -q 'general-closed-bundles' pt_asset_tool/cli.py
grep -q 'SPC_NATIVE_ABI_INSERT' pt_asset_tool/server_field_editor.py
grep -q 'source_abi.*smTRNAS_PLAYERINFO=504; smCHAR_INFO=464' pt_asset_tool/server_field_editor.py
grep -q 'donor_record_required.*False' pt_asset_tool/server_field_editor.py
grep -q 'BLENDER_PREVIEW_APPROXIMATE' pt_effect_preview.py
grep -q 'registry_bootstrap' pt_asset.py
grep -q 'legacy_runtime' pt_asset.py
grep -q 'texture-upscale' pt_asset.py
grep -q 'upscale_texture' pt_asset_tool/ui_actions.py
grep -q "action==='upscale_texture'" pt_asset_tool/ui_static/app.js
grep -q 'TEXTURE_UPSCALE_PILLOW_UNAVAILABLE' pt_asset_tool/ui_app.py
grep -q 'data-tab="particles"' pt_asset_tool/ui_static/index.html
grep -q '/api/particles/inspect' pt_asset_tool/ui_app.py
grep -q 'particle_service' pt_part_ui.py
grep -q 'dependency_report' pt_asset_tool/ui_app.py
grep -q 'dependencies' pt_asset.py
grep -q 'pt_build.*texture_upscale' pt_asset_tool/texture_upscale.py

VERIFY_TMP="$(mktemp -d)"
trap 'rm -rf "$VERIFY_TMP"' EXIT
PYTHONPYCACHEPREFIX="$VERIFY_TMP/pycache" python3 -m compileall -q \
  pt_asset.py pt_texture_upscale.py pt_asset_tool pt_effect_preview.py pt_effect_blender_preview.py \
  pt_effect_preview_verify.py pt_part_editor.py pt_part_ui.py ../READY_TO_DEPLOY.py
if command -v node >/dev/null 2>&1; then
  node --check pt_asset_tool/ui_static/app.js >/dev/null
fi
bash -n RUN_RELEASE_FAST.sh
bash -n RUN_REGRESSION_FOCUSED.sh

# The mutable-path manifest is intentionally comment-only now: all mutable
# state is beneath pt_build, which the static manifest excludes wholesale.
if grep -Ev '^[[:space:]]*(#|$)' "$ROOT/SNAPSHOT_MUTABLE_PATHS.txt" | grep -q .; then
  echo "PACKAGE_VERIFY=FAIL mutable_paths_should_be_runtime_state_only" >&2
  exit 6
fi

if [[ -f "$ROOT/SNAPSHOT_SHA256SUMS.txt" ]]; then
  python3 - "$ROOT/SNAPSHOT_SHA256SUMS.txt" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]); bad=[]
for raw in p.read_text(encoding='utf-8').splitlines():
    if not raw.strip(): continue
    try: _,rel=raw.split(None,1)
    except ValueError: raise SystemExit('PACKAGE_VERIFY=FAIL snapshot_manifest_malformed')
    rel=rel.strip().lstrip('*')
    parts=pathlib.PurePosixPath(rel).parts
    if '__pycache__' in parts or 'pt_build' in parts or rel.endswith('.pyc'):
        bad.append(rel)
if bad: raise SystemExit('PACKAGE_VERIFY=FAIL snapshot_manifest_ephemeral_paths '+','.join(bad[:8]))
PY
  python3 "$ROOT/app/update_snapshot_manifest.py" --current-root "$ROOT" --check || {
    echo "PACKAGE_VERIFY=FAIL snapshot_manifest" >&2
    exit 7
  }
fi

printf 'PACKAGE_VERIFY=PASS version=1.0.0 vendor=v9-fix136 runtime_state=excluded_or_untracked files=%s\n' "$(find . -type f -not -path './pt_build/*' -not -path './app/pt_build/*' -not -path './enhancement/*' -not -path './.git/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -name '*.pyc' -not -name '*.pyo' | wc -l)"
