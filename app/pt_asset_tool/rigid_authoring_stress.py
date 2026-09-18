from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from .authoring import authoring_plan, verify_selected_context_for_asset, verify_workspace_manifest
from .blender_workspace import asset_workspace_name, blender_edit_root
from .rigid_authoring_candidate import _eligible_objects, _physique_names, _rigid_semantic_payload
from .smb_writer import _layout_for_bones
from .static_roundtrip import _parse as parse_model062_bytes

FORMAT = "PT_RIGID_PROFILE_STRESS_CANDIDATE_PLAN_V1"
VERIFY_FORMAT = "PT_RIGID_PROFILE_STRESS_CANDIDATE_VERIFY_V1"


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def _profile_nodes(selected_context: dict[str, Any] | None) -> tuple[list[str], dict[str, str]]:
    context = dict(selected_context or {})
    selected_lod = str(context.get("lod") or "")
    if str(context.get("lod_selection_mode") or "MODEL_GROUP_KEYS") == "SINGLE_TIER_FULL_CONTAINER":
        out = [str(x) for x in (context.get("selected_lod_nodes") or []) if str(x)]
        return out, {name.casefold(): selected_lod for name in out}
    groups = dict(context.get("lod_groups") or {})
    out: list[str] = []
    lod_by_object: dict[str, str] = {}
    for lod in ("high", "default", "low"):
        for raw in groups.get(lod) or []:
            name = str(raw)
            if not name:
                continue
            key = name.casefold()
            if key not in lod_by_object:
                out.append(name)
                lod_by_object[key] = lod
    return out, lod_by_object


