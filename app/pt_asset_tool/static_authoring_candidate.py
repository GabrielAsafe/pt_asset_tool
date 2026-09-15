from __future__ import annotations

import pathlib
from typing import Any

from .authoring import authoring_plan, verify_workspace_manifest
from .blender_workspace import blender_edit_root, asset_workspace_name
from .static_roundtrip import _parse as parse_model062_bytes

FORMAT = "PT_STATIC_SAVED_BLENDER_CANDIDATE_PLAN_V1"
VERIFY_FORMAT = "PT_STATIC_SAVED_BLENDER_CANDIDATE_VERIFY_V1"


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def plan_static_saved_blender_candidate(project_root, resolver, asset, *, object_name: str | None = None, output: pathlib.Path | str | None = None) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    if asset.family != "SMD_MODEL_062_STATIC":
        raise RuntimeError(f"static saved-Blender candidate requires SMD_MODEL_062_STATIC, got {asset.family}")
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    plan = authoring_plan(asset, source)
    eligible = list(((plan.get("channels") or {}).get("geometry") or {}).get("eligible_objects") or [])
    if object_name:
        hits = [x for x in eligible if x.casefold() == str(object_name).casefold()]
        if not hits:
            raise RuntimeError(f"object is not eligible for static candidate writer: {object_name}; eligible={eligible}")
        selected = hits[0]
    elif len(eligible) == 1:
        selected = eligible[0]
    elif not eligible:
        raise RuntimeError("no object satisfies the static saved-Blender candidate contract")
    else:
        raise RuntimeError(f"multiple eligible objects; choose --object explicitly: {eligible}")

    workspace = blender_edit_root(project_root, "generic_import", asset.primary_path)
    blend = workspace / "imported.blend"
    manifest = workspace / "authoring_manifest.json"
    blockers: list[str] = []
    if not blend.is_file():
        blockers.append("GENERIC_IMPORT_WORKSPACE_MISSING")
    if not manifest.is_file():
        manifest_verify = {
            "status": "FAIL", "errors": ["AUTHORING_MANIFEST_MISSING"],
            "build_authorized": False, "client_write_authorized": False,
        }
        blockers.append("AUTHORING_MANIFEST_MISSING")
    else:
        manifest_verify = verify_workspace_manifest(manifest)
        if manifest_verify.get("status") != "PASS":
            blockers.append("AUTHORING_WORKSPACE_PROVENANCE_FAILED")

    if output is None:
        output_path = (
            project_root / "pt_build" / "candidate_build" /
            asset_workspace_name(asset.primary_path) /
            pathlib.PurePosixPath(asset.primary_path).name
        ).resolve()
    else:
        raw = pathlib.Path(output).expanduser()
        output_path = (project_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if not _inside(project_root / "pt_build", output_path):
        blockers.append("OUTPUT_OUTSIDE_PT_BUILD")

    return {
        "format": FORMAT,
        "status": "READY" if not blockers else "BLOCKED",
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "source": str(source),
        "source_sha256": ((plan.get("source_analysis") or {}).get("sha256")),
        "workspace": str(workspace),
        "blend": str(blend),
        "authoring_manifest": str(manifest),
        "manifest_verification": manifest_verify,
        "object": selected,
        "eligible_objects": eligible,
        "output": str(output_path),
        "blockers": blockers,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def validate_static_candidate_output(source: pathlib.Path, output: pathlib.Path, target_object: str) -> dict[str, Any]:
    source = pathlib.Path(source).resolve()
    output = pathlib.Path(output).resolve()
    sb = source.read_bytes()
    ob = output.read_bytes()
    s = parse_model062_bytes(sb)
    o = parse_model062_bytes(ob)
    errors: list[str] = []
    if s["n"] != o["n"]:
        errors.append("OBJECT_COUNT")
    if s["mat_count"] != o["mat_count"]:
        errors.append("MATERIAL_COUNT")
    if s["mat_region"] != o["mat_region"]:
        errors.append("MATERIAL_REGION_BYTES")
    if set(s["objects"]) != set(o["objects"]):
        errors.append("OBJECT_NAMES")
    if target_object not in s["objects"] or target_object not in o["objects"]:
        errors.append("TARGET_MISSING")

    non_target_changed = []
    for name in set(s["objects"]) & set(o["objects"]):
        if name == target_object:
            continue
        if s["objects"][name]["block"] != o["objects"][name]["block"]:
            non_target_changed.append(name)
    if non_target_changed:
        errors.append("NON_TARGET_BLOCK_CHANGED")

    target = None
    if target_object in o["objects"]:
        src_obj = s["objects"][target_object]
        out_obj = o["objects"][target_object]
        if src_obj["phys"] or out_obj["phys"]:
            errors.append("PHYSIQUE_PRESENT")
        if any([src_obj["nr"], src_obj["np"], src_obj["ns"], out_obj["nr"], out_obj["np"], out_obj["ns"]]):
            errors.append("OBJECT_LOCAL_ANIMATION_PRESENT")
        layer_depths = [len(f.get("uv_layers") or []) for f in out_obj["faces"]]
        if not layer_depths or min(layer_depths) != 1 or max(layer_depths) != 1:
            errors.append("OUTPUT_TEXLINK_NOT_SINGLE_LAYER")
        if out_obj["nv"] < 3 or out_obj["nf"] < 1:
            errors.append("OUTPUT_GEOMETRY_EMPTY")
        target = {
            "source_counts": [src_obj["nv"], src_obj["nf"], src_obj["nt"]],
            "output_counts": [out_obj["nv"], out_obj["nf"], out_obj["nt"]],
            "topology_changed": [src_obj["nv"], src_obj["nf"]] != [out_obj["nv"], out_obj["nf"]],
            "target_block_byte_identical": src_obj["block"] == out_obj["block"],
            "texlink_layer_depths": sorted(set(layer_depths)),
        }

    return {
        "format": VERIFY_FORMAT,
        "status": "PASS" if not errors else "FAIL",
        "source": str(source),
        "output": str(output),
        "object": target_object,
        "target": target,
        "non_target_changed": non_target_changed,
        "errors": errors,
        "edit_observed": bool(target is not None and not target.get("target_block_byte_identical", True)),
        "candidate_only": True,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def build_static_candidate_blender_command(settings, candidate: dict[str, Any], *, report: pathlib.Path) -> list[str]:
    if candidate.get("status") != "READY":
        raise RuntimeError(f"candidate plan is not ready: {candidate.get('blockers')}")
    project_root = pathlib.Path(settings.project_root).resolve()
    writer = project_root / "pt_blender_to_smd_static_v1.py"
    if not writer.is_file():
        raise FileNotFoundError(writer)
    return settings.blender_command() + [
        "--background", str(pathlib.Path(candidate["blend"]).resolve()),
        "--python-exit-code", "1",
        "--python", str(writer), "--",
        "--smd", str(pathlib.Path(candidate["source"]).resolve()),
        "--object", str(candidate["object"]),
        "--out", str(pathlib.Path(candidate["output"]).resolve()),
        "--report", str(pathlib.Path(report).resolve()),
        "--expected-source-sha256", str(candidate["source_sha256"]),
    ]
