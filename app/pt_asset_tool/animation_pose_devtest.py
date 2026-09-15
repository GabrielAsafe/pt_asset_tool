from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

from .motion_core import build_bake_payload, resolve_asset_motion_context, write_payload, load_smb_evaluator
from .rigid_model_info import lod_node_coverage, effective_lod_node_coverage, usable_model_info_configs, classify_asset_model_info_context
from .utils import run_logged, sha256_file
from .release_1_coverage import content_domain
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_ANIMATION_POSESPACE_AUTOMATED_DEVTEST_V1"
BATCH_FORMAT = "PT_ANIMATION_POSESPACE_AUTOMATED_DEVTEST_BATCH_V1"


def _norm(v: str) -> str:
    return str(v or "").replace("\\", "/").strip("/")


def _config(asset, model_info_inx: str) -> dict[str, Any]:
    q = _norm(model_info_inx).casefold()
    hits = [c for c in usable_model_info_configs(asset) if _norm(c.get("inx")).casefold() == q]
    if len(hits) != 1:
        raise RuntimeError(f"expected exactly one selected model-info config: {model_info_inx}; hits={len(hits)}")
    return hits[0]


def _choose_lod(asset, cfg: dict[str, Any]) -> str:
    for lod in ("default", "high", "low"):
        if (cfg.get("lod_groups") or {}).get(lod) and effective_lod_node_coverage(asset, cfg, lod).get("status") == "PASS":
            return lod
    raise RuntimeError("selected animation context has no physically representable LOD")


def _work(root: pathlib.Path, domain: str, asset_path: str) -> pathlib.Path:
    safe = asset_path.replace("\\", "/").strip("/").replace("/", "__")
    return root / "pt_build" / "devtest" / "animation_pose_auto" / domain.lower() / safe


def choose_animation_pose_representatives(registry, domain: str, *, limit: int = 2) -> list[dict[str, Any]]:
    """Choose rigid animation witnesses whose selected INX really owns a motion SMB.

    ``animation_binding_ready`` is asset-level evidence and is insufficient for a
    particular model-info row: an equipment INX can describe LOD geometry while a
    different INX supplies the motion container.  The pose gate must select the
    latter explicitly or it can fail with ``hits=0`` despite a valid animation
    binding elsewhere on the same asset.
    """
    candidates=[]
    for asset in registry.assets:
        if asset.family != 'SMD_MODEL_062_RIGID_PHYSIQUE' or content_domain(asset) != str(domain):
            continue
        if not bool(getattr(asset,'animation_binding_ready',False)):
            continue
        cls=classify_asset_model_info_context(asset)
        for cfg in usable_model_info_configs(asset):
            motion_smb=_norm(cfg.get('motion_smb'))
            inx=_norm(cfg.get('inx'))
            if not motion_smb or not inx or not bool(cfg.get('motion_resolved', True)):
                continue
            valid=[]; score=0
            for lod in ('high','default','low'):
                groups=(cfg.get('lod_groups') or {}).get(lod) or []
                if groups and effective_lod_node_coverage(asset,cfg,lod).get('status') == 'PASS':
                    valid.append(lod); score += len(groups)
            if not valid:
                continue
            candidates.append({
                'asset_id':asset.asset_id,'asset':asset.primary_path,'domain':str(domain),
                'model_info_inx':inx,'skeleton_smb':motion_smb,'valid_lods':valid,
                'lod_node_count':score,'model_info_context_state':str(cls.get('state') or 'UNKNOWN'),
                'config_count':int(cls.get('config_count') or 0),
            })
    state_rank={'AMBIGUOUS_MODEL_INFO_CONFIG':0,'SEMANTICALLY_EQUIVALENT':1,'SINGLE_CONFIG':2}
    candidates.sort(key=lambda r:(state_rank.get(r['model_info_context_state'],9),-len(r['valid_lods']),-r['lod_node_count'],r['asset'].casefold(),r['model_info_inx'].casefold()))
    out=[]; seen=set()
    for row in candidates:
        if row['asset_id'] in seen: continue
        out.append(row); seen.add(row['asset_id'])
        if len(out) >= int(limit): break
    return out



