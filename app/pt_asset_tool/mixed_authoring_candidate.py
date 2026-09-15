from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from .authoring import verify_selected_context_for_asset, verify_workspace_manifest
from .blender_workspace import asset_workspace_name, blender_edit_root
from .static_roundtrip import _parse as parse_model062_bytes
from .rigid_authoring_candidate import _physique_names, build_rigid_candidate_blender_command
from .static_authoring_candidate import build_static_candidate_blender_command
from .smb_writer import _layout_for_bones

FORMAT = "PT_MIXED_PHYSIQUE_SAVED_BLENDER_CANDIDATE_PLAN_V1"
VERIFY_FORMAT = "PT_MIXED_PHYSIQUE_SAVED_BLENDER_CANDIDATE_VERIFY_V1"
SOURCE_FORMAT = "PT_MIXED_PHYSIQUE_SOURCE_ANALYSIS_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve(); path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def analyze_mixed_source(source: pathlib.Path | str) -> dict[str, Any]:
    source = pathlib.Path(source).resolve()
    parsed = parse_model062_bytes(source.read_bytes())
    rows=[]
    for name, obj in parsed["objects"].items():
        depths=[len(face.get("uv_layers") or []) for face in obj.get("faces") or []]
        single_layer=bool(depths) and min(depths)==1 and max(depths)==1
        local=bool(int(obj.get("nr") or 0) or int(obj.get("np") or 0) or int(obj.get("ns") or 0))
        phys=bool(obj.get("phys"))
        eligible=bool(int(obj.get("nv") or 0) >= 3 and int(obj.get("nf") or 0) >= 1 and single_layer and not local)
        rows.append({
            "name":name,
            "physique":phys,
            "adapter":"RIGID" if phys else "STATIC",
            "vertices":int(obj.get("nv") or 0),
            "faces":int(obj.get("nf") or 0),
            "texlinks":int(obj.get("nt") or 0),
            "object_local_key_counts":[int(obj.get("nr") or 0),int(obj.get("np") or 0),int(obj.get("ns") or 0)],
            "single_layer_texlink":single_layer,
            "candidate_eligible":eligible,
            "blockers":([] if eligible else (["OBJECT_LOCAL_ANIMATION_PRESENT"] if local else []) + (["MULTILAYER_OR_EMPTY_TEXLINK"] if not single_layer else []) + (["GEOMETRY_EMPTY"] if int(obj.get("nv") or 0)<3 or int(obj.get("nf") or 0)<1 else [])),
        })
    rigid=[r["name"] for r in rows if r["physique"]]
    static=[r["name"] for r in rows if not r["physique"]]
    mode="MIXED" if rigid and static else ("RIGID" if rigid else ("STATIC" if static else "UNKNOWN"))
    return {
        "format":SOURCE_FORMAT,
        "status":"PASS" if mode=="MIXED" else "FAIL",
        "source":str(source),"source_sha256":_sha256(source),"mode":mode,
        "object_count":len(rows),"rigid_objects":rigid,"static_objects":static,
        "eligible_rigid_objects":[r["name"] for r in rows if r["physique"] and r["candidate_eligible"]],
        "eligible_static_objects":[r["name"] for r in rows if not r["physique"] and r["candidate_eligible"]],
        "objects":rows,"client_modified":False,
    }


