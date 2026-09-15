from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .stage072_authoring_candidate import (
    plan_stage072_saved_blender_candidate,
    build_stage072_edit_extract_command,
    apply_stage072_candidate_witness,
)
from .stage072_corpus import parse_stage072
from .utils import run_logged, sha256_file
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_STAGE072_AUTOMATED_DEVTEST_V2"
BATCH_FORMAT = "PT_STAGE072_AUTOMATED_DEVTEST_BATCH_V2"


def run_stage072_automated_devtest(settings, registry, resolver, certifications, *, asset_path: str) -> dict[str, Any]:
    asset = registry.resolve(asset_path)
    if asset.kind != "SMD_STAGE_072":
        raise RuntimeError(f"Stage0.72 automated devtest requires SMD_STAGE_072, got {asset.kind}/{asset.family}")
    root=pathlib.Path(settings.project_root).resolve()
    work=root/"pt_build"/"devtest"/"stage072_auto"/asset.primary_path.replace("/","__")
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True,exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    preview = runner.stage072_preview(asset)
    uv = runner.stage072_uv_roundtrip(asset, uv_delta=0.03125)

    # Build a real saved-Blender multi-vertex/XYZ geometry candidate. The generic
    # import workspace is disposable in this devtest and is rebuilt from source.
    imported=runner.blender_import_workspace(asset, reset=True)
    base_blend=pathlib.Path(imported['blend']).resolve()
    edited=work/'automatically_edited_stage.blend'; edit_report=work/'edit_report.json'
    run_logged(settings.blender_command()+[
        '--background',str(base_blend),'--python-exit-code','1',
        '--python',str(root/'pt_asset_tool'/'blender'/'apply_stage072_semantic_devtest.py'),'--',
        '--out',str(edited),'--report',str(edit_report),
    ],work/'01_automatic_edit.log')
    edit=json.loads(edit_report.read_text(encoding='utf-8'))
    if edit.get('status')!='PASS' or int(edit.get('edit_count') or 0)<2:
        raise RuntimeError(f'Stage0.72 automatic multi-vertex edit failed: {edit}')
    # Candidate planner reads the canonical generic workspace path, so replace
    # only the pt_build workspace blend with the deterministic edited copy.
    shutil.copy2(edited, base_blend)
    candidate=plan_stage072_saved_blender_candidate(root,resolver,asset,output=work/pathlib.PurePosixPath(asset.primary_path).name)
    if candidate.get('status')!='READY':
        raise RuntimeError(f'Stage0.72 candidate plan blocked: {candidate.get("blockers")}')
    witness=work/'saved_edit_witness.json'; extract=work/'saved_edit_extract.json'
    run_logged(build_stage072_edit_extract_command(settings,candidate,witness=witness,report=extract),work/'02_extract.log')
    extracted=json.loads(extract.read_text(encoding='utf-8'))
    if extracted.get('status')!='PASS' or extracted.get('edit_mode')!='GEOMETRY_GRID_MULTI' or int(extracted.get('edit_count') or 0)<2:
        raise RuntimeError(f'Stage0.72 multi geometry extraction failed: {extracted}')
    built=apply_stage072_candidate_witness(candidate,witness)
    if built.get('status')!='PASS':
        raise RuntimeError(f'Stage0.72 strict candidate failed: {built}')
    output=pathlib.Path(built['output']).resolve()
    parsed=parse_stage072(output,include_payload=True)
    if parsed.get('full_parse')!='PASS': raise RuntimeError('Stage0.72 rebuilt candidate parser failed')

    # Reimport the actual rebuilt candidate and require the transport importer to
    # accept it headlessly, including material/UV/color/light metadata.
    reimport=work/'candidate_reimport.blend'; reimport_report=work/'candidate_reimport.json'
    run_logged(settings.blender_command()+[
        '--background','--python-exit-code','1','--python',str(root/'pt_asset_tool'/'blender'/'import_stage072.py'),'--',
        '--smd',str(output),'--client-root',str(settings.client_root),'--out',str(reimport),'--report',str(reimport_report),
    ],work/'03_reimport.log')
    re=json.loads(reimport_report.read_text(encoding='utf-8'))
    if re.get('check')!='PASS': raise RuntimeError(f'Stage0.72 rebuilt reimport failed: {re}')

    result = {
        "format": FORMAT, "status": "PASS", "asset": asset.primary_path,
        "preview_transport": "PASS",
        "uv_roundtrip": uv.get("stage072_uv_roundtrip"),
        "geometry_saved_edit": {
            "status":"PASS","edit_mode":"GEOMETRY_GRID_MULTI","edit_count":extracted.get('edit_count'),
            "artifact":str(output),"artifact_sha256":sha256_file(output),"witness":str(witness),
            "strict_compare":(built.get('compare') or {}).get('check'),
        },
        "candidate_reimport": {"status":"PASS","blend":str(reimport),"report":str(reimport_report)},
        "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    rp = work / "result.json"; result["report"] = str(rp)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_stage072_automated_devtest_batch(settings, registry, resolver, certifications, rows: list[dict[str, Any]]) -> dict[str, Any]:
    results=[]; failures=[]
    for row in rows:
        try:
            results.append(run_stage072_automated_devtest(settings, registry, resolver, certifications, asset_path=row["asset"]))
        except Exception as exc:
            failures.append({"asset": row.get("asset"), "error": f"{type(exc).__name__}: {exc}"})
    result = {
        "format": BATCH_FORMAT, "status": "PASS" if results and not failures else ("EMPTY" if not rows else "FAIL"),
        "requested": len(rows), "passed_assets": [x.get("asset") for x in results],
        "failed_assets": failures, "results": results, "automatic_only": True,
        "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    out = pathlib.Path(settings.project_root).resolve() / "pt_build" / "devtest" / "stage072_auto" / "batch_result.json"
    out.parent.mkdir(parents=True, exist_ok=True); result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