def filter_animation_pose_physical_representatives(rows: list[dict[str, Any]], resolver, *, limit: int = 2) -> list[dict[str, Any]]:
    """Return the first physically evaluable motion witnesses from *rows*.

    A resolver-less object is accepted only as an internal test seam; real CLI
    execution always supplies the physical resolver and therefore always runs
    the strict SMB hierarchy/layout preflight.
    """
    if int(limit) <= 0:
        return []
    if not hasattr(resolver, "resolve"):
        return [dict(r) for r in rows[: int(limit)]]
    root = pathlib.Path(__file__).resolve().parents[1]
    ev = load_smb_evaluator(root)
    out: list[dict[str, Any]] = []
    for row in rows:
        logical = _norm(row.get("skeleton_smb"))
        if not logical:
            continue
        try:
            physical = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            parsed = ev.parse_smb(physical)
            containers = [x for x in parsed.get("header_frames") or [] if int(x.get("end") or 0) > int(x.get("start") or 0)]
            key_count = sum(
                len(b.get(track) or [])
                for b in parsed.get("bones") or []
                for track in ("rot", "pos", "scale")
            )
            if not containers or key_count <= 0:
                continue
        except Exception:
            continue
        enriched = dict(row)
        enriched["physical_pose_preflight"] = "PASS"
        enriched["motion_container_count"] = len(containers)
        enriched["motion_key_count"] = int(key_count)
        out.append(enriched)
        if len(out) >= int(limit):
            break
    return out


def choose_animation_pose_physical_representatives(registry, resolver, domain: str, *, limit: int = 2) -> list[dict[str, Any]]:
    """Backfill a domain witness set until enough closed physical SMBs exist."""
    broad = choose_animation_pose_representatives(
        registry, domain, limit=max(200, len(getattr(registry, "assets", []) or []))
    )
    return filter_animation_pose_physical_representatives(broad, resolver, limit=limit)

