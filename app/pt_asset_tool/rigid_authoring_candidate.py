from __future__ import annotations

import pathlib
from typing import Any

from .authoring import authoring_plan, verify_selected_context_for_asset, verify_workspace_manifest
from .blender_workspace import asset_workspace_name, blender_edit_root
from .smb_writer import _layout_for_bones
from .static_roundtrip import _parse as parse_model062_bytes

FORMAT = "PT_RIGID_SAVED_BLENDER_CANDIDATE_PLAN_V1"
VERIFY_FORMAT = "PT_RIGID_SAVED_BLENDER_CANDIDATE_VERIFY_V1"


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def _eligible_objects(plan: dict[str, Any]) -> list[str]:
    rows = ((plan.get("source_analysis") or {}).get("objects") or [])
    return [
        str(row["name"]) for row in rows
        if bool(row.get("physique"))
        and not bool(row.get("has_object_local_animation"))
        and int(row.get("faces") or 0) >= 1
        and int(row.get("vertices") or 0) >= 3
        and int(row.get("texlink_min_layers") or 0) == 1
        and int(row.get("texlink_max_layers") or 0) == 1
    ]


def _restrict_to_selected_lod(eligible: list[str], selected_context: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    """Restrict candidate targets to the exact LOD nodes saved at import time.

    A Model0.62 container may carry meshes for several LODs/variants.  Physical
    writer eligibility alone is therefore not enough: a candidate edit must also
    belong to the authoring context that produced the saved Blender workspace.
    """
    context = dict(selected_context or {})
    selected_nodes = [str(x) for x in (context.get("selected_lod_nodes") or []) if str(x)]
    if not selected_nodes:
        return list(eligible), [], []

    by_key: dict[str, list[str]] = {}
    for name in eligible:
        by_key.setdefault(name.casefold(), []).append(name)

    scoped: list[str] = []
    ineligible: list[str] = []
    for requested in selected_nodes:
        hits = by_key.get(requested.casefold(), [])
        if not hits:
            ineligible.append(requested)
            continue
        for hit in hits:
            if hit not in scoped:
                scoped.append(hit)
    return scoped, selected_nodes, ineligible


def _restrict_to_all_lods(eligible: list[str], selected_context: dict[str, Any] | None) -> tuple[list[str], dict[str, str]]:
    """Return writer-eligible nodes referenced by any saved HIGH/DEFAULT/LOW group."""
    context = dict(selected_context or {})
    groups = dict(context.get("lod_groups") or {})
    by_key = {name.casefold(): name for name in eligible}
    out: list[str] = []
    lod_by_object: dict[str, str] = {}
    for lod in ("high", "default", "low"):
        for raw in groups.get(lod) or []:
            actual = by_key.get(str(raw).casefold())
            if actual is None:
                continue
            if actual not in out:
                out.append(actual)
            lod_by_object.setdefault(actual, lod)
    if not out:
        out = list(eligible)
    return out, lod_by_object


def inspect_rigid_candidate_scope(plan: dict[str, Any], selected_context: dict[str, Any] | None) -> dict[str, Any]:
    source_eligible = _eligible_objects(plan)
    eligible, selected_lod_nodes, selected_lod_ineligible = _restrict_to_selected_lod(source_eligible, selected_context)
    return {
        "format": "PT_RIGID_SAVED_BLENDER_CANDIDATE_SCOPE_V1",
        "selected_lod": str((selected_context or {}).get("lod") or ""),
        "selected_lod_nodes": selected_lod_nodes,
        "eligible_objects": eligible,
        "source_contract_eligible_objects": source_eligible,
        "selected_lod_ineligible_objects": selected_lod_ineligible,
        "scope_complete": not bool(selected_lod_ineligible),
        "selection_required": len(eligible) > 1,
        "client_modified": False,
    }


def plan_rigid_saved_blender_candidate(project_root, resolver, asset, *, object_name: str | None = None, output: pathlib.Path | str | None = None, lod_scope: str = "selected") -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"rigid saved-Blender candidate requires SMD_MODEL_062_RIGID_PHYSIQUE, got {asset.family}")
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    plan = authoring_plan(asset, source)
    source_eligible = _eligible_objects(plan)

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

    selected_context = (manifest_verify or {}).get("selected_context")
    context_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver)
    if context_verify.get("status") != "PASS":
        blockers.append("RIGID_SELECTED_CONTEXT_MISMATCH")
    if not asset.rigid_binding_ready and str((selected_context or {}).get("format") or "") != "PT_ASSET_STANDALONE_RIGID_CONTEXT_V1":
        blockers.append("RIGID_SKELETON_BINDING_NOT_READY")

    scope = inspect_rigid_candidate_scope(plan, selected_context)
    if lod_scope not in {"selected", "all"}:
        raise ValueError(f"invalid rigid candidate lod_scope: {lod_scope}")
    if lod_scope == "all":
        eligible, object_lods = _restrict_to_all_lods(source_eligible, selected_context)
    else:
        eligible = list(scope["eligible_objects"])
        object_lods = {name: str((selected_context or {}).get("lod") or "") for name in eligible}
    selected_lod_nodes = list(scope["selected_lod_nodes"])
    selected_lod_ineligible = list(scope["selected_lod_ineligible_objects"])
    if object_name:
        hits = [x for x in eligible if x.casefold() == str(object_name).casefold()]
        if not hits:
            raise RuntimeError(
                f"object is not eligible within the saved rigid LOD context: {object_name}; "
                f"selected_lod_nodes={selected_lod_nodes}; eligible={eligible}"
            )
        selected = hits[0]
    elif len(eligible) == 1:
        selected = eligible[0]
    elif not eligible:
        raise RuntimeError(
            "no object satisfies the rigid saved-Blender candidate contract within the saved LOD context"
        )
    else:
        raise RuntimeError(
            f"multiple eligible objects in saved LOD context; choose --object explicitly: {eligible}"
        )

    skeleton_row = dict((selected_context or {}).get("skeleton_smb") or {})
    skeleton_path_value = str(skeleton_row.get("path") or "")
    skeleton_logical = str(skeleton_row.get("logical") or asset.binding_skeleton_smb or "").replace("\\", "/")
    if skeleton_path_value:
        skeleton = pathlib.Path(skeleton_path_value).resolve()
    elif skeleton_logical:
        skeleton = pathlib.Path(resolver.resolve(skeleton_logical, required=True)).resolve()
    else:
        skeleton = pathlib.Path("")
        blockers.append("RIGID_SKELETON_CONTEXT_MISSING")

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
        "skeleton": str(skeleton),
        "skeleton_logical": skeleton_logical,
        "selected_context": selected_context,
        "selected_context_verification": context_verify,
        "workspace": str(workspace),
        "blend": str(blend),
        "authoring_manifest": str(manifest),
        "manifest_verification": manifest_verify,
        "object": selected,
        "lod_scope": lod_scope,
        "eligible_objects": eligible,
        "object_lods": object_lods,
        "source_contract_eligible_objects": source_eligible,
        "selected_lod_nodes": selected_lod_nodes,
        "selected_lod_ineligible_objects": selected_lod_ineligible,
        "output": str(output_path),
        "blockers": blockers,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def build_rigid_candidate_blender_command(settings, candidate: dict[str, Any], *, report: pathlib.Path) -> list[str]:
    if candidate.get("status") != "READY":
        raise RuntimeError(f"candidate plan is not ready: {candidate.get('blockers')}")
    project_root = pathlib.Path(settings.project_root).resolve()
    writer = project_root / "pt_blender_to_smd_free_mesh_v3.py"
    if not writer.is_file():
        raise FileNotFoundError(writer)
    cmd = settings.blender_command() + [
        "--background", str(pathlib.Path(candidate["blend"]).resolve()),
        "--python-exit-code", "1",
        "--python", str(writer), "--",
        "--smd", str(pathlib.Path(candidate["source"]).resolve()),
        "--skeleton", str(pathlib.Path(candidate["skeleton"]).resolve()),
        "--object", str(candidate["object"]),
    ]
    if candidate.get("object_index") is not None:
        cmd += ["--object-index", str(int(candidate["object_index"]))]
    cmd += [
        "--out", str(pathlib.Path(candidate["output"]).resolve()),
        "--report", str(pathlib.Path(report).resolve()),
        "--expected-source-sha256", str(candidate["source_sha256"]),
    ]
    physique_policy = str(candidate.get("physique_policy") or "auto")
    if physique_policy not in {"auto", "strict", "source"}:
        raise ValueError(f"invalid physique_policy: {physique_policy}")
    # Always pass the policy explicitly so build logs are auditable and a caller
    # cannot accidentally inherit a changed writer default.
    cmd += ["--physique-policy", physique_policy]
    return cmd