def inspect_rigid_profile_stress_scope(plan: dict[str, Any], selected_context: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(selected_context or {})
    basis = dict(context.get("selection_basis") or {})
    requested, lod_by_object = _profile_nodes(context)
    physical = _eligible_objects(plan)
    physical_by_key = {x.casefold(): x for x in physical}
    eligible: list[str] = []
    missing: list[str] = []
    object_lods: dict[str, str] = {}
    for requested_name in requested:
        actual = physical_by_key.get(requested_name.casefold())
        if actual is None:
            missing.append(requested_name)
            continue
        eligible.append(actual)
        object_lods[actual] = lod_by_object[requested_name.casefold()]
    canonical_profile = str(basis.get("kind") or "") == "CANONICAL_PROFILE" and bool(basis.get("profile_id"))
    return {
        "format": "PT_RIGID_PROFILE_STRESS_SCOPE_V1",
        "profile_id": basis.get("profile_id"),
        "profile_version": basis.get("profile_version"),
        "canonical_profile_context": canonical_profile,
        "requested_objects": requested,
        "eligible_objects": eligible,
        "object_lods": object_lods,
        "missing_or_ineligible_objects": missing,
        "source_contract_eligible_objects": physical,
        "scope_complete": bool(requested) and not missing and len(eligible) == len(requested),
        "all_lods_present": all(any(v == lod for v in object_lods.values()) for lod in ("high", "default", "low")),
        "client_modified": False,
    }


def plan_rigid_profile_stress_candidate(project_root, resolver, asset, *, output: pathlib.Path | str | None = None) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    if asset.family != "SMD_MODEL_062_RIGID_PHYSIQUE":
        raise RuntimeError(f"rigid profile stress requires SMD_MODEL_062_RIGID_PHYSIQUE, got {asset.family}")
    if not asset.rigid_binding_ready:
        raise RuntimeError(f"rigid profile stress requires resolved binding, got {asset.binding_mode}/{asset.binding_source}")
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    base_plan = authoring_plan(asset, source)
    workspace = blender_edit_root(project_root, "generic_import", asset.primary_path)
    blend = workspace / "imported.blend"
    manifest = workspace / "authoring_manifest.json"
    blockers: list[str] = []
    if not blend.is_file():
        blockers.append("GENERIC_IMPORT_WORKSPACE_MISSING")
    if not manifest.is_file():
        manifest_verify = {"status": "FAIL", "errors": ["AUTHORING_MANIFEST_MISSING"]}
        blockers.append("AUTHORING_MANIFEST_MISSING")
    else:
        manifest_verify = verify_workspace_manifest(manifest)
        if manifest_verify.get("status") != "PASS":
            blockers.append("AUTHORING_WORKSPACE_PROVENANCE_FAILED")
    selected_context = dict((manifest_verify or {}).get("selected_context") or {})
    context_verify = verify_selected_context_for_asset(selected_context, asset, resolver=resolver)
    if context_verify.get("status") != "PASS":
        blockers.append("RIGID_SELECTED_CONTEXT_MISMATCH")
    scope = inspect_rigid_profile_stress_scope(base_plan, selected_context)
    if not scope.get("canonical_profile_context"):
        blockers.append("STRESS_REQUIRES_CANONICAL_PROFILE_CONTEXT")
    if not scope.get("scope_complete"):
        blockers.append("PROFILE_STRESS_SCOPE_INCOMPLETE")
    if not scope.get("all_lods_present"):
        blockers.append("PROFILE_STRESS_REQUIRES_HIGH_DEFAULT_LOW")

    skeleton_row = dict(selected_context.get("skeleton_smb") or {})
    skeleton = pathlib.Path(str(skeleton_row.get("path") or resolver.resolve(asset.binding_skeleton_smb, required=True))).resolve()
    skeleton_logical = str(skeleton_row.get("logical") or asset.binding_skeleton_smb or "").replace("\\", "/")
    if output is None:
        output_path = (
            project_root / "pt_build" / "candidate_stress" /
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
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "skeleton": str(skeleton),
        "skeleton_logical": skeleton_logical,
        "selected_context": selected_context,
        "selected_context_verification": context_verify,
        "workspace": str(workspace),
        "blend": str(blend),
        "authoring_manifest": str(manifest),
        "manifest_verification": manifest_verify,
        "objects": list(scope.get("eligible_objects") or []),
        "object_lods": dict(scope.get("object_lods") or {}),
        "stress_scope": scope,
        "output": str(output_path),
        "blockers": blockers,
        "require_every_target_edited": True,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def _validate_target(project_root: pathlib.Path, s_obj: dict[str, Any], o_obj: dict[str, Any], skeleton: pathlib.Path) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    if not s_obj["phys"] or not o_obj["phys"]:
        errors.append("PHYSIQUE_MISSING")
    if any([s_obj["nr"], s_obj["np"], s_obj["ns"], o_obj["nr"], o_obj["np"], o_obj["ns"]]):
        errors.append("OBJECT_LOCAL_ANIMATION_PRESENT")
    layer_depths = [len(f.get("uv_layers") or []) for f in o_obj["faces"]]
    if not layer_depths or min(layer_depths) != 1 or max(layer_depths) != 1:
        errors.append("OUTPUT_TEXLINK_NOT_SINGLE_LAYER")
    bones = _physique_names(o_obj)
    if len(bones) != o_obj["nv"] or any(not x for x in bones):
        errors.append("OUTPUT_PHYSIQUE_EMPTY_BONE")
    unknown: list[str] = []
    try:
        _evaluator, parsed_skeleton, _infos, _data = _layout_for_bones(project_root, skeleton)
        skeleton_names = {str(b["name"]).casefold() for b in parsed_skeleton["bones"]}
        unknown = sorted({x for x in bones if x.casefold() not in skeleton_names}, key=str.casefold)
        if unknown:
            errors.append("OUTPUT_PHYSIQUE_BONE_NOT_IN_SKELETON")
    except Exception as exc:
        errors.append(f"SKELETON_PARSE:{type(exc).__name__}")
    source_semantic = _rigid_semantic_payload(s_obj)
    output_semantic = _rigid_semantic_payload(o_obj)
    target = {
        "source_counts": [s_obj["nv"], s_obj["nf"], s_obj["nt"]],
        "output_counts": [o_obj["nv"], o_obj["nf"], o_obj["nt"]],
        "topology_changed": [s_obj["nv"], s_obj["nf"]] != [o_obj["nv"], o_obj["nf"]],
        "target_block_byte_identical": s_obj["block"] == o_obj["block"],
        "semantic_edit_observed": source_semantic != output_semantic,
        "vertex_payload_changed": source_semantic["vertices"] != output_semantic["vertices"],
        "face_uv_material_changed": source_semantic["faces"] != output_semantic["faces"],
        "physique_assignment_changed": source_semantic["physique_bones"] != output_semantic["physique_bones"],
        "texlink_layer_depths": sorted(set(layer_depths)),
        "unique_physique_bones": sorted(set(bones), key=str.casefold),
    }
    return target, unknown, errors


def validate_rigid_profile_stress_output(project_root: pathlib.Path, source: pathlib.Path, output: pathlib.Path, skeleton: pathlib.Path, target_objects: list[Any]) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    source = pathlib.Path(source).resolve()
    output = pathlib.Path(output).resolve()
    skeleton = pathlib.Path(skeleton).resolve()
    s = parse_model062_bytes(source.read_bytes())
    o = parse_model062_bytes(output.read_bytes())
    s_list = list(s.get("object_list") or [])
    o_list = list(o.get("object_list") or [])
    errors: list[str] = []
    if s["n"] != o["n"]:
        errors.append("OBJECT_COUNT")
    if s["mat_count"] != o["mat_count"]:
        errors.append("MATERIAL_COUNT")
    if s["mat_region"] != o["mat_region"]:
        errors.append("MATERIAL_REGION_BYTES")
    if [(int(x["index"]), str(x["name"])) for x in s_list] != [(int(x["index"]), str(x["name"])) for x in o_list]:
        errors.append("OBJECT_TABLE_IDENTITY")

    refs: list[dict[str, Any]] = []
    for raw in target_objects:
        if isinstance(raw, dict):
            refs.append({"name": str(raw.get("name") or ""), "index": raw.get("index")})
        else:
            refs.append({"name": str(raw), "index": None})

    def resolve_ref(rows: list[dict[str, Any]], ref: dict[str, Any], label: str) -> dict[str, Any] | None:
        name = str(ref.get("name") or "")
        idx = ref.get("index")
        if idx is not None:
            hits = [x for x in rows if int(x["index"]) == int(idx)]
            if len(hits) != 1 or str(hits[0]["name"]).casefold() != name.casefold():
                errors.append(f"TARGET_IDENTITY_MISMATCH:{label}:{name}#{idx}")
                return None
            return hits[0]
        hits = [x for x in rows if str(x["name"]).casefold() == name.casefold()]
        if len(hits) != 1:
            errors.append(f"TARGET_AMBIGUOUS:{label}:{name}:matches={len(hits)}")
            return None
        return hits[0]

    resolved: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    target_indices: set[int] = set()
    for ref in refs:
        sx = resolve_ref(s_list, ref, "source")
        ox = resolve_ref(o_list, ref, "output")
        if sx is None or ox is None:
            continue
        if int(sx["index"]) != int(ox["index"]):
            errors.append(f"TARGET_INDEX_DRIFT:{ref}")
            continue
        target_indices.add(int(sx["index"]))
        resolved.append((ref, sx, ox))

    non_target_changed: list[str] = []
    by_output_index = {int(x["index"]): x for x in o_list}
    for sx in s_list:
        idx = int(sx["index"])
        if idx in target_indices:
            continue
        ox = by_output_index.get(idx)
        if ox is None or sx["block"] != ox["block"]:
            non_target_changed.append(f"{sx['name']}#idx{idx}")
    if non_target_changed:
        errors.append("NON_TARGET_BLOCK_CHANGED")

    targets: dict[str, Any] = {}
    edit_observed_by_object: dict[str, bool] = {}
    unknown_by_object: dict[str, list[str]] = {}
    target_errors: dict[str, list[str]] = {}
    for ref, sx, ox in resolved:
        idx = int(sx["index"])
        key = f"{sx['name']}#idx{idx}"
        target, unknown, terr = _validate_target(project_root, sx, ox, skeleton)
        target["object_index"] = idx
        target["node_name"] = str(sx["name"])
        targets[key] = target
        edit_observed_by_object[key] = bool(target.get("semantic_edit_observed"))
        unknown_by_object[key] = unknown
        if terr:
            target_errors[key] = terr
            errors.extend([f"{key}:{x}" for x in terr])
    not_edited = [name for name, changed in edit_observed_by_object.items() if not changed]
    if not_edited:
        errors.append("STRESS_TARGET_EDIT_NOT_OBSERVED")
    if len(resolved) != len(refs):
        errors.append("TARGET_REF_RESOLUTION_INCOMPLETE")

    return {
        "format": VERIFY_FORMAT,
        "status": "PASS" if not errors else "FAIL",
        "source": str(source),
        "output": str(output),
        "skeleton": str(skeleton),
        "objects": refs,
        "target_count": len(refs),
        "resolved_target_count": len(resolved),
        "targets": targets,
        "edit_observed_by_object": edit_observed_by_object,
        "all_target_edits_observed": len(edit_observed_by_object) == len(refs) and bool(edit_observed_by_object) and all(edit_observed_by_object.values()),
        "targets_without_observed_edit": not_edited,
        "unknown_physique_bones_by_object": unknown_by_object,
        "target_errors": target_errors,
        "non_target_changed": non_target_changed,
        "errors": errors,
        "candidate_only": True,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def stress_context_key(asset_path: str, selected_context: dict[str, Any] | None, objects: list[str]) -> str:
    context = dict(selected_context or {})
    basis = dict(context.get("selection_basis") or {})
    payload = {
        "asset": str(asset_path or "").replace("\\", "/").casefold(),
        "model_info_inx": str(((context.get("model_info_inx") or {}).get("logical")) or "").replace("\\", "/").casefold(),
        "skeleton_smb": str(((context.get("skeleton_smb") or {}).get("logical")) or "").replace("\\", "/").casefold(),
        "lod_groups_signature": str(context.get("lod_groups_signature") or "").lower(),
        "profile_id": str(basis.get("profile_id") or "").casefold(),
        "profile_version": int(basis.get("profile_version") or 0),
        "objects": sorted({str(x).casefold() for x in objects}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "RIGIDSTRESS-" + hashlib.sha256(raw).hexdigest()[:24].upper()