def run_animation_pose_automated_devtest(
    settings, asset_registry, resolver, certifications, *,
    asset_path: str, model_info_inx: str, domain: str, fps: int = 30,
) -> dict[str, Any]:
    asset = asset_registry.resolve(asset_path)
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"animation pose devtest requires rigid Model0.62, got {asset.family}")
    if not asset.animation_binding_ready:
        raise RuntimeError("asset has no resolved animation binding")
    cfg = _config(asset, model_info_inx)
    lod = _choose_lod(asset, cfg)
    root = pathlib.Path(settings.project_root).resolve()
    work = _work(root, domain, asset.primary_path)
    if work.exists():
        shutil.rmtree(work)
    import_work = work / "01_import"; bake_work = work / "02_bake"; check_work = work / "03_pose_check"
    for p in (import_work, bake_work, check_work): p.mkdir(parents=True, exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    runner.structural(asset)
    overlay, texture_report = runner._texture_overlay(asset, import_work)
    preselected = runner._preflight_rigid_import(asset, lod, model_info=model_info_inx, require_unambiguous=True)
    src, pristine, actual_lod, selected_cfg = runner._prepare_rigid_blend(
        asset, lod, import_work, overlay, model_info=model_info_inx,
        require_unambiguous=True, preselected=preselected,
    )
    if actual_lod != lod:
        raise RuntimeError("animation pose devtest LOD drift")

    motion = resolve_asset_motion_context(asset, resolver, require_physical=True)
    selected_smb = _norm(selected_cfg.get("motion_smb") or asset.binding_skeleton_smb)
    motion_smb = _norm(motion.get("motion_smb"))
    if selected_smb.casefold() != motion_smb.casefold():
        raise RuntimeError(f"model-info skeleton and animation motion SMB differ: {selected_smb} != {motion_smb}")
    inx_path = pathlib.Path(motion["inx_path"]).resolve()
    smb_path = pathlib.Path(motion["smb_path"]).resolve()
    payload = build_bake_payload(root, inx_path, smb_path, selector="auto", load_actions="core", fps=int(fps))
    if not payload.get("actions"):
        raise RuntimeError("animation pose devtest payload has no actions")
    payload_path = bake_work / "motion_bake_payload.json"; write_payload(payload_path, payload)

    animated = bake_work / "animated.blend"; bake_report = bake_work / "bake_report.json"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "bake_actions.py"), "--",
        "--payload", str(payload_path), "--out", str(animated), "--report", str(bake_report),
    ], bake_work / "01_bake.log")
    baked = json.loads(bake_report.read_text(encoding="utf-8"))
    if baked.get("check") != "PASS":
        raise RuntimeError(f"Blender action bake failed: {baked}")

    pose_report = check_work / "pose_space.json"
    run_logged(settings.blender_command() + [
        "--background", str(animated), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "check_baked_animation_pose.py"), "--",
        "--payload", str(payload_path), "--report", str(pose_report),
    ], check_work / "01_pose_check.log")
    pose = json.loads(pose_report.read_text(encoding="utf-8"))
    if pose.get("status") != "PASS":
        raise RuntimeError(f"Blender pose-space gate failed: {pose.get('errors')}")

    result = {
        "format": FORMAT, "status": "PASS", "domain": domain,
        "asset": asset.primary_path, "model_info_inx": _norm(model_info_inx), "lod": lod,
        "motion_inx": motion.get("motion_inx"), "motion_smb": motion.get("motion_smb"),
        "inx_layout": payload.get("inx_layout"),
        "source_sha256": sha256_file(src), "animated_blend": str(animated),
        "automatic_actions_checked": int(pose.get("action_count") or 0),
        "checked_frames": int(pose.get("checked_frames") or 0),
        "checked_bone_frames": int(pose.get("checked_bone_frames") or 0),
        "max_abs_matrix_error": pose.get("max_abs_matrix_error"),
        "pose_report": str(pose_report), "bake_report": str(bake_report),
        "texture_ready": bool(texture_report.get("ready", True)),
        "automatic_pose_space_pass": True,
        "track_key_counts": dict(payload.get("track_key_counts") or {}),
        "visual_runtime_review_required": True,
        "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
        "workdir": str(work),
    }
    rp = work / "result.json"; result["report"] = str(rp)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_animation_pose_automated_devtest_batch(
    settings, asset_registry, resolver, certifications, rows: list[dict[str, Any]], *, fps: int = 30,
) -> dict[str, Any]:
    results=[]; failures=[]
    for row in rows:
        try:
            results.append(run_animation_pose_automated_devtest(
                settings, asset_registry, resolver, certifications,
                asset_path=row["asset"], model_info_inx=row["model_info_inx"],
                domain=row["domain"], fps=fps,
            ))
        except Exception as exc:
            failure={
                "asset": row.get("asset"), "domain": row.get("domain"),
                "model_info_inx": row.get("model_info_inx"),
                "error": f"{type(exc).__name__}: {exc}",
            }
            try:
                work=_work(pathlib.Path(settings.project_root).resolve(),str(row.get("domain") or ""),str(row.get("asset") or ""))
                bake_path=work / "02_bake" / "bake_report.json"
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
                pose_path=work / "03_pose_check" / "pose_space.json"
                if pose_path.is_file():
                    pose=json.loads(pose_path.read_text(encoding="utf-8"))
                    failure["pose_diagnostic"]={
                        "status":pose.get("status"),
                        "errors":pose.get("errors"),
                        "pose_mismatch_diagnostic":pose.get("pose_mismatch_diagnostic"),
                        "max_abs_matrix_error":pose.get("max_abs_matrix_error"),
                        "max_expected_basis_trs_reconstruction_error":pose.get("max_expected_basis_trs_reconstruction_error"),
                        "non_trs_basis_mismatch_count":pose.get("non_trs_basis_mismatch_count"),
                        "actions":pose.get("actions"),
                        "report":str(pose_path),
                    }
            except Exception:
                pass
            failures.append(failure)
    result = {
        "format": BATCH_FORMAT,
        "status": "PASS" if results and not failures else "FAIL",
        "requested": len(rows), "passed_assets": [x.get("asset") for x in results],
        "failed_assets": failures, "results": results,
        "automatic_only": True, "visual_runtime_review_required": True,
        "runtime_authorized": False, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
    out = pathlib.Path(settings.project_root).resolve() / "pt_build" / "devtest" / "animation_pose_auto" / "batch_result.json"
    out.parent.mkdir(parents=True, exist_ok=True); result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