def _physique_names(obj: dict[str, Any]) -> list[str]:
    block = obj["block"]
    # Offset relative to the object block: smOBJ3D + vertices + faces + texlinks
    # + object-local arrays + PrevRot matrices. Physique slots are 32-byte C strings.
    off = 2236 + obj["nv"] * 24 + obj["nf"] * 36 + obj["nt"] * 32 + obj["nr"] * 20 + obj["np"] * 16 + obj["ns"] * 16 + obj["nr"] * 64
    names = []
    for i in range(obj["nv"]):
        raw = block[off + i*32 : off + (i+1)*32]
        names.append(raw.split(b"\0",1)[0].decode("latin-1", "replace"))
    return names


def _rigid_semantic_payload(obj: dict[str, Any]) -> dict[str, Any]:
    """Return the game-relevant rigid mesh payload used to detect real artist edits.

    Object block bytes are intentionally *not* used as the edit witness: the
    Blender writer may normalize opaque/pointer fields while preserving the
    mesh exactly.  Deployment must only call a model MODIFIED when geometry,
    UV/material face data, topology, or rigid bone assignments changed.
    """
    return {
        "vertices": [tuple(int(v) for v in row) for row in (obj.get("vertices") or [])],
        "faces": [
            {
                "verts": tuple(int(v) for v in (face.get("verts") or ())),
                "material": int(face.get("material") or 0),
                "uv_layers": tuple(
                    tuple(tuple(float(c) for c in uv) for uv in layer)
                    for layer in (face.get("uv_layers") or [])
                ),
            }
            for face in (obj.get("faces") or [])
        ],
        "physique_bones": tuple(_physique_names(obj)) if obj.get("phys") else (),
    }


