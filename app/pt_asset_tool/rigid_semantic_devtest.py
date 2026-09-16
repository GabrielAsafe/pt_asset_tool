from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .authoring import authoring_plan, build_selected_authoring_context, verify_selected_context_for_asset
from .build_provenance import sha256_file, write_build_provenance
from .rigid_authoring_candidate import build_rigid_candidate_blender_command
from .rigid_authoring_stress import inspect_rigid_profile_stress_scope, validate_rigid_profile_stress_output
from .rigid_model_info import config_semantic_id, lod_node_coverage, effective_lod_node_coverage, usable_model_info_configs, lod_model_info_configs
from .static_roundtrip import _parse as parse_model062_bytes
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner
from .blender_workspace import asset_workspace_name

FORMAT = "PT_RIGID_SEMANTIC_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_RIGID_SEMANTIC_AUTOMATED_DEVTEST_BATCH_V1"


def _cfg_for(asset, model_info_inx: str) -> dict[str, Any]:
    wanted = str(model_info_inx or "").replace("\\", "/").casefold()
    hits = [c for c in lod_model_info_configs(asset) if str(c.get("inx") or "").replace("\\", "/").casefold() == wanted]
    if len(hits) != 1:
        raise RuntimeError(f"model-info must match exactly one LOD-bearing asset config: {model_info_inx}; hits={len(hits)}")
    return hits[0]


def _valid_lods(asset, cfg: dict[str, Any]) -> list[str]:
    out=[]
    groups=cfg.get("lod_groups") or {}
    for lod in ("high", "default", "low"):
        if not (groups.get(lod) or []):
            continue
        cov=effective_lod_node_coverage(asset,cfg,lod)
        if cov.get("status") == "PASS":
            out.append(lod)
    return out


def _work_root(project_root: pathlib.Path, domain: str, asset_path: str, cfg: dict[str, Any]) -> pathlib.Path:
    return (
        pathlib.Path(project_root).resolve() / "pt_build" / "devtest" / "rigid_semantic_auto" /
        str(domain).lower() / f"{asset_workspace_name(asset_path)}__{config_semantic_id(cfg)}"
    )