def plan_mixed_saved_blender_candidate(
    project_root: pathlib.Path | str, resolver, asset, *,
    skeleton: pathlib.Path | str | None = None,
    output: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    project_root=pathlib.Path(project_root).resolve()
    source=pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    analysis=analyze_mixed_source(source)
    blockers=[]
    if analysis.get("mode") != "MIXED": blockers.append("SOURCE_NOT_MIXED_PHYSIQUE")
    if not analysis.get("eligible_rigid_objects"): blockers.append("NO_ELIGIBLE_RIGID_OBJECT")
    if not analysis.get("eligible_static_objects"): blockers.append("NO_ELIGIBLE_STATIC_OBJECT")

    workspace=blender_edit_root(project_root,"generic_import",asset.primary_path)
    blend=workspace/"imported.blend"; manifest=workspace/"authoring_manifest.json"
    if not blend.is_file(): blockers.append("GENERIC_IMPORT_WORKSPACE_MISSING")
    if not manifest.is_file():
        manifest_verify={"status":"FAIL","errors":["AUTHORING_MANIFEST_MISSING"],"build_authorized":False,"client_write_authorized":False}
        blockers.append("AUTHORING_MANIFEST_MISSING")
    else:
        manifest_verify=verify_workspace_manifest(manifest)
        if manifest_verify.get("status") != "PASS": blockers.append("AUTHORING_WORKSPACE_PROVENANCE_FAILED")

    selected_context = dict((manifest_verify or {}).get("selected_context") or {})
    context_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver) if selected_context else {"status":"FAIL","errors":["SELECTED_CONTEXT_MISSING"]}
    if context_verify.get("status") != "PASS":
        blockers.append("MIXED_SELECTED_CONTEXT_MISMATCH")
    skeleton_row = dict(selected_context.get("skeleton_smb") or {})
    skeleton_logical = str(skeleton_row.get("logical") or getattr(asset,"binding_skeleton_smb",None) or "").replace("\\","/")
    skeleton_path = pathlib.Path(str(skeleton_row.get("path") or "")) if skeleton_row.get("path") else None
    if skeleton is not None:
        raw = pathlib.Path(skeleton).expanduser()
        if raw.is_absolute(): requested_path = raw.resolve()
        else: requested_path = pathlib.Path(resolver.resolve(str(skeleton).replace("\\","/"),required=True)).resolve()
        if skeleton_path is not None and requested_path != skeleton_path.resolve():
            blockers.append("MIXED_REQUESTED_SKELETON_DIFFERS_FROM_WORKSPACE_CONTEXT")
        skeleton_path = requested_path
    if skeleton_path is None or not skeleton_path.is_file():
        blockers.append("MIXED_RIGID_SKELETON_REQUIRED")

    if output is None:
        output_path=(project_root/"pt_build"/"candidate_build"/asset_workspace_name(asset.primary_path)/pathlib.PurePosixPath(asset.primary_path).name).resolve()
    else:
        raw=pathlib.Path(output).expanduser(); output_path=(raw if raw.is_absolute() else project_root/raw).resolve()
    if not _inside(project_root/"pt_build",output_path): blockers.append("OUTPUT_OUTSIDE_PT_BUILD")

    adapters={name:"pt_blender_to_smd_free_mesh_v3.py" for name in analysis.get("eligible_rigid_objects") or []}
    adapters.update({name:"pt_blender_to_smd_static_v1.py" for name in analysis.get("eligible_static_objects") or []})
    return {
        "format":FORMAT,"status":"READY" if not blockers else "BLOCKED",
        "authorization":"CANDIDATE_PT_BUILD_ONLY","asset_id":getattr(asset,"asset_id",None),"asset":asset.primary_path,
        "source":str(source),"source_sha256":analysis.get("source_sha256"),"analysis":analysis,
        "workspace":str(workspace),"blend":str(blend),"authoring_manifest":str(manifest),"manifest_verification":manifest_verify,
        "selected_context":selected_context,"selected_context_verification":context_verify,
        "skeleton":str(skeleton_path.resolve()) if skeleton_path and skeleton_path.is_file() else None,"skeleton_logical":skeleton_logical,
        "objects":list(adapters),"object_adapters":adapters,"output":str(output_path),"blockers":blockers,
        "pipeline_wired":True,"real_corpus_certified":False,
        "production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }


def validate_mixed_candidate_output(
    source: pathlib.Path | str, output: pathlib.Path | str, *,
    target_objects: list[str] | tuple[str,...],
    project_root: pathlib.Path | str | None = None,
    skeleton: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    source=pathlib.Path(source).resolve(); output=pathlib.Path(output).resolve()
    s=parse_model062_bytes(source.read_bytes()); o=parse_model062_bytes(output.read_bytes())
    targets={str(x) for x in target_objects}
    errors=[]
    if s["n"] != o["n"]: errors.append("OBJECT_COUNT")
    if s["mat_count"] != o["mat_count"]: errors.append("MATERIAL_COUNT")
    if s["mat_region"] != o["mat_region"]: errors.append("MATERIAL_REGION_BYTES")
    if set(s["objects"]) != set(o["objects"]): errors.append("OBJECT_NAMES")
    missing=sorted(targets-set(s["objects"]));
    if missing: errors.append("TARGET_MISSING")
    non_target=[]; target_rows=[]; unknown_by_object={}
    skeleton_names=None
    if skeleton is not None and project_root is not None:
        try:
            _ev, parsed_skeleton, _infos, _data = _layout_for_bones(pathlib.Path(project_root).resolve(), pathlib.Path(skeleton).resolve())
            skeleton_names={str(b["name"]).casefold() for b in parsed_skeleton["bones"]}
        except Exception as exc:
            errors.append(f"SKELETON_PARSE:{type(exc).__name__}")
    for name in sorted(set(s["objects"]) & set(o["objects"]),key=str.casefold):
        a=s["objects"][name]; b=o["objects"][name]
        if name not in targets:
            if a["block"] != b["block"]: non_target.append(name)
            continue
        if bool(a["phys"]) != bool(b["phys"]): errors.append(f"PHYSIQUE_MODE_CHANGED:{name}")
        if any([b["nr"],b["np"],b["ns"]]): errors.append(f"OBJECT_LOCAL_ANIMATION_PRESENT:{name}")
        depths=[len(f.get("uv_layers") or []) for f in b.get("faces") or []]
        if not depths or min(depths)!=1 or max(depths)!=1: errors.append(f"OUTPUT_TEXLINK_NOT_SINGLE_LAYER:{name}")
        unknown=[]
        if bool(b["phys"]) and skeleton_names is not None:
            bones=_physique_names(b)
            unknown=sorted({x for x in bones if x and x.casefold() not in skeleton_names},key=str.casefold)
            if unknown: errors.append(f"OUTPUT_PHYSIQUE_BONE_NOT_IN_SKELETON:{name}")
        if bool(b["phys"]): unknown_by_object[name]=unknown
        target_rows.append({
            "name":name,"adapter":"RIGID" if b["phys"] else "STATIC",
            "source_counts":[a["nv"],a["nf"],a["nt"]],"output_counts":[b["nv"],b["nf"],b["nt"]],
            "topology_changed":[a["nv"],a["nf"]] != [b["nv"],b["nf"]],
            "edit_observed":a["block"] != b["block"],
        })
    if non_target: errors.append("NON_TARGET_BLOCK_CHANGED")
    targets_without_edit=sorted([r["name"] for r in target_rows if not r["edit_observed"]],key=str.casefold)
    return {
        "format":VERIFY_FORMAT,"status":"PASS" if not errors else "FAIL",
        "source":str(source),"output":str(output),"targets":sorted(targets),"target_results":target_rows,
        "all_target_edits_observed":bool(target_rows) and not targets_without_edit,
        "targets_without_observed_edit":targets_without_edit,
        "unknown_physique_bones_by_object":unknown_by_object,
        "non_target_changed":non_target,"errors":errors,
        "mixed_modes_preserved":not any(str(x).startswith("PHYSIQUE_MODE_CHANGED:") for x in errors),
        "candidate_only":True,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }


def build_mixed_candidate_step_command(
    settings, candidate: dict[str, Any], *, object_name: str, source: pathlib.Path, output: pathlib.Path, report: pathlib.Path,
) -> list[str]:
    adapter=(candidate.get("object_adapters") or {}).get(object_name)
    step={
        "status":"READY", "blend":candidate["blend"], "source":str(pathlib.Path(source).resolve()),
        "source_sha256":_sha256(pathlib.Path(source)), "object":object_name, "output":str(pathlib.Path(output).resolve()),
    }
    if adapter == "pt_blender_to_smd_free_mesh_v3.py":
        step["skeleton"] = candidate["skeleton"]
        return build_rigid_candidate_blender_command(settings,step,report=report)
    if adapter == "pt_blender_to_smd_static_v1.py":
        return build_static_candidate_blender_command(settings,step,report=report)
    raise RuntimeError(f"unknown mixed candidate adapter for {object_name}: {adapter}")