def compare_rigid_candidate_semantics(baseline: pathlib.Path, edited: pathlib.Path, target_object: str) -> dict[str, Any]:
    """Compare two writer outputs for one object, independent of source import normalization.

    Workspace deploy uses this to compare a pristine imported .blend with the saved
    edited .blend after both have gone through the exact same writer/weight policy.
    That makes source->Blender vertex splitting and deterministic weight repair cancel
    out of the edit witness; only an artist-visible mesh/UV/material/Physique delta
    between the two workspace states is considered an edit.
    """
    baseline = pathlib.Path(baseline).resolve()
    edited = pathlib.Path(edited).resolve()
    b = parse_model062_bytes(baseline.read_bytes())
    e = parse_model062_bytes(edited.read_bytes())
    errors: list[str] = []
    if target_object not in b["objects"]:
        errors.append("BASELINE_TARGET_MISSING")
    if target_object not in e["objects"]:
        errors.append("EDITED_TARGET_MISSING")
    if errors:
        return {
            "format": "PT_RIGID_WORKSPACE_SEMANTIC_COMPARE_V1",
            "status": "FAIL",
            "object": target_object,
            "errors": errors,
            "edit_observed": False,
        }

    bo = b["objects"][target_object]
    eo = e["objects"][target_object]
    bp = _rigid_semantic_payload(bo)
    ep = _rigid_semantic_payload(eo)
    return {
        "format": "PT_RIGID_WORKSPACE_SEMANTIC_COMPARE_V1",
        "status": "PASS",
        "object": target_object,
        "baseline": str(baseline),
        "edited": str(edited),
        "baseline_counts": [bo["nv"], bo["nf"], bo["nt"]],
        "edited_counts": [eo["nv"], eo["nf"], eo["nt"]],
        "topology_changed": [bo["nv"], bo["nf"]] != [eo["nv"], eo["nf"]],
        "vertex_payload_changed": bp["vertices"] != ep["vertices"],
        "face_uv_material_changed": bp["faces"] != ep["faces"],
        "physique_assignment_changed": bp["physique_bones"] != ep["physique_bones"],
        "edit_observed": bp != ep,
        "errors": [],
    }


