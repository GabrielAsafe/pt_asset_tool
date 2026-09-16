from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .motion_core import build_standalone_smb_bake_payload, load_smb_evaluator, write_payload
from .smb_writer import parse_smb_structural
from .release_1_coverage import CONTENT_DOMAINS, content_domain, content_domain_from_values
from .standalone_rigid_devtest import explicit_skeleton_candidate, standalone_rigid_context_eligible
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_STANDALONE_SMB_ANIMATION_POSE_DEVTEST_V1"
BATCH_FORMAT = "PT_STANDALONE_SMB_ANIMATION_POSE_DEVTEST_BATCH_V1"
AUDIT_FORMAT = "PT_SMB_ANIMATION_PHYSICAL_CORPUS_V1"


def _norm(v: str | None) -> str:
    return str(v or "").replace("\\", "/").strip("/")


def _work(root: pathlib.Path, domain: str, asset_path: str) -> pathlib.Path:
    safe = _norm(asset_path).replace("/", "__")
    return pathlib.Path(root).resolve() / "pt_build" / "devtest" / "standalone_animation_pose" / str(domain).lower() / safe


def _animated_smb(root: pathlib.Path, path: pathlib.Path) -> dict[str, Any]:
    ev = load_smb_evaluator(root)
    smb = ev.parse_smb(path)
    containers = [x for x in smb.get("header_frames") or [] if int(x.get("end") or 0) > int(x.get("start") or 0)]
    key_count = sum(len(b.get("rot") or []) + len(b.get("pos") or []) + len(b.get("scale") or []) for b in smb.get("bones") or [])
    return {"animated": bool(containers and key_count), "container_count": len(containers), "key_count": key_count}



