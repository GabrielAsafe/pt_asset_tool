from __future__ import annotations

import json
import pathlib
import re
import struct
import subprocess
from types import SimpleNamespace
from typing import Any

from .multilayer_texlink import parse_multilayer_semantics
from .rare_rigid_binding import audit_rare_rigid_binding
from .rare_rigid_context import RARE_SMD_FILES
from .rare_support import prepare_model062_tooling_source
from .texture_overlay import prepare_texture_overlay
from .utils import low_path, norm_path, run_logged, sha256_file

MODEL_GROUPS = {"high": 0x0C0, "default": 0x104, "low": 0x148}


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def parse_inx_model_groups(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    data = pathlib.Path(path).read_bytes()
    groups: dict[str, dict[str, Any]] = {}
    for key, off in MODEL_GROUPS.items():
        if off + 68 > len(data):
            raise ValueError(f"INX too small for {key} group at 0x{off:04X}")
        count = struct.unpack_from("<i", data, off)[0]
        if not 0 <= count <= 4:
            raise ValueError(f"invalid {key} ModelNameCnt={count} at 0x{off:04X}")
        names = [_cstr(data[off + 4 + i * 16:off + 4 + (i + 1) * 16]) for i in range(4)]
        groups[key] = {"count": count, "names": names, "active": names[:count]}
    return groups


def choose_root_lod(groups: dict[str, dict[str, Any]]) -> str:
    # Prefer the historical default group when it exists. Some proven link-root
    # INX files (M6/M7) intentionally serialize only a high group.
    for lod in ("default", "high", "low"):
        if list((groups.get(lod) or {}).get("active") or []):
            return lod
    raise ValueError("verified target INX has no active model group")


def _find_rare_logical(target: str) -> str:
    key = low_path(norm_path(target))
    exact = [x for x in RARE_SMD_FILES if low_path(x) == key]
    if len(exact) == 1:
        return exact[0]
    # Keep this narrow: only exact rare filenames are accepted as basenames.
    base = pathlib.PurePosixPath(norm_path(target)).name.lower()
    by_base = [x for x in RARE_SMD_FILES if pathlib.PurePosixPath(x).name.lower() == base]
    if len(by_base) == 1:
        return by_base[0]
    raise ValueError(f"target is not one of the six proven rare rigid Model0.62 files: {target}")


def _used_texture_names(path: pathlib.Path) -> list[str]:
    sem = parse_multilayer_semantics(path)
    if sem.get("htexture_mapping_errors") or sem.get("stage_index_errors"):
        raise ValueError(f"Model0.62 texture semantics failed: {path}")
    used_ids: set[int] = set()
    for obj in sem.get("objects") or []:
        for face in obj.get("face_rows") or []:
            used_ids.add(int(face.get("material_id") or 0))
    names: list[str] = []
    seen: set[str] = set()
    for mat in sem.get("materials") or []:
        if int(mat.get("id") or 0) not in used_ids:
            continue
        for tex in list(mat.get("textures") or []) + list(mat.get("anim_textures") or []):
            name = norm_path(str(tex.get("Name") or ""))
            if not name:
                continue
            k = low_path(name)
            if k not in seen:
                seen.add(k)
                names.append(name)
    return names


def _merge_runtime_aliases(reg, logicals: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for logical in logicals:
        try:
            asset = reg.resolve(logical)
        except Exception:
            continue
        aliases.update(dict(getattr(asset, "runtime_path_aliases", {}) or {}))
    return aliases


def _safe_component(logical: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", pathlib.PurePosixPath(logical).name)


def _binding_row_for_target(binding: dict[str, Any], logical: str) -> dict[str, Any]:
    rows = [r for r in binding.get("rows") or [] if low_path(r.get("logical") or "") == low_path(logical)]
    if len(rows) != 1:
        raise ValueError(f"rare binding row unresolved/ambiguous for {logical}: {len(rows)}")
    row = rows[0]
    if not row.get("preview_binding_authorized") or row.get("binding_status") != "VERIFIED_INX_LINK_SKELETON":
        raise ValueError(f"rare binding is not preview-authorized: {logical}")
    links = list(row.get("verified_links") or [])
    if not links:
        raise ValueError(f"rare binding has no verified links: {logical}")
    targets = {low_path(x.get("target_inx") or "") for x in links}
    motions = {low_path(x.get("motion_smb") or "") for x in links}
    roots = {low_path(y) for x in links for y in (x.get("physical_root_models") or [])}
    if len(targets) != 1 or len(motions) != 1 or len(roots) != 1:
        raise ValueError(
            f"rare preview requires one target INX/motion/root context: targets={len(targets)} motions={len(motions)} roots={len(roots)}"
        )
    return row


def _prepare_one_preview(*, reg, resolver, certifications, settings, project_root: pathlib.Path,
                         binding: dict[str, Any], logical: str, work: pathlib.Path,
                         open_gui: bool = False) -> dict[str, Any]:
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    row = _binding_row_for_target(binding, logical)
    links = list(row["verified_links"])
    link0 = links[0]

    source_inxs = sorted({norm_path(x.get("source_inx") or "") for x in links}, key=str.lower)
    # CartolaFS has three source INXs but all serialize the same verified target.
    source_inx = source_inxs[0]
    target_inx = norm_path(link0["target_inx"])
    motion_smb = norm_path(link0["motion_smb"])
    roots = sorted({norm_path(y) for x in links for y in (x.get("physical_root_models") or [])}, key=str.lower)
    root_model = roots[0]

    rare_src = pathlib.Path(resolver.resolve(logical, required=True))
    rare_prepared = work / "prepared" / pathlib.PurePosixPath(logical)
    prep = prepare_model062_tooling_source(rare_src, rare_prepared)
    if prep.get("family") != row.get("physical_family"):
        raise ValueError(f"prepared family changed since binding proof: {prep.get('family')} != {row.get('physical_family')}")

    root_src = pathlib.Path(resolver.resolve(root_model, required=True))
    source_inx_path = pathlib.Path(resolver.resolve(source_inx, required=True))
    target_inx_path = pathlib.Path(resolver.resolve(target_inx, required=True))
    skeleton_path = pathlib.Path(resolver.resolve(motion_smb, required=True))

    target_groups = parse_inx_model_groups(target_inx_path)
    source_groups = parse_inx_model_groups(source_inx_path)
    root_lod = choose_root_lod(target_groups)
    source_active = list((source_groups.get(root_lod) or {}).get("active") or [])
    rare_visibility_policy = "SOURCE_INX_EXACT" if source_active else "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC"

    texture_names = []
    seen: set[str] = set()
    for source in (root_src, rare_prepared):
        for name in _used_texture_names(source):
            k = low_path(name)
            if k not in seen:
                seen.add(k); texture_names.append(name)
    aliases = _merge_runtime_aliases(reg, [logical, root_model])
    synth = SimpleNamespace(
        asset_id=f"RARE_PREVIEW::{logical}", primary_path=logical,
        kind="RARE_MODEL062_PREVIEW", textures=texture_names,
        runtime_path_aliases=aliases,
    )
    overlay_root, texture_report = prepare_texture_overlay(
        asset=synth, resolver=resolver, root=project_root, work=work / "textures"
    )
    if not texture_report.get("ready"):
        required = [x for x in texture_report.get("entries") or [] if x.get("affects_ready") and x.get("status") not in {
            "LINK_READY", "TGA_READY", "BMP_PROTECTED_DECODED", "BMP_SHIP_PROTECTED_DECODED",
            "LINK_READY_RUNTIME_ALIAS", "TGA_READY_RUNTIME_ALIAS", "BMP_PROTECTED_DECODED_RUNTIME_ALIAS", "BMP_SHIP_PROTECTED_DECODED_RUNTIME_ALIAS",
        }]
        raise RuntimeError(f"rare preview texture preparation failed: {required[:5]}")

    blend = work / "rare_rigid_context_preview.blend"
    import_report = work / "rare_rigid_import.json"
    importer_script = project_root / "pt_asset_tool/blender/import_rare_rigid_context.py"
    common_args = [
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(rare_prepared), "--root-smd", str(root_src),
        "--skeleton", str(skeleton_path),
        "--rare-model-info", str(source_inx_path), "--root-model-info", str(target_inx_path),
        "--root-lod", root_lod, "--rare-visibility-policy", rare_visibility_policy,
        "--client-root", str(overlay_root), "--out", str(blend), "--report", str(import_report),
        "--logical", logical, "--root-logical", root_model,
    ]
    run_logged(settings.blender_command() + [
        "--background", "--python-exit-code", "1", "--python", str(importer_script), "--", *common_args
    ], work / "01_rare_import.log")
    imported = json.loads(import_report.read_text(encoding="utf-8"))
    if imported.get("check") != "PASS":
        raise RuntimeError(f"rare Blender import failed: {imported}")

    check_report = work / "rare_rigid_transport.json"
    checker_script = project_root / "pt_asset_tool/blender/check_rare_rigid_context.py"
    run_logged(settings.blender_command() + [
        "--background", str(blend), "--python-exit-code", "1", "--python", str(checker_script), "--",
        "--importer", str(project_root / "history_py/pt_smd_blender_import_v3_static_armature.py"),
        "--rare-smd", str(rare_prepared), "--root-smd", str(root_src),
        "--skeleton", str(skeleton_path),
        "--rare-model-info", str(source_inx_path), "--root-model-info", str(target_inx_path),
        "--root-lod", root_lod, "--rare-visibility-policy", rare_visibility_policy,
        "--report", str(check_report),
    ], work / "02_rare_transport.log")
    checked = json.loads(check_report.read_text(encoding="utf-8"))
    if checked.get("check") != "PASS":
        raise RuntimeError(f"rare Blender transport failed: {checked}")

    artifact_sha = sha256_file(blend)
    try:
        asset_id = str(getattr(reg.resolve(logical), "asset_id", "") or "")
    except Exception:
        asset_id = ""
    if not asset_id:
        asset_id = "RARE::" + logical
    cert = certifications.add(
        asset_id=asset_id,
        asset_path=logical, family=row.get("physical_family") or "RARE_MODEL062",
        test="RARE_RIGID_BLENDER_PREVIEW", layer="AUTOMATIC", result="PASS",
        source_sha256=sha256_file(rare_src), artifact_sha256=artifact_sha,
        metadata={
            "binding_status": row.get("binding_status"), "source_inxs": source_inxs,
            "target_inx": target_inx, "motion_smb": motion_smb, "root_model": root_model,
            "root_lod": root_lod, "rare_visibility_policy": rare_visibility_policy,
            "prepared_source": str(rare_prepared), "preview_blend": str(blend),
            "import_report": str(import_report), "transport_report": str(check_report),
            "position_max_abs_error": checked.get("max_position_abs_error"),
            "uv_max_abs_error": checked.get("max_uv_abs_error"),
            "physique_mismatch_count": checked.get("physique_mismatch_count"),
            "texture_load_error_count": checked.get("texture_load_error_count"),
            "client_modified": False,
        },
    )

    summary = {
        "logical": logical,
        "physical_family": row.get("physical_family"),
        "binding_status": row.get("binding_status"),
        "source_inxs": source_inxs,
        "target_inx": target_inx,
        "motion_smb": motion_smb,
        "root_model": root_model,
        "root_lod": root_lod,
        "rare_visibility_policy": rare_visibility_policy,
        "rare_objects": imported.get("rare_objects"),
        "rare_visible_objects": imported.get("rare_visible_objects"),
        "root_visible_objects": imported.get("root_visible_objects"),
        "armature_bones": imported.get("armature_bones"),
        "textures_required": len(texture_names),
        "texture_prepare": "PASS",
        "texture_load_error_count": checked.get("texture_load_error_count"),
        "position_max_abs_error": checked.get("max_position_abs_error"),
        "uv_max_abs_error": checked.get("max_uv_abs_error"),
        "physique_mismatch_count": checked.get("physique_mismatch_count"),
        "preview_blend": str(blend),
        "certification_id": cert["certification_id"],
        "preview_integration": "PASS",
        "write_authorized": False,
        "client_modified": False,
    }
    (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if open_gui:
        viewer = project_root / "pt_asset_tool/blender/open_rare_rigid_preview.py"
        proc = subprocess.run(settings.blender_command() + [str(blend), "--python", str(viewer)], text=True)
        if proc.returncode:
            raise RuntimeError(f"Blender rare preview exited rc={proc.returncode}")
    return summary


def audit_rare_rigid_preview(reg, resolver, certifications, settings, *, project_root: pathlib.Path, work: pathlib.Path) -> dict[str, Any]:
    project_root = pathlib.Path(project_root)
    work = pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=project_root, work=work / "binding_recheck", bundle=None
    )
    if binding.get("status") != "PASS" or not binding.get("preview_integration_authorized"):
        raise RuntimeError("rare rigid binding recheck did not authorize preview")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for logical in RARE_SMD_FILES:
        try:
            rows.append(_prepare_one_preview(
                reg=reg, resolver=resolver, certifications=certifications, settings=settings,
                project_root=project_root, binding=binding, logical=logical,
                work=work / _safe_component(logical), open_gui=False,
            ))
        except Exception as exc:
            errors.append({"logical": logical, "error": f"{type(exc).__name__}: {exc}"})
    expected = len(RARE_SMD_FILES)
    passed = sum(r.get("preview_integration") == "PASS" for r in rows)
    result = {
        "format": "PT_RARE_RIGID_BLENDER_PREVIEW_V1",
        "status": "PASS" if passed == expected and not errors else "FAIL",
        "expected": expected,
        "audited": len(rows),
        "preview_pass": passed,
        "head_accessory_preview": sum(r.get("rare_visibility_policy") == "SOURCE_INX_EMPTY_SHOW_ALL_DIAGNOSTIC" for r in rows),
        "source_inx_exact_preview": sum(r.get("rare_visibility_policy") == "SOURCE_INX_EXACT" for r in rows),
        "texture_load_error_total": sum(int(r.get("texture_load_error_count") or 0) for r in rows),
        "physique_mismatch_total": sum(int(r.get("physique_mismatch_count") or 0) for r in rows),
        "max_position_abs_error": max([float(r.get("position_max_abs_error") or 0.0) for r in rows] or [0.0]),
        "max_uv_abs_error": max([float(r.get("uv_max_abs_error") or 0.0) for r in rows] or [0.0]),
        "errors": errors,
        "preview_integration_complete_candidate": passed == expected and not errors,
        "binding_write_authorized": False,
        "policy": {
            "binding": "reverify serialized LinkFile chain before every preview audit",
            "head_accessories": "source INX has zero model groups; show all rare chunks as diagnostic preview only",
            "legacy_name_mismatch": "do not rewrite MBHB18/MBHB19; exact INX visibility leaves the mismatched chunk untouched/hidden",
            "transport": "positions, stage0 UV and rigid Physique assignments are automatically compared after persisted Blender save",
            "write": "read-only preview does not authorize Model0.62 geometry/Physique writes",
            "client_modified": False,
        },
        "rows": rows,
    }
    report = work / "rare_rigid_preview_report.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(report)
    return result


def view_rare_rigid_preview(reg, resolver, certifications, settings, *, project_root: pathlib.Path, target: str, work: pathlib.Path) -> dict[str, Any]:
    logical = _find_rare_logical(target)
    binding = audit_rare_rigid_binding(
        reg, resolver, project_root=pathlib.Path(project_root), work=pathlib.Path(work) / "binding_recheck", bundle=None
    )
    if binding.get("status") != "PASS" or not binding.get("preview_integration_authorized"):
        raise RuntimeError("rare rigid binding recheck did not authorize preview")
    return _prepare_one_preview(
        reg=reg, resolver=resolver, certifications=certifications, settings=settings,
        project_root=pathlib.Path(project_root), binding=binding, logical=logical,
        work=pathlib.Path(work) / _safe_component(logical), open_gui=True,
    )