def validate_rigid_candidate_output(project_root: pathlib.Path, source: pathlib.Path, output: pathlib.Path, skeleton: pathlib.Path, target_object: str) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    source = pathlib.Path(source).resolve()
    output = pathlib.Path(output).resolve()
    skeleton = pathlib.Path(skeleton).resolve()
    sb = source.read_bytes(); ob = output.read_bytes()
    s = parse_model062_bytes(sb); o = parse_model062_bytes(ob)
    errors: list[str] = []
    if s["n"] != o["n"]: errors.append("OBJECT_COUNT")
    if s["mat_count"] != o["mat_count"]: errors.append("MATERIAL_COUNT")
    if s["mat_region"] != o["mat_region"]: errors.append("MATERIAL_REGION_BYTES")
    if set(s["objects"]) != set(o["objects"]): errors.append("OBJECT_NAMES")
    if target_object not in s["objects"] or target_object not in o["objects"]: errors.append("TARGET_MISSING")

    non_target_changed = []
    for name in set(s["objects"]) & set(o["objects"]):
        if name == target_object: continue
        if s["objects"][name]["block"] != o["objects"][name]["block"]:
            non_target_changed.append(name)
    if non_target_changed: errors.append("NON_TARGET_BLOCK_CHANGED")

    target = None
    bone_names: list[str] = []
    unknown_bones: list[str] = []
    if target_object in o["objects"]:
        src_obj = s["objects"][target_object]; out_obj = o["objects"][target_object]
        if not src_obj["phys"] or not out_obj["phys"]: errors.append("PHYSIQUE_MISSING")
        if any([src_obj["nr"],src_obj["np"],src_obj["ns"],out_obj["nr"],out_obj["np"],out_obj["ns"]]):
            errors.append("OBJECT_LOCAL_ANIMATION_PRESENT")
        layer_depths = [len(f.get("uv_layers") or []) for f in out_obj["faces"]]
        if not layer_depths or min(layer_depths) != 1 or max(layer_depths) != 1:
            errors.append("OUTPUT_TEXLINK_NOT_SINGLE_LAYER")
        bone_names = _physique_names(out_obj)
        if len(bone_names) != out_obj["nv"] or any(not x for x in bone_names):
            errors.append("OUTPUT_PHYSIQUE_EMPTY_BONE")
        try:
            _evaluator, parsed_skeleton, _infos, _data = _layout_for_bones(project_root, skeleton)
            skeleton_names = {str(b["name"]).casefold() for b in parsed_skeleton["bones"]}
            unknown_bones = sorted({x for x in bone_names if x.casefold() not in skeleton_names}, key=str.casefold)
            if unknown_bones: errors.append("OUTPUT_PHYSIQUE_BONE_NOT_IN_SKELETON")
        except Exception as exc:
            errors.append(f"SKELETON_PARSE:{type(exc).__name__}")
        source_semantic = _rigid_semantic_payload(src_obj)
        output_semantic = _rigid_semantic_payload(out_obj)
        target = {
            "source_counts": [src_obj["nv"],src_obj["nf"],src_obj["nt"]],
            "output_counts": [out_obj["nv"],out_obj["nf"],out_obj["nt"]],
            "topology_changed": [src_obj["nv"],src_obj["nf"]] != [out_obj["nv"],out_obj["nf"]],
            "target_block_byte_identical": src_obj["block"] == out_obj["block"],
            "semantic_edit_observed": source_semantic != output_semantic,
            "vertex_payload_changed": source_semantic["vertices"] != output_semantic["vertices"],
            "face_uv_material_changed": source_semantic["faces"] != output_semantic["faces"],
            "physique_assignment_changed": source_semantic["physique_bones"] != output_semantic["physique_bones"],
            "texlink_layer_depths": sorted(set(layer_depths)),
            "unique_physique_bones": sorted(set(bone_names), key=str.casefold),
        }

    return {
        "format": VERIFY_FORMAT,
        "status": "PASS" if not errors else "FAIL",
        "source": str(source), "output": str(output), "skeleton": str(skeleton),
        "object": target_object, "target": target,
        "unknown_physique_bones": unknown_bones,
        "non_target_changed": non_target_changed, "errors": errors,
        "byte_edit_observed": bool(target is not None and not target.get("target_block_byte_identical", True)),
        "edit_observed": bool(target is not None and target.get("semantic_edit_observed")),
        "candidate_only": True, "production_authorized": False,
        "client_write_authorized": False, "client_modified": False,
    }
