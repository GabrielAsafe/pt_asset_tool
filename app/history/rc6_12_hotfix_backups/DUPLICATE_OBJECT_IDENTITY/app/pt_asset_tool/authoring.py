from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter
from typing import Any

from .static_roundtrip import _parse as parse_model062_bytes
from .workflow_dispatch import build_plan

PLAN_FORMAT = "PT_ASSET_AUTHORING_PLAN_V1"
WORKSPACE_FORMAT = "PT_ASSET_AUTHORING_WORKSPACE_V1"
SELECTED_CONTEXT_FORMAT = "PT_ASSET_SELECTED_AUTHORING_CONTEXT_V1"
STANDALONE_RIGID_CONTEXT_FORMAT = "PT_ASSET_STANDALONE_RIGID_CONTEXT_V1"
AUDIT_FORMAT = "PT_MODEL062_AUTHORING_CANDIDATES_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_logical(path: str | pathlib.PurePath) -> str:
    return str(path).replace("\\", "/").strip("/")


def normalize_lod_groups(groups: dict[str, Any] | None) -> dict[str, list[str]]:
    groups = groups or {}
    return {tier: [str(x) for x in (groups.get(tier) or [])] for tier in ("high", "default", "low")}


def lod_groups_signature(groups: dict[str, Any] | None) -> str:
    normalized = normalize_lod_groups(groups)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_selected_authoring_context(
    *,
    model_info_logical: str,
    model_info_path: pathlib.Path,
    skeleton_logical: str,
    skeleton_path: pathlib.Path,
    lod: str,
    lod_groups: dict[str, Any] | None,
    selection_basis: dict[str, Any] | None = None,
    selected_lod_nodes: list[str] | tuple[str, ...] | None = None,
    lod_selection_mode: str = "MODEL_GROUP_KEYS",
) -> dict[str, Any]:
    model_info_path = pathlib.Path(model_info_path).resolve()
    skeleton_path = pathlib.Path(skeleton_path).resolve()
    if not model_info_path.is_file():
        raise FileNotFoundError(model_info_path)
    if not skeleton_path.is_file():
        raise FileNotFoundError(skeleton_path)
    normalized_groups = normalize_lod_groups(lod_groups)
    lod = str(lod)
    if lod not in normalized_groups or not normalized_groups[lod]:
        raise RuntimeError(f"selected authoring LOD has no nodes: {lod}")
    selected_nodes = [str(x) for x in (selected_lod_nodes if selected_lod_nodes is not None else normalized_groups[lod]) if str(x)]
    if not selected_nodes:
        raise RuntimeError("selected authoring context has no effective nodes")
    selection_mode = str(lod_selection_mode or "MODEL_GROUP_KEYS")
    if selection_mode not in {"MODEL_GROUP_KEYS", "SINGLE_TIER_FULL_CONTAINER"}:
        raise RuntimeError(f"unsupported lod_selection_mode={selection_mode}")
    return {
        "format": SELECTED_CONTEXT_FORMAT,
        "model_info_inx": {
            "logical": _norm_logical(model_info_logical),
            "path": str(model_info_path),
            "size": model_info_path.stat().st_size,
            "sha256": _sha256(model_info_path),
        },
        "skeleton_smb": {
            "logical": _norm_logical(skeleton_logical),
            "path": str(skeleton_path),
            "size": skeleton_path.stat().st_size,
            "sha256": _sha256(skeleton_path),
        },
        "lod": lod,
        "lod_groups": normalized_groups,
        "lod_groups_signature": lod_groups_signature(normalized_groups),
        "selected_lod_nodes": selected_nodes,
        "lod_selection_mode": selection_mode,
        "selection_basis": dict(selection_basis) if selection_basis is not None else None,
    }