def run_rigid_semantic_automated_devtest(
    settings,
    asset_registry,
    resolver,
    certifications,
    *,
    asset_path: str,
    model_info_inx: str,
    domain: str,
    skeleton_smb: str | None = None,
    amplitude: float = 0.12,
    operation_timeout_seconds: float = 180.0,
    progress=None,
) -> dict[str, Any]:
    def emit(stage: str) -> None:
        if progress:
            progress(stage)

    asset=asset_registry.resolve(asset_path)
    emit(f"ASSET_START {asset.primary_path} model_info={model_info_inx}")
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"rigid semantic devtest requires rigid Model0.62, got {asset.family}")
    cfg=_cfg_for(asset,model_info_inx)
    skeleton_logical=str(cfg.get("motion_smb") or skeleton_smb or asset.binding_skeleton_smb or "").replace("\\", "/")
    if not skeleton_logical:
        raise RuntimeError(f"rigid semantic devtest requires an explicit/resolved skeleton: {asset.binding_mode}/{asset.binding_source}")
    if not asset.rigid_binding_ready and not skeleton_smb:
        raise RuntimeError(f"rigid semantic devtest requires resolved binding or explicit skeleton: {asset.binding_mode}/{asset.binding_source}")
    valid_lods=_valid_lods(asset,cfg)
    if not valid_lods:
        raise RuntimeError("selected INX config has no generic-importable LOD groups")
    import_lod=next((x for x in ("default","high","low") if x in valid_lods), valid_lods[0])

    project_root=pathlib.Path(settings.project_root).resolve()
    work=_work_root(project_root,domain,asset.primary_path,cfg)
    if work.exists():
        shutil.rmtree(work)
    import_work,edit_work,build_work,reimport_work=[work/x for x in ("01_import","02_edit","03_candidate","04_reimport")]
    for p in (import_work,edit_work,build_work,reimport_work): p.mkdir(parents=True,exist_ok=True)

    runner=ValidationRunner(ValidationContext(settings,resolver,certifications))
    overlay,texture_report=runner._texture_overlay(asset,import_work)
    model_info=pathlib.Path(resolver.resolve(model_info_inx,required=True)).resolve()
    skeleton=pathlib.Path(resolver.resolve(skeleton_logical,required=True)).resolve()
    if cfg.get("motion_smb"):
        runner.structural(asset)
        preselected=runner._preflight_rigid_import(asset,import_lod,model_info=model_info_inx,require_unambiguous=True)
        source,pristine,actual_lod,_=runner._prepare_rigid_blend(
            asset,import_lod,import_work,overlay,model_info=model_info_inx,require_unambiguous=True,preselected=preselected,
        )
        explicit_skeleton_lod=False
    else:
        pre=runner._preflight_explicit_skeleton_lod_import(
            asset,import_lod,model_info=model_info_inx,skeleton_logical=skeleton_logical,require_unambiguous=True,
        )
        source,pristine=runner._prepare_explicit_skeleton_lod_blend(asset,import_work,overlay,pre)
        actual_lod=pre["lod"]
        explicit_skeleton_lod=True
    context_basis = ({
        "kind":"AUTOMATED_EXPLICIT_SKELETON_LOD",
        "roundtrip_target":asset.primary_path,
        "structural_gate":"PASS",
    } if explicit_skeleton_lod else None)
    selected_coverage=effective_lod_node_coverage(asset,cfg,actual_lod)
    selected_context=build_selected_authoring_context(
        model_info_logical=model_info_inx,model_info_path=model_info,
        skeleton_logical=skeleton_logical,skeleton_path=skeleton,
        lod=actual_lod,lod_groups=cfg.get("lod_groups") or {},selection_basis=context_basis,
        selected_lod_nodes=list(selected_coverage.get("effective_selected_nodes") or []),
        lod_selection_mode=str(selected_coverage.get("selection_mode") or "MODEL_GROUP_KEYS"),
    )
    context_verify=verify_selected_context_for_asset(selected_context,asset,resolver=resolver)
    if context_verify.get("status") != "PASS":
        raise RuntimeError(f"selected semantic context failed: {context_verify.get('errors')}")

    base_plan=authoring_plan(asset,source)
    scope=inspect_rigid_profile_stress_scope(base_plan,selected_context)
    if not scope.get("scope_complete"):
        raise RuntimeError(f"rigid semantic scope incomplete: {scope.get('missing_or_ineligible_objects')}")
    objects=list(scope.get("eligible_objects") or [])
    object_lods=dict(scope.get("object_lods") or {})
    # Only exercise objects belonging to LOD groups proven representable for this selected INX.
    objects=[x for x in objects if object_lods.get(x) in valid_lods]
    object_lods={x:object_lods[x] for x in objects}
    if not objects:
        raise RuntimeError("rigid semantic devtest has no eligible target objects")

    edit_plan={
        "format":"PT_RIGID_SEMANTIC_AUTOMATED_EDIT_PLAN_V1","domain":domain,"asset":asset.primary_path,
        "objects":objects,"object_lods":object_lods,"amplitude":float(amplitude),"source_sha256":sha256_file(source),
        "selected_context":selected_context,
    }
    edit_plan_path=edit_work/"edit_plan.json"
    edit_plan_path.write_text(json.dumps(edit_plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    edited_blend=edit_work/"automatically_edited.blend"; edit_report_path=edit_work/"edit_report.json"
    edit_script=project_root/"pt_asset_tool"/"blender"/"apply_rigid_profile_devtest.py"
    emit(f"BLENDER_EDIT_START {asset.primary_path}")
    run_logged(settings.blender_command()+[
        "--background",str(pristine),"--python-exit-code","1","--python",str(edit_script),"--",
        "--plan",str(edit_plan_path),"--out",str(edited_blend),"--report",str(edit_report_path),
    ],edit_work/"01_automatic_edit.log", timeout_seconds=float(operation_timeout_seconds))
    emit(f"BLENDER_EDIT_DONE {asset.primary_path}")
    edit_report=json.loads(edit_report_path.read_text(encoding="utf-8"))
    if edit_report.get("status") != "PASS" or int(edit_report.get("target_count") or 0) != len(objects):
        raise RuntimeError(f"automatic semantic rigid edit failed: {edit_report}")

    # FIX22_CORE_CORPUS_AND_T5_ATTRIBUTION: preserve physical object-table
    # identity across Blender edit -> writer -> semantic validation.
    object_refs=[]
    for target in (edit_report.get("targets") or []):
        name=str(target.get("object") or "")
        object_index=target.get("object_index")
        if not name or object_index is None:
            raise RuntimeError(f"automatic rigid edit did not preserve physical object identity: {target}")
        object_refs.append({"name":name,"index":int(object_index)})
    if len(object_refs) != len(objects):
        raise RuntimeError(f"automatic rigid edit object identity count mismatch: refs={len(object_refs)} objects={len(objects)}")

    output=build_work/pathlib.PurePosixPath(asset.primary_path).name
    steps_dir=build_work/"steps"; steps_dir.mkdir(parents=True,exist_ok=True)
    current_source=pathlib.Path(source).resolve(); steps=[]
    for idx,object_ref in enumerate(object_refs,start=1):
        object_name=str(object_ref["name"]); object_index=int(object_ref["index"])
        step_output=output if idx==len(object_refs) else steps_dir/f"{idx:02d}_{object_name}.smd"
        step_report=steps_dir/f"{idx:02d}_{object_name}.writer.json"; step_log=steps_dir/f"{idx:02d}_{object_name}.log"
        candidate={"status":"READY","blend":str(edited_blend),"source":str(current_source),"source_sha256":sha256_file(current_source),"skeleton":str(skeleton),"object":object_name,"object_index":object_index,"output":str(step_output)}
        emit(f"WRITER_STEP_START {idx}/{len(object_refs)} {asset.primary_path} object={object_name} object_index={object_index}")
        run_logged(
            build_rigid_candidate_blender_command(settings,candidate,report=step_report),
            step_log, timeout_seconds=float(operation_timeout_seconds),
        )
        emit(f"WRITER_STEP_DONE {idx}/{len(object_refs)} {asset.primary_path} object={object_name} object_index={object_index}")
        data=json.loads(step_report.read_text(encoding="utf-8"))
        steps.append({"index":idx,"object":object_name,"object_index":object_index,"lod":object_lods.get(object_name),"input_sha256":sha256_file(current_source),"output_sha256":sha256_file(step_output),"source_counts":data.get("source_counts"),"output_counts":data.get("output_counts"),"max_vertex_fit_error":data.get("max_vertex_fit_error")})
        current_source=step_output.resolve()

    verification=validate_rigid_profile_stress_output(project_root,source,output,skeleton,object_refs)
    if verification.get("status") != "PASS":
        raise RuntimeError(f"combined semantic rigid candidate failed: {verification.get('errors')}")
    writer_summary_path=build_work/"writer_summary.json"
    writer_summary_path.write_text(json.dumps({"tool":"PT_RIGID_SEMANTIC_AUTOMATED_DEVTEST_WRITER_V1","step_count":len(steps),"steps":steps,"output_sha256":sha256_file(output)},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    provenance=write_build_provenance(
        output,asset=asset,source=source,build_mode="CANDIDATE_RIGID_SEMANTIC_AUTOMATED_DEVTEST",
        adapter="pt_blender_to_smd_free_mesh_v3.py",build_status="PASS",production_authorized=False,
        evidence={"automated_devtest":True,"semantic_domain":domain,"candidate_objects":objects,"candidate_object_refs":object_refs,"valid_lods":valid_lods,"explicit_skeleton_lod":explicit_skeleton_lod,"all_target_edits_observed":bool(verification.get("all_target_edits_observed")),"non_target_changed":list(verification.get("non_target_changed") or []),"unknown_physique_bones_by_object":dict(verification.get("unknown_physique_bones_by_object") or {}),"verification_errors":list(verification.get("errors") or []),"writer_summary":str(writer_summary_path)},
        selected_context=selected_context,
    )

    parsed_candidate=parse_model062_bytes(output.read_bytes())
    reimports={}
    import_script=project_root/"pt_asset_tool" / "legacy_runtime"/"pt_smd_blender_import_v3_static_armature.py"
    check_script=project_root/"pt_asset_tool"/"blender"/"check_rigid_profile_devtest.py"
    groups=cfg.get("lod_groups") or {}

    # FIX24_RELEASE_CAPABILITY_TARGET_SEPARATION: mirror the importer's exact
    # INX ModelName matching semantics and preserve every physical SMD object.
    # A name-keyed dict is lossy when several object-table rows share NodeName.
    def _inx_slot_matches_node_name(slot_name: str, node_name: str) -> bool:
        slot_key=str(slot_name).encode("latin-1",errors="replace").lower()
        node_key=str(node_name).encode("latin-1",errors="replace").lower()
        return node_key[:16] == slot_key if len(slot_key) == 16 else node_key == slot_key

    candidate_object_rows=list(parsed_candidate.get("object_list") or [])
    for lod in valid_lods:
        lod_cov=effective_lod_node_coverage(asset,cfg,lod)
        expected_names=list(lod_cov.get("effective_selected_nodes") or groups.get(lod) or [])
        missing_names=[
            name for name in expected_names
            if not any(_inx_slot_matches_node_name(name,str(obj.get("name") or "")) for obj in candidate_object_rows)
        ]
        if missing_names:
            raise RuntimeError(f"candidate missing {lod} object(s) before reimport: {missing_names}")
        selected_refs=[]
        for obj in candidate_object_rows:
            node_name=str(obj.get("name") or "")
            if any(_inx_slot_matches_node_name(name,node_name) for name in expected_names):
                selected_refs.append({
                    "name":node_name,
                    "index":int(obj["index"]),
                    "vertices":int(obj["nv"]),
                    "faces":int(obj["nf"]),
                })
        if not selected_refs:
            raise RuntimeError(f"candidate has no physical {lod} objects before reimport")
        contract={
            "format":"PT_RIGID_SEMANTIC_AUTOMATED_REIMPORT_EXPECTED_V1",
            "lod":lod,
            "objects":{},
            "object_refs":selected_refs,
            "selection_semantics":"SERIALIZED_MODEL_KEY_16_OR_EXACT_PHYSICAL_OBJECT_INDEX",
        }
        expected_path=reimport_work/f"expected_{lod}.json"; expected_path.write_text(json.dumps(contract,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        blend=reimport_work/f"candidate_{lod}.blend"
        reimport_cmd=settings.blender_command()+[
            "--background","--python-exit-code","1","--python",str(import_script),"--",
            "--smd",str(output),"--skeleton",str(skeleton),"--model-info",str(model_info),"--lod",lod,"--client-root",str(overlay),"--out",str(blend),"--no-pack",
        ]
        if lod_cov.get("selection_mode") == "SINGLE_TIER_FULL_CONTAINER":
            reimport_cmd.append("--single-tier-full-container")
        emit(f"REIMPORT_START {asset.primary_path} lod={lod}")
        run_logged(reimport_cmd,reimport_work/f"01_import_{lod}.log", timeout_seconds=float(operation_timeout_seconds))
        check_report=reimport_work/f"check_{lod}.json"
        run_logged(settings.blender_command()+["--background",str(blend),"--python-exit-code","1","--python",str(check_script),"--","--expected",str(expected_path),"--report",str(check_report)],reimport_work/f"02_check_{lod}.log", timeout_seconds=float(operation_timeout_seconds))
        emit(f"REIMPORT_DONE {asset.primary_path} lod={lod}")
        checked=json.loads(check_report.read_text(encoding="utf-8"))
        if checked.get("status") != "PASS": raise RuntimeError(f"candidate {lod} reimport check failed: {checked.get('errors')}")
        reimports[lod]={"status":"PASS","expected_objects":expected_names,"expected_object_refs":[{"name":x["name"],"index":x["index"]} for x in selected_refs],"checked_object_count":checked.get("checked_object_count"),"blend":str(blend),"check_report":str(check_report)}

    result={
        "format":FORMAT,"status":"PASS","domain":domain,"asset":asset.primary_path,"model_info_inx":model_info_inx,
        "skeleton_smb":skeleton_logical,"explicit_skeleton_lod":explicit_skeleton_lod,
        "source_sha256":sha256_file(source),"valid_lods":valid_lods,"selected_context_verification":context_verify.get("status"),
        "texture_ready":bool(texture_report.get("ready",True)),
        "automatic_edit":{"status":edit_report.get("status"),"amplitude":edit_report.get("amplitude"),"target_count":edit_report.get("target_count"),"objects":objects,"object_refs":object_refs,"report":str(edit_report_path)},
        "candidate":{"status":verification.get("status"),"artifact":str(output),"artifact_sha256":sha256_file(output),"provenance":str(provenance),"writer_step_count":len(steps),"all_target_edits_observed":bool(verification.get("all_target_edits_observed")),"targets_without_observed_edit":list(verification.get("targets_without_observed_edit") or []),"non_target_changed":list(verification.get("non_target_changed") or []),"unknown_physique_bones_by_object":dict(verification.get("unknown_physique_bones_by_object") or {}),"errors":list(verification.get("errors") or []),"writer_summary":str(writer_summary_path)},
        "reimport":reimports,"automatic_devtest_pass":True,"runtime_authorized":False,"production_authorized":False,"client_write_authorized":False,"client_modified":False,"workdir":str(work),
    }
    report=work/"result.json"; result["report"]=str(report); report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    emit(f"ASSET_DONE {asset.primary_path} status=PASS")
    return result


def run_rigid_semantic_automated_devtest_batch(
    settings, asset_registry, resolver, certifications, rows: list[dict[str, Any]], *,
    amplitude: float = 0.12, operation_timeout_seconds: float = 180.0,
    progress=None, resume: bool = True,
) -> dict[str, Any]:
    passed=[]; failed=[]; results=[]; resumed=[]
    batch_out=pathlib.Path(settings.project_root).resolve()/"pt_build"/"devtest"/"rigid_semantic_auto"/"batch_result.json"
    progress_out=batch_out.with_name("batch_progress.json")

    def emit(message: str) -> None:
        if progress:
            progress(message)

    def checkpoint(index: int, current: str | None) -> None:
        payload={
            "format":"PT_RIGID_SEMANTIC_AUTOMATED_DEVTEST_BATCH_PROGRESS_V1",
            "requested":len(rows),"completed":len(passed)+len(failed),"index":index,
            "current":current,"passed_assets":passed,"failed_assets":failed,"resumed_assets":resumed,
            "client_write_authorized":False,"client_modified":False,
        }
        progress_out.parent.mkdir(parents=True,exist_ok=True)
        progress_out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    for idx,row in enumerate(rows,start=1):
        asset_path=str(row.get("asset") or "")
        emit(f"BATCH {idx}/{len(rows)} START {asset_path}")
        try:
            asset=asset_registry.resolve(asset_path)
            cfg=_cfg_for(asset,row["model_info_inx"])
            existing=_work_root(pathlib.Path(settings.project_root),row["domain"],asset.primary_path,cfg)/"result.json"
            if resume and existing.is_file():
                try:
                    prior=json.loads(existing.read_text(encoding="utf-8"))
                    source_path=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
                    if (prior.get("status")=="PASS" and prior.get("asset")==asset.primary_path
                        and prior.get("model_info_inx")==row["model_info_inx"]
                        and prior.get("source_sha256")==sha256_file(source_path)):
                        results.append(prior); passed.append(asset_path); resumed.append(asset_path)
                        emit(f"BATCH {idx}/{len(rows)} RESUME_PASS {asset_path}")
                        checkpoint(idx,None)
                        continue
                except Exception:
                    pass
            result=run_rigid_semantic_automated_devtest(
                settings,asset_registry,resolver,certifications,asset_path=row["asset"],
                model_info_inx=row["model_info_inx"],domain=row["domain"],
                skeleton_smb=row.get("skeleton_smb"),amplitude=amplitude,
                operation_timeout_seconds=float(operation_timeout_seconds),
                progress=lambda m,idx=idx: emit(f"BATCH {idx}/{len(rows)} {m}"),
            )
            results.append(result); passed.append(asset_path)
            emit(f"BATCH {idx}/{len(rows)} DONE {asset_path} status=PASS")
        except Exception as exc:
            failed.append({"asset":row.get("asset"),"model_info_inx":row.get("model_info_inx"),"domain":row.get("domain"),"error":f"{type(exc).__name__}: {exc}"})
            emit(f"BATCH {idx}/{len(rows)} DONE {asset_path} status=FAIL error={type(exc).__name__}")
        checkpoint(idx,None)
    result={
        "format":BATCH_FORMAT,"status":"PASS" if results and not failed else "FAIL",
        "requested":len(rows),"passed_assets":passed,"failed_assets":failed,"results":results,
        "resumed_assets":resumed,"operation_timeout_seconds":float(operation_timeout_seconds),
        "automatic_only":True,"runtime_authorized":False,"production_authorized":False,
        "client_write_authorized":False,"client_modified":False,
    }
    batch_out.parent.mkdir(parents=True,exist_ok=True); result["report"]=str(batch_out)
    batch_out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    progress_out.unlink(missing_ok=True)
    return result