def audit_smb_animation_corpus(registry, resolver, *, sample_limit: int = 25) -> dict[str, Any]:
    """Parse every physical SMB and census existing TmFrame/key animation by domain.

    This is deliberately corpus-wide.  Blender pose-space remains representative,
    but Release 1.0 presence/absence of existing SMB animation must not be inferred
    only from INX/model bindings.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    ev = load_smb_evaluator(root)
    by_domain = {d: {
        "smb_file_count": 0, "parse_pass_count": 0, "structural_support_pass_count": 0,
        "external_parent_support_count": 0, "duplicate_name_support_count": 0, "animated_smb_file_count": 0,
        "active_container_count": 0, "rot_key_count": 0, "pos_key_count": 0, "scale_key_count": 0,
    } for d in CONTENT_DOMAINS}
    failures: list[dict[str, Any]] = []
    animated_rows: list[dict[str, Any]] = []
    total = parsed = animated = 0
    for record in registry.records:
        if str(record.get("extension") or "").casefold() != ".smb":
            continue
        logical = _norm(record.get("relative_path"))
        domain = content_domain_from_values(logical, str(record.get("category_hint") or ""))
        if domain not in by_domain:
            continue
        total += 1
        by_domain[domain]["smb_file_count"] += 1
        try:
            physical = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            strict_error = None
            support_only = False
            try:
                smb = ev.parse_smb(physical)
            except Exception as exc:
                strict_error = exc
                # Support SMBs can be structurally valid serialized containers
                # while still being impossible to evaluate as one standalone
                # Blender hierarchy.  Two physically observed reasons are an
                # external parent supplied by another container and duplicate
                # NodeName entries.  Downgrade only those exact hierarchy
                # failures after the relaxed parser proves every object layout
                # closes; they remain explicitly *not* pose-certified.
                msg = str(exc).casefold()
                if "missing parent" not in msg and "duplicate nodename" not in msg:
                    raise
                smb = parse_smb_structural(root, physical)
                if "missing parent" in msg and not smb.get("missing_parent_names"):
                    raise
                if "duplicate nodename" in msg and not smb.get("duplicate_node_names"):
                    raise
                support_only = True

            containers = [x for x in smb.get("header_frames") or [] if int(x.get("end") or 0) > int(x.get("start") or 0)]
            rot = sum(len(b.get("rot") or []) for b in smb.get("bones") or [])
            pos = sum(len(b.get("pos") or []) for b in smb.get("bones") or [])
            scale = sum(len(b.get("scale") or []) for b in smb.get("bones") or [])
            key_count = rot + pos + scale
            parsed += 1
            by_domain[domain]["parse_pass_count"] += 1
            if support_only:
                by_domain[domain]["structural_support_pass_count"] += 1
                if smb.get("missing_parent_names"):
                    by_domain[domain]["external_parent_support_count"] += 1
                if smb.get("duplicate_node_names"):
                    by_domain[domain]["duplicate_name_support_count"] += 1
                continue
            is_animated = bool(containers and key_count)
            if is_animated:
                animated += 1
                row = {
                    "path": logical, "domain": domain, "active_container_count": len(containers),
                    "rot_key_count": rot, "pos_key_count": pos, "scale_key_count": scale, "key_count": key_count,
                }
                animated_rows.append(row)
                by_domain[domain]["animated_smb_file_count"] += 1
                by_domain[domain]["active_container_count"] += len(containers)
                by_domain[domain]["rot_key_count"] += rot
                by_domain[domain]["pos_key_count"] += pos
                by_domain[domain]["scale_key_count"] += scale
        except Exception as exc:
            failures.append({"path": logical, "domain": domain, "error": f"{type(exc).__name__}: {exc}"})
    animated_rows.sort(key=lambda r: (str(r["domain"]), str(r["path"]).casefold()))
    return {
        "format": AUDIT_FORMAT,
        "status": "PASS" if total and parsed == total and not failures else ("EMPTY" if not total else "FAIL"),
        "smb_file_count": total, "parse_pass_count": parsed, "animated_smb_file_count": animated,
        "by_domain": by_domain,
        "animated_rows": animated_rows,
        "failure_sample": failures[: max(0, int(sample_limit))], "failure_count": len(failures),
        "policy": {
            "presence_requires_active_tmframe_and_existing_key": True,
            "corpus_wide_parse_required": True,
            "external_parent_support_is_structural_not_standalone_animation_certification": True,
            "duplicate_nodename_support_is_structural_not_standalone_animation_certification": True,
            "inx_not_required_for_standalone_smb_animation": True,
        },
        "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }

def choose_standalone_animation_representatives(registry, resolver, *, per_domain: int = 2) -> dict[str, list[dict[str, Any]]]:
    root = pathlib.Path(getattr(registry, "project_root", pathlib.Path(__file__).resolve().parents[1]))
    # The evaluator is project-relative, not registry-relative.
    root = pathlib.Path(__file__).resolve().parents[1]
    groups = {d: [] for d in CONTENT_DOMAINS}
    for asset in registry.assets:
        domain = content_domain(asset)
        if domain not in groups or not standalone_rigid_context_eligible(asset):
            continue
        probe = explicit_skeleton_candidate(registry, asset)
        if not probe.get("candidate_available"):
            continue
        logical = _norm(probe.get("candidate_smb"))
        try:
            physical = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            info = _animated_smb(root, physical)
        except Exception:
            continue
        if not info["animated"]:
            continue
        groups[domain].append({
            "asset_id": asset.asset_id, "asset": asset.primary_path, "domain": domain,
            "skeleton_smb": logical, "candidate_basis": probe.get("candidate_basis"),
            "container_count": info["container_count"], "key_count": info["key_count"],
        })
    for d in groups:
        groups[d].sort(key=lambda r: (-int(r["key_count"]), -int(r["container_count"]), str(r["asset"]).casefold()))
        groups[d] = groups[d][: max(0, int(per_domain))]
    return groups


def run_standalone_animation_pose_devtest(settings, registry, resolver, certifications, *, row: dict[str, Any], fps: int = 30) -> dict[str, Any]:
    asset = registry.resolve(row["asset"])
    root = pathlib.Path(settings.project_root).resolve()
    domain = str(row["domain"])
    work = _work(root, domain, asset.primary_path)
    if work.exists(): shutil.rmtree(work)
    import_work=work/"01_import"; bake_work=work/"02_bake"; check_work=work/"03_pose_check"
    for p in (import_work,bake_work,check_work): p.mkdir(parents=True,exist_ok=True)
    source=pathlib.Path(resolver.resolve(asset.primary_path,required=True)).resolve()
    skeleton=pathlib.Path(resolver.resolve(row["skeleton_smb"],required=True)).resolve()

    runner=ValidationRunner(ValidationContext(settings,resolver,certifications))
    overlay, texture_report=runner._texture_overlay(asset,import_work)
    pristine=import_work/"pristine_import.blend"
    importer=root/"pt_asset_tool" / "legacy_runtime"/"pt_smd_blender_import_v3_static_armature.py"
    run_logged(settings.blender_command()+[
        "--background","--python-exit-code","1","--python",str(importer),"--",
        "--smd",str(source),"--skeleton",str(skeleton),"--client-root",str(overlay),"--out",str(pristine),"--no-pack",
    ],import_work/"01_import.log")

    payload=build_standalone_smb_bake_payload(root,skeleton,fps=int(fps),max_actions=4,max_frames_per_action=120)
    payload_path=bake_work/"motion_bake_payload.json"; write_payload(payload_path,payload)
    animated=bake_work/"animated.blend"; bake_report=bake_work/"bake_report.json"
    run_logged(settings.blender_command()+[
        "--background",str(pristine),"--python-exit-code","1","--python",str(root/"pt_asset_tool"/"blender"/"bake_actions.py"),"--",
        "--payload",str(payload_path),"--out",str(animated),"--report",str(bake_report),
    ],bake_work/"01_bake.log")
    baked=json.loads(bake_report.read_text(encoding="utf-8"))
    if baked.get("check")!="PASS": raise RuntimeError(f"standalone SMB bake failed: {baked}")
    pose_report=check_work/"pose_space.json"
    run_logged(settings.blender_command()+[
        "--background",str(animated),"--python-exit-code","1","--python",str(root/"pt_asset_tool"/"blender"/"check_baked_animation_pose.py"),"--",
        "--payload",str(payload_path),"--report",str(pose_report),
    ],check_work/"01_pose_check.log")
    pose=json.loads(pose_report.read_text(encoding="utf-8"))
    if pose.get("status")!="PASS": raise RuntimeError(f"standalone SMB pose-space gate failed: {pose.get('errors')}")
    result={
        "format":FORMAT,"status":"PASS","domain":domain,"asset":asset.primary_path,"skeleton_smb":_norm(row["skeleton_smb"]),
        "source_mode":"STANDALONE_SMB_TMFRAME","automatic_actions_checked":int(pose.get("action_count") or 0),
        "checked_frames":int(pose.get("checked_frames") or 0),"checked_bone_frames":int(pose.get("checked_bone_frames") or 0),
        "max_abs_matrix_error":pose.get("max_abs_matrix_error"),"pose_report":str(pose_report),"bake_report":str(bake_report),
        "texture_ready":bool(texture_report.get("ready",True)),"automatic_pose_space_pass":True,
        "track_key_counts":dict(payload.get("track_key_counts") or {}),
        "runtime_authorized":False,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
    rp=work/"result.json"; result["report"]=str(rp); rp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def run_standalone_animation_pose_devtest_batch(settings,registry,resolver,certifications,rows:list[dict[str,Any]],*,fps:int=30)->dict[str,Any]:
    results=[]; failures=[]
    for row in rows:
        try: results.append(run_standalone_animation_pose_devtest(settings,registry,resolver,certifications,row=row,fps=fps))
        except Exception as exc:
            failure={"asset":row.get("asset"),"domain":row.get("domain"),"error":f"{type(exc).__name__}: {exc}"}
            try:
                work=_work(pathlib.Path(settings.project_root).resolve(),str(row.get("domain") or ""),str(row.get("asset") or ""))
                bake_path=work/"02_bake"/"bake_report.json"
                if bake_path.is_file():
                    bake=json.loads(bake_path.read_text(encoding="utf-8"))
                    failure["bake_diagnostic"]={
                        "check":bake.get("check"),
                        "affine_representation":bake.get("affine_representation"),
                        "affine_split_bone_count":bake.get("affine_split_bone_count"),
                        "max_source_basis_trs_error":bake.get("max_source_basis_trs_error"),
                        "max_affine_factor_reconstruction_error":bake.get("max_affine_factor_reconstruction_error"),
                        "live_source_pose_check":bake.get("live_source_pose_check"),
                        "live_source_pose_max_error":bake.get("live_source_pose_max_error"),
                        "live_source_pose_mismatch_sample":bake.get("live_source_pose_mismatch_sample"),
                        "report":str(bake_path),
                    }
                pose_path=work/"03_pose_check"/"pose_space.json"
                if pose_path.is_file():
                    pose=json.loads(pose_path.read_text(encoding="utf-8"))
                    failure["pose_diagnostic"]={
                        "status":pose.get("status"),"errors":pose.get("errors"),
                        "pose_mismatch_diagnostic":pose.get("pose_mismatch_diagnostic"),
                        "max_abs_matrix_error":pose.get("max_abs_matrix_error"),
                        "max_expected_basis_trs_reconstruction_error":pose.get("max_expected_basis_trs_reconstruction_error"),
                        "non_trs_basis_mismatch_count":pose.get("non_trs_basis_mismatch_count"),
                        "actions":pose.get("actions"),"report":str(pose_path),
                    }
            except Exception:
                pass
            failures.append(failure)
    result={
        "format":BATCH_FORMAT,"status":"PASS" if rows and results and not failures else ("EMPTY" if not rows else "FAIL"),
        "requested":len(rows),"passed_assets":[x.get("asset") for x in results],"failed_assets":failures,"results":results,
        "automatic_only":True,"runtime_authorized":False,"production_authorized":False,"client_write_authorized":False,"client_modified":False,
    }
    out=pathlib.Path(settings.project_root).resolve()/"pt_build"/"devtest"/"standalone_animation_pose"/"batch_result.json"
    out.parent.mkdir(parents=True,exist_ok=True); result["report"]=str(out); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result