def build_standalone_rigid_authoring_context(
    *,
    asset_logical: str,
    source_path: pathlib.Path,
    skeleton_logical: str,
    skeleton_path: pathlib.Path,
    selected_nodes: list[str] | tuple[str, ...],
    structural_gate_report: pathlib.Path | None = None,
    selection_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a durable authoring identity for rigid Physique without model-info INX.

    This is intentionally a separate context format from the model-info/LOD
    context.  Directory/name proximity never authorizes it: callers must have
    already passed the physical SMD<->SMB structural gate.
    """
    source_path = pathlib.Path(source_path).resolve()
    skeleton_path = pathlib.Path(skeleton_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not skeleton_path.is_file():
        raise FileNotFoundError(skeleton_path)
    nodes = [str(x) for x in selected_nodes if str(x)]
    if not nodes:
        raise RuntimeError("standalone rigid authoring context requires at least one selected Physique node")
    basis = dict(selection_basis or {})
    if not basis:
        basis = {
            "kind": "EXPLICIT_SKELETON",
            "roundtrip_target": _norm_logical(asset_logical),
            "structural_gate": "PASS",
        }
    report_row = None
    if structural_gate_report is not None:
        rp = pathlib.Path(structural_gate_report).resolve()
        if rp.is_file():
            report_row = {"path": str(rp), "size": rp.stat().st_size, "sha256": _sha256(rp)}
    return {
        "format": STANDALONE_RIGID_CONTEXT_FORMAT,
        "asset": {
            "logical": _norm_logical(asset_logical),
            "path": str(source_path),
            "size": source_path.stat().st_size,
            "sha256": _sha256(source_path),
        },
        "model_info_inx": None,
        "skeleton_smb": {
            "logical": _norm_logical(skeleton_logical),
            "path": str(skeleton_path),
            "size": skeleton_path.stat().st_size,
            "sha256": _sha256(skeleton_path),
        },
        "lod": "standalone",
        "lod_groups": {"high": [], "default": [], "low": []},
        "lod_groups_signature": None,
        "selected_lod_nodes": nodes,
        "selection_basis": basis,
        "structural_gate_report": report_row,
    }


def _verify_file_identity(row: dict[str, Any] | None, label: str) -> tuple[list[str], dict[str, Any]]:
    row = dict(row or {})
    logical = _norm_logical(str(row.get("logical") or ""))
    path = pathlib.Path(str(row.get("path") or ""))
    row_errors: list[str] = []
    if not logical:
        row_errors.append("LOGICAL_MISSING")
    if not path.is_file():
        row_errors.append("MISSING")
    else:
        if path.stat().st_size != int(row.get("size") or -1):
            row_errors.append("SIZE_DRIFT")
        if str(row.get("sha256") or "").lower() != _sha256(path).lower():
            row_errors.append("SHA_DRIFT")
    return [f"{label}_{x}" for x in row_errors], {
        "logical": logical, "path": str(path), "ok": not row_errors, "errors": row_errors,
    }


def verify_selected_authoring_context(context: dict[str, Any] | None) -> dict[str, Any]:
    errors: list[str] = []
    context = dict(context or {})
    fmt = context.get("format")
    identity_results: dict[str, dict[str, Any]] = {}

    if fmt == STANDALONE_RIGID_CONTEXT_FORMAT:
        selected_nodes = [str(x) for x in (context.get("selected_lod_nodes") or []) if str(x)]
        if str(context.get("lod") or "") != "standalone":
            errors.append("LOD_INVALID")
        if not selected_nodes:
            errors.append("SELECTED_LOD_NODES_EMPTY")
        if context.get("model_info_inx") not in (None, {}):
            errors.append("MODEL_INFO_MUST_BE_ABSENT")
        basis = dict(context.get("selection_basis") or {})
        if basis.get("kind") not in {"EXPLICIT_SKELETON", "AUTOMATED_STRUCTURAL_SKELETON"}:
            errors.append("SELECTION_BASIS_KIND_INVALID")
        if basis.get("structural_gate") != "PASS":
            errors.append("STRUCTURAL_GATE_NOT_PROVEN")
        target = _norm_logical(str(basis.get("roundtrip_target") or ""))
        if not target:
            errors.append("SELECTION_BASIS_TARGET_MISSING")
        e, ident = _verify_file_identity(context.get("skeleton_smb"), "SKELETON")
        errors.extend(e); identity_results["skeleton_smb"] = ident
        e, asset_ident = _verify_file_identity(context.get("asset"), "ASSET")
        errors.extend(e); identity_results["asset"] = asset_ident
        return {
            "format": "PT_ASSET_SELECTED_AUTHORING_CONTEXT_VERIFY_V1",
            "status": "PASS" if not errors else "FAIL",
            "context_kind": "STANDALONE_RIGID",
            "errors": sorted(set(errors)),
            "lod": "standalone",
            "lod_groups_signature": None,
            "identities": identity_results,
            "client_modified": False,
        }

    if fmt != SELECTED_CONTEXT_FORMAT:
        errors.append("FORMAT")
    groups = normalize_lod_groups(context.get("lod_groups") or {})
    lod = str(context.get("lod") or "")
    if lod not in groups:
        errors.append("LOD_INVALID")
    elif not groups[lod]:
        errors.append("LOD_EMPTY")
    expected_sig = lod_groups_signature(groups)
    if str(context.get("lod_groups_signature") or "").lower() != expected_sig.lower():
        errors.append("LOD_GROUPS_SIGNATURE_DRIFT")
    selection_mode = str(context.get("lod_selection_mode") or "MODEL_GROUP_KEYS")
    selected_nodes = [str(x) for x in (context.get("selected_lod_nodes") or []) if str(x)]
    if selection_mode == "MODEL_GROUP_KEYS":
        if selected_nodes != list(groups.get(lod) or []):
            errors.append("SELECTED_LOD_NODES_DRIFT")
    elif selection_mode == "SINGLE_TIER_FULL_CONTAINER":
        nonempty = [tier for tier in ("high","default","low") if groups.get(tier)]
        if len(nonempty) != 1 or nonempty[0] != lod:
            errors.append("FULL_CONTAINER_REQUIRES_SINGLE_TIER")
        if not selected_nodes:
            errors.append("SELECTED_LOD_NODES_EMPTY")
    else:
        errors.append("LOD_SELECTION_MODE_INVALID")
    selection_basis = context.get("selection_basis")
    if selection_basis is not None:
        basis = dict(selection_basis or {})
        kind = str(basis.get("kind") or "")
        if kind == "CANONICAL_PROFILE":
            if not str(basis.get("profile_id") or ""):
                errors.append("SELECTION_BASIS_PROFILE_ID_MISSING")
        elif kind in {"EXPLICIT_SKELETON_LOD", "AUTOMATED_EXPLICIT_SKELETON_LOD"}:
            if basis.get("structural_gate") != "PASS":
                errors.append("STRUCTURAL_GATE_NOT_PROVEN")
        else:
            errors.append("SELECTION_BASIS_KIND_INVALID")
        if not _norm_logical(str(basis.get("roundtrip_target") or "")):
            errors.append("SELECTION_BASIS_TARGET_MISSING")

    for field, label in (("model_info_inx", "MODEL_INFO"), ("skeleton_smb", "SKELETON")):
        e, ident = _verify_file_identity(context.get(field), label)
        errors.extend(e); identity_results[field] = ident
    return {
        "format": "PT_ASSET_SELECTED_AUTHORING_CONTEXT_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "context_kind": "MODEL_INFO",
        "errors": sorted(set(errors)),
        "lod": lod,
        "lod_groups_signature": expected_sig,
        "identities": identity_results,
        "client_modified": False,
    }

def verify_selected_context_for_asset(context: dict[str, Any] | None, asset, resolver=None) -> dict[str, Any]:
    base = verify_selected_authoring_context(context)
    errors = list(base.get("errors") or [])
    context = dict(context or {})
    fmt = context.get("format")
    skeleton_row = dict(context.get("skeleton_smb") or {})
    skeleton_logical = _norm_logical(str(skeleton_row.get("logical") or ""))

    if fmt == STANDALONE_RIGID_CONTEXT_FORMAT:
        asset_path = _norm_logical(str(getattr(asset, "primary_path", "") or ""))
        stored_asset = _norm_logical(str((context.get("asset") or {}).get("logical") or ""))
        target = _norm_logical(str((context.get("selection_basis") or {}).get("roundtrip_target") or ""))
        if stored_asset.casefold() != asset_path.casefold():
            errors.append("STANDALONE_ASSET_MISMATCH")
        if target.casefold() != asset_path.casefold():
            errors.append("SELECTION_BASIS_TARGET_MISMATCH")
        if str(getattr(asset, "family", "")) not in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
            errors.append("STANDALONE_CONTEXT_REQUIRES_RIGID_PHYSIQUE")
        if resolver is not None and skeleton_logical:
            try:
                resolved = pathlib.Path(resolver.resolve(skeleton_logical, required=True)).resolve()
                stored = pathlib.Path(str(skeleton_row.get("path") or "")).resolve()
                if resolved != stored:
                    errors.append("SKELETON_RESOLUTION_DRIFT")
            except Exception:
                errors.append("SKELETON_RESOLUTION_FAILED")
        return {
            **base,
            "format": "PT_ASSET_SELECTED_CONTEXT_ASSET_VERIFY_V1",
            "status": "PASS" if not errors else "FAIL",
            "errors": sorted(set(errors)),
            "asset_id": getattr(asset, "asset_id", None),
            "asset": getattr(asset, "primary_path", None),
        }

    model_row = dict(context.get("model_info_inx") or {})
    model_logical = _norm_logical(str(model_row.get("logical") or ""))
    lod = str(context.get("lod") or "")
    selection_basis = context.get("selection_basis")
    if selection_basis is not None:
        target = _norm_logical(str((selection_basis or {}).get("roundtrip_target") or ""))
        asset_path = _norm_logical(str(getattr(asset, "primary_path", "") or ""))
        if target.casefold() != asset_path.casefold():
            errors.append("SELECTION_BASIS_TARGET_MISMATCH")
    configs = [cfg for cfg in getattr(asset, "configs", []) if cfg.get("inx")]
    hits = [cfg for cfg in configs if _norm_logical(str(cfg.get("inx") or "")).casefold() == model_logical.casefold()]
    if not hits:
        errors.append("MODEL_INFO_NOT_ASSOCIATED_WITH_ASSET")
    else:
        cfg = hits[0]
        cfg_skeleton = _norm_logical(str(cfg.get("motion_smb") or ""))
        bound_skeleton = _norm_logical(str(getattr(asset, "binding_skeleton_smb", "") or ""))
        expected_skeleton = cfg_skeleton or bound_skeleton
        if expected_skeleton:
            if expected_skeleton.casefold() != skeleton_logical.casefold():
                errors.append("SKELETON_LOGICAL_MISMATCH")
        else:
            basis = dict(context.get("selection_basis") or {})
            if str(basis.get("kind") or "") not in {"EXPLICIT_SKELETON_LOD", "AUTOMATED_EXPLICIT_SKELETON_LOD"}:
                errors.append("SKELETON_NOT_PROVEN_BY_CONFIG_OR_EXPLICIT_STRUCTURAL_GATE")
            elif basis.get("structural_gate") != "PASS":
                errors.append("STRUCTURAL_GATE_NOT_PROVEN")
        expected_groups = normalize_lod_groups(cfg.get("lod_groups") or {})
        if lod_groups_signature(expected_groups).lower() != str(context.get("lod_groups_signature") or "").lower():
            errors.append("LOD_GROUPS_REGISTRY_DRIFT")
        if lod not in expected_groups or not expected_groups.get(lod):
            errors.append("LOD_NOT_AVAILABLE_IN_SELECTED_CONFIG")
    if resolver is not None:
        for logical, row, label in ((model_logical, model_row, "MODEL_INFO"), (skeleton_logical, skeleton_row, "SKELETON")):
            if not logical:
                continue
            try:
                resolved = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            except Exception:
                errors.append(f"{label}_RESOLUTION_FAILED")
                continue
            stored = pathlib.Path(str(row.get("path") or "")).resolve()
            if resolved != stored:
                errors.append(f"{label}_RESOLUTION_DRIFT")
    return {
        **base,
        "format": "PT_ASSET_SELECTED_CONTEXT_ASSET_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(set(errors)),
        "asset_id": getattr(asset, "asset_id", None),
        "asset": getattr(asset, "primary_path", None),
    }

def _source_summary(path: pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path).resolve()
    data = path.read_bytes()
    parsed = parse_model062_bytes(data)
    objects = []
    for name, obj in parsed["objects"].items():
        layer_depths = [len(face.get("uv_layers") or []) for face in obj["faces"]]
        max_layers = max(layer_depths, default=0)
        min_layers = min(layer_depths, default=0)
        local_counts = [int(obj["nr"]), int(obj["np"]), int(obj["ns"])]
        objects.append({
            "name": name,
            "physique": bool(obj["phys"]),
            "vertices": int(obj["nv"]),
            "faces": int(obj["nf"]),
            "texlinks": int(obj["nt"]),
            "object_local_rot_keys": int(obj["nr"]),
            "object_local_pos_keys": int(obj["np"]),
            "object_local_scale_keys": int(obj["ns"]),
            "texlink_min_layers": min_layers,
            "texlink_max_layers": max_layers,
            "object_local_key_counts": local_counts,
            "has_object_local_animation": any(local_counts),
            "static_saved_blender_candidate": (
                not bool(obj["phys"])
                and not any(local_counts)
                and bool(obj["faces"])
                and int(obj["nv"]) >= 3
                and min_layers == 1
                and max_layers == 1
            ),
            "rigid_saved_blender_candidate": (
                bool(obj["phys"])
                and not any(local_counts)
                and bool(obj["faces"])
                and int(obj["nv"]) >= 3
                and min_layers == 1
                and max_layers == 1
            ),
        })
    phys = sum(1 for obj in objects if obj["physique"])
    if objects and phys == len(objects):
        mode = "RIGID"
    elif objects and phys == 0:
        mode = "STATIC"
    elif objects and 0 < phys < len(objects):
        mode = "MIXED"
    else:
        mode = "UNKNOWN"
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size": len(data),
        "mode": mode,
        "object_count": len(objects),
        "objects": objects,
        "objects_with_object_local_animation": sum(1 for x in objects if x["has_object_local_animation"]),
        "objects_with_object_local_pos_scale_keys": [x["name"] for x in objects if x["object_local_pos_keys"] or x["object_local_scale_keys"]],
        "objects_with_object_local_rotation_keys": [x["name"] for x in objects if x["object_local_rot_keys"]],
        "objects_with_multilayer_texlinks": sum(1 for x in objects if x["texlink_max_layers"] > 1),
        "static_saved_blender_candidate_objects": [x["name"] for x in objects if x["static_saved_blender_candidate"]],
        "rigid_saved_blender_candidate_objects": [x["name"] for x in objects if x["rigid_saved_blender_candidate"]],
    }


def authoring_plan(asset, source_path: pathlib.Path | None = None) -> dict[str, Any]:
    writer_plan = build_plan(asset)
    base: dict[str, Any] = {
        "format": PLAN_FORMAT,
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "family": asset.family,
        "kind": asset.kind,
        "physique_mode": asset.physique_mode,
        "build_plan": writer_plan,
        "source_analysis": None,
        "channels": {},
        "blockers": [],
        "generic_build_authorized": bool(writer_plan.get("authorized")),
        "client_write_authorized": False,
        "client_modified": False,
    }

    if asset.kind == "SMD_STAGE_072":
        base["channels"] = {
            "geometry": {"maturity": "SPECIALIZED_ROUNDTRIP", "writer": "stage072 geometry witness writer"},
            "uv_texlink": {"maturity": "SPECIALIZED_ROUNDTRIP", "writer": "stage072 UV witness writer"},
            "texture_paint": {"maturity": "EDIT_WORKSPACE", "writer": None},
            "saved_blender_build": {
                "maturity": "CANDIDATE_STRICT_EDIT_SET",
                "writer": "pt_asset_tool.stage072_authoring_candidate",
                "accepted_edit_modes": ["UV_ONLY", "GEOMETRY_GRID_MULTI"],
            },
        }
        base["blockers"] = ["STAGE072_SAVED_EDIT_CANDIDATE_NOT_PRODUCTION_PROMOTED"]
        return base

    if asset.kind != "SMD_MODEL_062":
        base["channels"] = {"authoring": {"maturity": "UNSUPPORTED", "writer": None}}
        base["blockers"] = ["NO_AUTHORING_ADAPTER_FOR_KIND"]
        return base

    # Certified outliers may deliberately violate generic parser invariants.
    # Their specialized writer/guard is authoritative and must not be demoted
    # by a generic preflight parser (at_dragon has a known NodeName mismatch).
    if writer_plan.get("authorized"):
        base["channels"] = {
            "geometry": {"maturity": "PRODUCTION_CERTIFIED_GUARDED", "writer": writer_plan.get("adapter")},
            "normals": {"maturity": "PRODUCTION_CERTIFIED_GUARDED", "writer": "rare rigid normal bridge"},
            "physique": {"maturity": "PRESERVED_WITH_GUARDS", "writer": writer_plan.get("adapter")},
            "saved_blender_build": {"maturity": "PRODUCTION_CERTIFIED_GUARDED", "writer": writer_plan.get("adapter")},
        }
        base["blockers"] = []
        return base

    if asset.family == "SMD_MODEL_062_VARIANT_OR_DAMAGED":
        base["channels"] = {
            "authoring": {"maturity": "SPECIALIZED_OUTLIER_ONLY", "writer": None},
            "saved_blender_build": {"maturity": "NOT_CERTIFIED", "writer": None},
        }
        base["blockers"] = ["VARIANT_OR_DAMAGED_REQUIRES_SPECIALIZED_PROBE_AND_WRITER"]
        return base

    analysis = None
    if source_path is not None:
        analysis = _source_summary(pathlib.Path(source_path))
        base["source_analysis"] = analysis

    if asset.family == "SMD_MODEL_062_STATIC":
        eligible = list((analysis or {}).get("static_saved_blender_candidate_objects") or [])
        local = int((analysis or {}).get("objects_with_object_local_animation") or 0)
        local_pos_scale = list((analysis or {}).get("objects_with_object_local_pos_scale_keys") or [])
        local_rot = list((analysis or {}).get("objects_with_object_local_rotation_keys") or [])
        multi = int((analysis or {}).get("objects_with_multilayer_texlinks") or 0)
        base["channels"] = {
            "geometry": {
                "maturity": "CANDIDATE_PER_OBJECT" if eligible else ("PREFLIGHT_REQUIRED" if analysis is None else "BLOCKED_BY_SOURCE_FEATURES"),
                "writer": "pt_blender_to_smd_static_v1.py",
                "eligible_objects": eligible,
                "constraints": ["no Physique", "no object-local animation on target", "exactly one TexLink layer per face", "existing material IDs"],
            },
            "normals": {"maturity": "CANDIDATE_WITH_GEOMETRY", "writer": "pt_blender_to_smd_static_v1.py"},
            "uv_texlink": {
                "maturity": "CANDIDATE_SINGLE_LAYER" if analysis is not None and multi == 0 else "SPECIALIZED_OR_BLOCKED",
                "writer": "pt_blender_to_smd_static_v1.py / strict TexLink roundtrip",
            },
            "object_local": {
                "maturity": "CANDIDATE_EXISTING_ROT_POS_SCALE_KEYS" if (local_pos_scale or local_rot) else ("READ_VALIDATE_ONLY" if local else "ABSENT"),
                "writer": "pt_asset_tool.object_local_writer" if (local_pos_scale or local_rot) else None,
                "eligible_pos_scale_objects": local_pos_scale,
                "eligible_rotation_objects": local_rot,
                "constraints": [
                    "existing key only", "no frame/count change", "SCALE grid 1/256",
                    "ROT rebuilds cumulative TmPrevRot suffix", "segmented TmFrame tables preserved for existing-key edits",
                ],
            },
            "physique": {"maturity": "NOT_APPLICABLE", "writer": None},
            "saved_blender_build": {"maturity": "CANDIDATE_NOT_PROMOTED", "writer": "pt_blender_to_smd_static_v1.py"},
        }
        if analysis is None:
            base["blockers"].append("PHYSICAL_SOURCE_PREFLIGHT_REQUIRED")
        if analysis is not None and not eligible:
            base["blockers"].append("NO_STATIC_OBJECT_SATISFIES_SAVED_BLENDER_WRITER_CONTRACT")
        if local_pos_scale or local_rot:
            base["blockers"].append("OBJECT_LOCAL_ROT_POS_SCALE_WRITER_CANDIDATE_NOT_PRODUCTION_PROMOTED")
        if multi:
            base["blockers"].append("MULTILAYER_TEXLINK_REQUIRES_SPECIALIZED_WRITER")
        base["blockers"].append("STATIC_SAVED_BLENDER_WRITER_NOT_PRODUCTION_PROMOTED")
        return base

    if asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE" or asset.physique_mode == "RIGID":
        dependency_ready = bool(getattr(asset, "rigid_binding_ready", False))
        eligible = list((analysis or {}).get("rigid_saved_blender_candidate_objects") or [])
        local = int((analysis or {}).get("objects_with_object_local_animation") or 0)
        multi = int((analysis or {}).get("objects_with_multilayer_texlinks") or 0)
        if not dependency_ready:
            geometry_maturity = "BLOCKED_BY_BINDING"
        elif analysis is None:
            geometry_maturity = "PREFLIGHT_REQUIRED"
        elif eligible:
            geometry_maturity = "CANDIDATE_PER_OBJECT"
        else:
            geometry_maturity = "BLOCKED_BY_SOURCE_FEATURES"
        base["channels"] = {
            "geometry": {
                "maturity": geometry_maturity,
                "writer": "pt_blender_to_smd_free_mesh_v3.py",
                "eligible_objects": eligible,
                "constraints": ["rigid 1.0 bone assignment per vertex", "known skeleton bone names", "existing material IDs"],
            },
            "physique": {"maturity": "IMPORT_PROVEN_GENERIC_WRITE_NOT_CERTIFIED", "writer": "pt_blender_to_smd_free_mesh_v3.py"},
            "animation": {"maturity": "SOURCE_AND_BLENDER_REVIEW_PIPELINE" if asset.animation_binding_ready else "CONTEXT_INCOMPLETE", "writer": "candidate SMB writer for existing keys only"},
            "config_motioninfo": {"maturity": "CANDIDATE_EDIT_CORPUS_PROVEN", "writer": "pt_asset_tool.inx_writer"},
            "skeleton_motion_keys": {"maturity": "CANDIDATE_EDIT_CORPUS_PROVEN", "writer": "pt_asset_tool.smb_writer"},
            "saved_blender_build": {"maturity": "CANDIDATE_NOT_PROMOTED", "writer": "pt_blender_to_smd_free_mesh_v3.py"},
        }
        if not dependency_ready:
            base["blockers"].append("RIGID_SKELETON_BINDING_NOT_READY")
        if analysis is None:
            base["blockers"].append("PHYSICAL_SOURCE_PREFLIGHT_REQUIRED")
        if analysis is not None and not eligible:
            base["blockers"].append("NO_RIGID_OBJECT_SATISFIES_SAVED_BLENDER_WRITER_CONTRACT")
        if local:
            base["blockers"].append("OBJECT_LOCAL_ANIMATION_WRITER_NOT_GENERIC")
        if multi:
            base["blockers"].append("MULTILAYER_TEXLINK_REQUIRES_SPECIALIZED_WRITER")
        base["blockers"].append("GENERIC_RIGID_SAVED_BLENDER_WRITER_NOT_PRODUCTION_PROMOTED")
        return base

    if asset.physique_mode == "MIXED" or asset.family == "SMD_MODEL_062_MIXED_PHYSIQUE":
        eligible_rigid = list((analysis or {}).get("rigid_saved_blender_candidate_objects") or [])
        eligible_static = list((analysis or {}).get("static_saved_blender_candidate_objects") or [])
        base["channels"] = {
            "geometry": {
                "maturity": "CANDIDATE_PIPELINE_WIRED_AWAITING_REAL_CORPUS",
                "writer": "pt_asset_tool.mixed_authoring_candidate",
                "eligible_rigid_objects": eligible_rigid,
                "eligible_static_objects": eligible_static,
                "adapters": {"RIGID": "pt_blender_to_smd_free_mesh_v3.py", "STATIC": "pt_blender_to_smd_static_v1.py"},
                "constraints": [
                    "object-local target tracks must use their specialized writer",
                    "single-layer TexLink for generic geometry target",
                    "rigid objects require an explicit/proven skeleton context",
                    "non-target object blocks preserved",
                ],
            },
            "physique": {"maturity": "PER_OBJECT_MODE_PRESERVED", "writer": "mixed rigid/static dispatch"},
            "saved_blender_build": {"maturity": "IMPLEMENTED_SYNTHETIC_AWAITING_REAL_REPRESENTATIVE", "writer": "pt_asset_tool.mixed_authoring_candidate"},
        }
        if analysis is None:
            base["blockers"].append("PHYSICAL_SOURCE_PREFLIGHT_REQUIRED")
        if analysis is not None and (not eligible_rigid or not eligible_static):
            base["blockers"].append("MIXED_SOURCE_LACKS_ELIGIBLE_RIGID_OR_STATIC_TARGET")
        base["blockers"].append("MIXED_PHYSIQUE_REAL_CORPUS_CERTIFICATION_REQUIRED")
        return base

    base["channels"] = {"authoring": {"maturity": "UNCLASSIFIED", "writer": None}}
    base["blockers"] = ["MODEL062_AUTHORING_FAMILY_NOT_CLASSIFIED"]
    return base


def write_workspace_manifest(
    workspace: pathlib.Path, asset, source_path: pathlib.Path, plan: dict[str, Any],
    dependencies: list[pathlib.Path] | None = None, *, selected_context: dict[str, Any] | None = None,
) -> pathlib.Path:
    workspace = pathlib.Path(workspace).resolve()
    source_path = pathlib.Path(source_path).resolve()
    deps = []
    for p in dependencies or []:
        pp = pathlib.Path(p).resolve()
        if not pp.is_file():
            continue
        deps.append({"path": str(pp), "size": pp.stat().st_size, "sha256": _sha256(pp)})
    payload = {
        "format": WORKSPACE_FORMAT,
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "family": asset.family,
        "kind": asset.kind,
        "source": {"path": str(source_path), "size": source_path.stat().st_size, "sha256": _sha256(source_path)},
        "dependencies": deps,
        "selected_context": dict(selected_context) if selected_context is not None else None,
        "authoring_plan": plan,
        "provenance_state": "VERIFIED_AT_IMPORT",
        "build_authorized": bool(plan.get("generic_build_authorized")),
        "client_write_authorized": False,
        "client_modified": False,
    }
    out = workspace / "authoring_manifest.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def verify_workspace_manifest(path: pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("format") != WORKSPACE_FORMAT:
        errors.append("FORMAT")
    source = data.get("source") or {}
    sp = pathlib.Path(str(source.get("path") or ""))
    if not sp.is_file():
        errors.append("SOURCE_MISSING")
    else:
        if sp.stat().st_size != int(source.get("size") or -1):
            errors.append("SOURCE_SIZE_DRIFT")
        if _sha256(sp) != source.get("sha256"):
            errors.append("SOURCE_SHA_DRIFT")
    selected_context = data.get("selected_context")
    selected_context_verification = None
    if selected_context is not None:
        selected_context_verification = verify_selected_authoring_context(selected_context)
        if selected_context_verification.get("status") != "PASS":
            errors.append("SELECTED_CONTEXT_DRIFT")
    elif data.get("family") in {"SMD_MODEL_062_RIGID_PHYSIQUE", "SMD_MODEL_062_MIXED_PHYSIQUE"}:
        errors.append("SELECTED_CONTEXT_MISSING")

    dependency_results = []
    for dep in data.get("dependencies") or []:
        dp = pathlib.Path(str(dep.get("path") or ""))
        ok = dp.is_file()
        reason = None
        if not ok:
            reason = "MISSING"
        elif dp.stat().st_size != int(dep.get("size") or -1):
            ok, reason = False, "SIZE_DRIFT"
        elif _sha256(dp) != dep.get("sha256"):
            ok, reason = False, "SHA_DRIFT"
        dependency_results.append({"path": str(dp), "ok": ok, "reason": reason})
        if not ok:
            errors.append("DEPENDENCY_DRIFT")
    return {
        "format": "PT_ASSET_AUTHORING_WORKSPACE_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "manifest": str(path),
        "asset": data.get("asset"),
        "provenance_state": data.get("provenance_state"),
        "errors": sorted(set(errors)),
        "dependencies": dependency_results,
        "selected_context": selected_context,
        "selected_context_verification": selected_context_verification,
        "build_authorized": bool(data.get("build_authorized")) and not errors,
        "client_write_authorized": False,
        "client_modified": False,
    }


def audit_model062_authoring(registry, resolver, *, category: str | None = None, physical_only: bool = True, sample_limit: int = 50) -> dict[str, Any]:
    rows = []
    counts = Counter()
    family_counts: dict[str, Counter] = {}
    candidate_asset_counts: Counter = Counter()
    candidate_object_counts: Counter = Counter()
    for asset in registry.assets:
        if asset.kind != "SMD_MODEL_062":
            continue
        if category and str(asset.category).upper() != str(category).upper():
            continue
        try:
            source = pathlib.Path(resolver.resolve(asset.primary_path, required=True))
        except Exception:
            if physical_only:
                continue
            source = None
        try:
            plan = authoring_plan(asset, source)
            status = "ANALYZED"
            error = None
        except Exception as exc:
            plan = None
            status = "FAIL"
            error = f"{type(exc).__name__}:{exc}"
        if plan:
            geometry = (plan.get("channels") or {}).get("geometry") or {}
            maturity = str(geometry.get("maturity") or (plan.get("channels") or {}).get("authoring", {}).get("maturity") or "UNKNOWN")
            counts[maturity] += 1
            family_counts.setdefault(asset.family, Counter())[maturity] += 1
            eligible_objects = list(geometry.get("eligible_objects") or [])
            if maturity == "CANDIDATE_PER_OBJECT" and eligible_objects:
                candidate_asset_counts[asset.family] += 1
                candidate_object_counts[asset.family] += len(eligible_objects)
        else:
            maturity = "FAIL"
            eligible_objects = []
            counts[maturity] += 1
            family_counts.setdefault(asset.family, Counter())[maturity] += 1
        rows.append({
            "asset": asset.primary_path,
            "category": asset.category,
            "family": asset.family,
            "binding_mode": asset.binding_mode,
            "physical": source is not None,
            "status": status,
            "geometry_maturity": maturity,
            "candidate_objects": eligible_objects,
            "blockers": list((plan or {}).get("blockers") or []),
            "error": error,
        })
    failures = sum(1 for r in rows if r["status"] == "FAIL")
    return {
        "format": AUDIT_FORMAT,
        "status": "PASS" if failures == 0 else "FAIL",
        "assets_audited": len(rows),
        "failures": failures,
        "geometry_maturity_counts": dict(sorted(counts.items())),
        "family_maturity_counts": {fam: dict(sorted(vals.items())) for fam, vals in sorted(family_counts.items())},
        "candidate_asset_count": int(sum(candidate_asset_counts.values())),
        "candidate_object_count": int(sum(candidate_object_counts.values())),
        "family_candidate_asset_counts": dict(sorted(candidate_asset_counts.items())),
        "family_candidate_object_counts": dict(sorted(candidate_object_counts.items())),
        "samples": rows[: max(0, int(sample_limit))],
        "policy": {
            "candidate_does_not_imply_production_authorization": True,
            "client_source_read_only": True,
        },
        "client_modified": False,
    }
