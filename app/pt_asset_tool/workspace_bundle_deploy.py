from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import time
import uuid
from typing import Any

from pt_character_texture_v1_4 import (
    build_game_bytes as build_bmp_game_bytes,
    decode_editable as decode_bmp_editable,
    inspect_bmp_bytes,
    validate_edited_against_baseline,
)
from pt_protected_tga_v1 import (
    build_bytes as build_tga_game_bytes,
    decode_bytes as decode_tga_bytes,
    inspect_bytes as inspect_tga_bytes,
)

from .authoring import authoring_plan, verify_workspace_manifest
from .blender_workspace import asset_workspace_name, blender_edit_root
from .rare_support import build_ship_bmp_bytes, decode_ship_bmp_bytes
from .rigid_authoring_candidate import (
    _eligible_objects,
    _restrict_to_all_lods,
    build_rigid_candidate_blender_command,
    compare_rigid_candidate_semantics,
    plan_rigid_saved_blender_candidate,
    validate_rigid_candidate_output,
)
from .rigid_authoring_stress import validate_rigid_profile_stress_output
from .static_authoring_candidate import (
    build_static_candidate_blender_command,
    plan_static_saved_blender_candidate,
    validate_static_candidate_output,
)
from .utils import run_logged

try:  # Optional: only needed for PNG/JPEG workspace texture verification.
    from PIL import Image
except Exception:  # pragma: no cover - environment specific
    Image = None


FORMAT = "PT_ASSET_WORKSPACE_BUNDLE_TRANSACTION_V1"
APPLY_CONFIRMATION = "APPLY CLIENT BUNDLE"
RESTORE_CONFIRMATION = "RESTORE CLIENT BUNDLE"
ACTIVE_DEPLOY_STATES = {"APPLIED_VERIFIED", "PARTIALLY_RESTORED_VERIFIED"}


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def _atomic_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_bytes(path, raw)


def _atomic_bytes(path: pathlib.Path, data: bytes) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_replace_from(source: pathlib.Path, destination: pathlib.Path) -> None:
    source = pathlib.Path(source).resolve()
    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".ptdeploy", dir=str(destination.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if tmp.stat().st_size != source.stat().st_size or _sha256(tmp) != _sha256(source):
            raise RuntimeError(f"temporary deployment copy verification failed: {destination}")
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)


def _safe_client_relative(client_root: pathlib.Path, path: pathlib.Path) -> str:
    client_root = pathlib.Path(client_root).resolve()
    path = pathlib.Path(path).resolve()
    try:
        return path.relative_to(client_root).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"bundle source is outside configured client: {path}") from exc


def _editable_texture_bytes(source: pathlib.Path) -> tuple[bytes, str, dict[str, Any]]:
    raw = source.read_bytes()
    suffix = source.suffix.lower()
    if suffix == ".tga":
        editable, info = decode_tga_bytes(raw)
        return editable, "TGA_PROTECTED" if info.get("protected") else "TGA_STANDARD", dict(info)
    if suffix == ".bmp":
        if raw[:2] == b"BM":
            info = inspect_bmp_bytes(raw)
            return raw, "BMP_STANDARD", dict(info)
        try:
            info = inspect_bmp_bytes(raw)
            return decode_bmp_editable(raw, info), "BMP_PROTECTED_PREFIX14", dict(info)
        except Exception:
            editable, meta = decode_ship_bmp_bytes(raw)
            return editable, "BMP_SHIP_DIB40_PROTECTED_EXACT", dict(meta)
    return raw, suffix.lstrip(".").upper() or "BINARY_TEXTURE", {}


def _verify_same_raster_size(baseline: bytes, edited: bytes, suffix: str) -> dict[str, Any]:
    if Image is None:
        raise RuntimeError(f"Pillow is required to validate edited {suffix} texture")
    try:
        with Image.open(io.BytesIO(baseline)) as a:
            a.load()
            a_size = tuple(a.size)
        with Image.open(io.BytesIO(edited)) as b:
            b.load()
            b_size = tuple(b.size)
    except Exception as exc:
        raise ValueError(f"edited {suffix} is not a readable image: {type(exc).__name__}:{exc}") from exc
    if a_size != b_size:
        raise ValueError(f"edited texture dimensions changed: {a_size} -> {b_size}")
    return {"width": a_size[0], "height": a_size[1]}


def _build_texture_game_bytes(source: pathlib.Path, edited: pathlib.Path) -> tuple[bytes, dict[str, Any]]:
    source = pathlib.Path(source).resolve()
    edited = pathlib.Path(edited).resolve()
    baseline_raw = source.read_bytes()
    edited_raw = edited.read_bytes()
    baseline_editable, family, baseline_meta = _editable_texture_bytes(source)
    if edited_raw == baseline_editable:
        return baseline_raw, {
            "status": "UNCHANGED",
            "family": family,
            "editable_sha256": _sha256_bytes(edited_raw),
            "source_sha256": _sha256_bytes(baseline_raw),
        }

    suffix = source.suffix.lower()
    if suffix == ".tga":
        binfo = inspect_tga_bytes(baseline_raw)
        if binfo.get("protected"):
            game_bytes, _bi, _ei = build_tga_game_bytes(baseline_raw, edited_raw)
            decoded, _ = decode_tga_bytes(game_bytes)
            if decoded != edited_raw:
                raise RuntimeError("protected TGA rebuild did not decode byte-identically to edited workspace file")
            writer = "pt_protected_tga_v1.build_bytes"
        else:
            einfo = inspect_tga_bytes(edited_raw)
            if einfo.get("protected"):
                raise ValueError("standard TGA workspace edit unexpectedly became protected")
            keys = ("width", "height", "pixel_depth", "image_type", "color_map_type")
            diffs = {
                k: ((binfo.get("fields") or {}).get(k), (einfo.get("fields") or {}).get(k))
                for k in keys
                if (binfo.get("fields") or {}).get(k) != (einfo.get("fields") or {}).get(k)
            }
            if diffs:
                raise ValueError(f"standard TGA structure changed: {diffs}")
            game_bytes = edited_raw
            writer = "DIRECT_STANDARD_TGA"
    elif suffix == ".bmp":
        if family == "BMP_SHIP_DIB40_PROTECTED_EXACT":
            game_bytes, _meta = build_ship_bmp_bytes(baseline_raw, edited_raw)
            decoded, _ = decode_ship_bmp_bytes(game_bytes)
            if decoded != edited_raw:
                raise RuntimeError("ship BMP rebuild did not roundtrip edited workspace bytes")
            writer = "pt_asset_tool.rare_support.build_ship_bmp_bytes"
        else:
            binfo = inspect_bmp_bytes(baseline_raw)
            if binfo.get("standard"):
                validate_edited_against_baseline(edited_raw, binfo)
                game_bytes = edited_raw
                writer = "DIRECT_STANDARD_BMP"
            else:
                game_bytes, _bi, _ei = build_bmp_game_bytes(baseline_raw, edited_raw)
                decoded = decode_bmp_editable(game_bytes, inspect_bmp_bytes(game_bytes))
                if decoded != edited_raw:
                    raise RuntimeError("protected BMP rebuild did not roundtrip edited workspace bytes")
                writer = "pt_character_texture_v1_4.build_game_bytes"
    elif suffix in {".png", ".jpg", ".jpeg"}:
        raster = _verify_same_raster_size(baseline_editable, edited_raw, suffix)
        game_bytes = edited_raw
        writer = "DIRECT_STANDARD_IMAGE"
        baseline_meta = {**baseline_meta, **raster}
    else:
        raise ValueError(f"workspace bundle texture writer does not support {suffix}")

    if game_bytes == baseline_raw:
        return baseline_raw, {
            "status": "UNCHANGED",
            "family": family,
            "writer": writer,
            "editable_sha256": _sha256_bytes(edited_raw),
            "source_sha256": _sha256_bytes(baseline_raw),
        }
    return game_bytes, {
        "status": "MODIFIED",
        "family": family,
        "writer": writer,
        "source_sha256": _sha256_bytes(baseline_raw),
        "editable_sha256": _sha256_bytes(edited_raw),
        "game_sha256": _sha256_bytes(game_bytes),
        "baseline_meta": baseline_meta,
    }


def _legacy_rigid_importer(project_root: pathlib.Path) -> pathlib.Path:
    candidates = [
        project_root / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py",
        project_root / "history_py" / "pt_smd_blender_import_v3_static_armature.py",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise RuntimeError(
        "rigid Blender importer is unavailable; checked "
        + ", ".join(str(path) for path in candidates)
    )


def _ensure_pristine_rigid_blend(
    settings, resolver, asset, workspace: pathlib.Path, selected_context: dict[str, Any], evidence: pathlib.Path,
) -> dict[str, Any]:
    """Return a pristine import baseline without overwriting artist work.

    Older generic-import workspaces promoted ``pristine_import.blend`` to
    ``imported.blend`` with a move, so a valid historical workspace can lack the
    baseline file needed by semantic edit detection.  Rebuild it from the
    verified source/context in the authoring manifest and keep the edited blend
    untouched.
    """
    workspace = pathlib.Path(workspace).resolve()
    pristine = workspace / "pristine_import.blend"
    if pristine.is_file():
        return {
            "status": "PASS",
            "path": str(pristine),
            "source": "EXISTING",
            "rebuilt": False,
        }

    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    skeleton_row = dict(selected_context.get("skeleton_smb") or {})
    skeleton_raw = str(skeleton_row.get("path") or "").strip()
    if skeleton_raw:
        skeleton = pathlib.Path(skeleton_raw).expanduser().resolve()
    else:
        skeleton_logical = str(skeleton_row.get("logical") or "").strip()
        if not skeleton_logical:
            raise RuntimeError("PRISTINE_REBUILD_SKELETON_CONTEXT_MISSING")
        skeleton = pathlib.Path(resolver.resolve(skeleton_logical, required=True)).resolve()
    if not skeleton.is_file():
        raise RuntimeError(f"PRISTINE_REBUILD_SKELETON_MISSING:{skeleton}")

    model_info_row = dict(selected_context.get("model_info_inx") or {})
    model_info_raw = str(model_info_row.get("path") or "").strip()
    model_info_logical = str(model_info_row.get("logical") or "").strip()
    model_info: pathlib.Path | None = None
    if model_info_raw:
        model_info = pathlib.Path(model_info_raw).expanduser().resolve()
    elif model_info_logical:
        model_info = pathlib.Path(resolver.resolve(model_info_logical, required=True)).resolve()

    lod = str(selected_context.get("lod") or "").strip()
    importer = _legacy_rigid_importer(pathlib.Path(settings.project_root).resolve())
    texture_overlay = workspace / "texture_overlay_client"
    client_root = texture_overlay if texture_overlay.is_dir() else pathlib.Path(settings.client_root).resolve()

    evidence.mkdir(parents=True, exist_ok=True)
    tmp = workspace / f".pristine_import.rebuild.{uuid.uuid4().hex}.blend"
    log = evidence / "pristine_rebuild.log"
    cmd = list(settings.blender_command()) + [
        "--background", "--python-exit-code", "1", "--python", str(importer), "--",
        "--smd", str(source), "--skeleton", str(skeleton),
    ]
    if model_info is not None:
        if not model_info.is_file():
            raise RuntimeError(f"PRISTINE_REBUILD_MODEL_INFO_MISSING:{model_info}")
        if not lod or lod == "standalone":
            raise RuntimeError("PRISTINE_REBUILD_LOD_CONTEXT_MISSING")
        cmd += ["--model-info", str(model_info), "--lod", lod]
    cmd += ["--client-root", str(client_root), "--out", str(tmp), "--no-pack"]
    if str(selected_context.get("lod_selection_mode") or "") == "SINGLE_TIER_FULL_CONTAINER":
        cmd.append("--single-tier-full-container")

    try:
        run_logged(cmd, log)
        if not tmp.is_file() or tmp.stat().st_size <= 0:
            raise RuntimeError("PRISTINE_REBUILD_OUTPUT_MISSING")
        os.replace(tmp, pristine)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "status": "PASS",
        "path": str(pristine),
        "source": "REBUILT_FROM_VERIFIED_SOURCE_CONTEXT",
        "rebuilt": True,
        "log": str(log),
        "source_smd": str(source),
        "skeleton_smb": str(skeleton),
        "model_info_inx": str(model_info) if model_info is not None else None,
        "lod": lod or None,
        "client_root": str(client_root),
    }


def _load_workspace(project_root: pathlib.Path, asset) -> tuple[pathlib.Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    workspace = blender_edit_root(project_root, "generic_import", asset.primary_path).resolve()
    manifest_path = workspace / "authoring_manifest.json"
    info_path = workspace / "workspace_info.json"
    summary_path = workspace / "import_summary.json"
    if not workspace.is_dir() or not manifest_path.is_file() or not (workspace / "imported.blend").is_file():
        raise RuntimeError("generic import workspace is missing; use Importar para Blender first")
    verify = verify_workspace_manifest(manifest_path)
    if verify.get("status") != "PASS":
        raise RuntimeError(f"authoring workspace provenance failed: {verify.get('errors')}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    expected = str(asset.primary_path).replace("\\", "/").casefold()
    for row, label in ((manifest, "authoring_manifest"), (info, "workspace_info"), (summary, "import_summary")):
        if row and str(row.get("asset") or "").replace("\\", "/").casefold() != expected:
            raise RuntimeError(f"{label} asset does not match selected asset")
    return workspace, manifest, info, summary


def _build_model_candidate(settings, resolver, asset, txroot: pathlib.Path, *, auto_rigid_weight_repair: bool = True) -> dict[str, Any]:
    evidence = txroot / "evidence" / "model"
    evidence.mkdir(parents=True, exist_ok=True)
    candidate_output = evidence / pathlib.PurePosixPath(asset.primary_path).name
    writer_report = evidence / (candidate_output.name + ".writer.json")
    build_log = evidence / (candidate_output.name + ".build.log")

    try:
        if asset.family == "SMD_MODEL_062_STATIC":
            plan = plan_static_saved_blender_candidate(
                settings.project_root, resolver, asset, output=candidate_output
            )
            kind = "STATIC"
            if plan.get("status") != "READY":
                return {"status": "BLOCKED", "kind": kind, "blockers": plan.get("blockers") or [], "plan": plan}
            run_logged(build_static_candidate_blender_command(settings, plan, report=writer_report), build_log)
            verification = validate_static_candidate_output(
                pathlib.Path(plan["source"]), candidate_output, str(plan["object"])
            )
        elif asset.family == "SMD_MODEL_062_RIGID_PHYSIQUE":
            kind = "RIGID"
            source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
            base_authoring = authoring_plan(asset, source)
            workspace = blender_edit_root(settings.project_root, "generic_import", asset.primary_path).resolve()
            manifest_path = workspace / "authoring_manifest.json"
            manifest_verify = verify_workspace_manifest(manifest_path)
            if manifest_verify.get("status") != "PASS":
                return {
                    "status": "BLOCKED", "kind": kind,
                    "blockers": ["AUTHORING_WORKSPACE_PROVENANCE_FAILED"],
                    "manifest_verification": manifest_verify,
                }
            selected_context = dict(manifest_verify.get("selected_context") or {})
            all_objects, object_lods = _restrict_to_all_lods(_eligible_objects(base_authoring), selected_context)
            if not all_objects:
                return {
                    "status": "BLOCKED", "kind": kind,
                    "blockers": ["NO_WRITER_ELIGIBLE_LOD_OBJECTS"],
                    "selected_context": selected_context,
                }

            # Probe every writer-eligible node referenced by the saved LOD context.
            # Edit detection is pristine-workspace vs saved-workspace, not source-SMD vs
            # saved-workspace. Generic import can legitimately split vertices for face/UV
            # representation (TN-003H: 549 source -> 2183 Blender vertices), so source
            # indexing is not a valid authoring witness. Running pristine and edited through
            # the same AUTO/STRICT policy makes import normalization and deterministic weight
            # repair cancel out; only the user's saved change remains.
            probes_dir = evidence / "lod_probes"
            probes_dir.mkdir(parents=True, exist_ok=True)
            pristine_state = _ensure_pristine_rigid_blend(
                settings, resolver, asset, workspace, selected_context, evidence / "pristine_baseline"
            )
            pristine_blend = pathlib.Path(pristine_state["path"]).resolve()
            probes: list[dict[str, Any]] = []
            changed_objects: list[str] = []
            skeleton: pathlib.Path | None = None
            for idx, object_name in enumerate(all_objects, start=1):
                probe_output = probes_dir / f"{idx:02d}_{object_name}.edited.smd"
                probe_report = probes_dir / f"{idx:02d}_{object_name}.edited.writer.json"
                probe_log = probes_dir / f"{idx:02d}_{object_name}.edited.build.log"
                baseline_output = probes_dir / f"{idx:02d}_{object_name}.pristine.smd"
                baseline_report = probes_dir / f"{idx:02d}_{object_name}.pristine.writer.json"
                baseline_log = probes_dir / f"{idx:02d}_{object_name}.pristine.build.log"
                probe_plan = plan_rigid_saved_blender_candidate(
                    settings.project_root, resolver, asset, object_name=object_name,
                    output=probe_output, lod_scope="all",
                )
                if probe_plan.get("status") != "READY":
                    return {
                        "status": "BLOCKED", "kind": kind,
                        "blockers": probe_plan.get("blockers") or ["LOD_PROBE_PLAN_BLOCKED"],
                        "plan": probe_plan, "probes": probes,
                    }
                if skeleton is None:
                    skeleton = pathlib.Path(str(probe_plan["skeleton"])).resolve()

                probe_policy = "auto" if auto_rigid_weight_repair else "strict"
                baseline_plan = dict(probe_plan)
                baseline_plan["blend"] = str(pristine_blend.resolve())
                baseline_plan["output"] = str(baseline_output.resolve())
                baseline_plan["physique_policy"] = probe_policy
                run_logged(build_rigid_candidate_blender_command(settings, baseline_plan, report=baseline_report), baseline_log)

                edited_plan = dict(probe_plan)
                edited_plan["physique_policy"] = probe_policy
                run_logged(build_rigid_candidate_blender_command(settings, edited_plan, report=probe_report), probe_log)

                baseline_verification = validate_rigid_candidate_output(
                    settings.project_root, source, baseline_output, skeleton, object_name
                )
                edited_verification = validate_rigid_candidate_output(
                    settings.project_root, source, probe_output, skeleton, object_name
                )
                semantic_compare = compare_rigid_candidate_semantics(
                    baseline_output, probe_output, object_name
                )
                baseline_writer = json.loads(baseline_report.read_text(encoding="utf-8")) if baseline_report.is_file() else {}
                probe_writer = json.loads(probe_report.read_text(encoding="utf-8")) if probe_report.is_file() else {}
                probe_status = "PASS" if (
                    baseline_verification.get("status") == "PASS"
                    and edited_verification.get("status") == "PASS"
                    and semantic_compare.get("status") == "PASS"
                ) else "FAIL"
                probe_repairs = list(probe_writer.get("blender_weight_repairs") or [])
                baseline_repairs = list(baseline_writer.get("blender_weight_repairs") or [])
                probe = {
                    "object": object_name,
                    "lod": object_lods.get(object_name),
                    "status": probe_status,
                    "edit_observed": bool(semantic_compare.get("edit_observed")),
                    "byte_edit_observed": bool(edited_verification.get("byte_edit_observed")),
                    "verification": edited_verification,
                    "baseline_verification": baseline_verification,
                    "semantic_compare": semantic_compare,
                    "candidate": str(probe_output),
                    "baseline_candidate": str(baseline_output),
                    "writer_report": str(probe_report),
                    "baseline_writer_report": str(baseline_report),
                    "log": str(probe_log),
                    "baseline_log": str(baseline_log),
                    "physique_policy": probe_policy.upper(),
                    "source_physique_preserved": False,
                    "blender_weight_mismatch_count": int(
                        probe_writer.get("blender_weight_mismatch_count")
                        or probe_writer.get("blender_weight_repair_count")
                        or 0
                    ),
                    "blender_weight_mismatches": list(
                        probe_writer.get("blender_weight_mismatches")
                        or probe_repairs
                    ),
                    "blender_weight_repair_count": int(probe_writer.get("blender_weight_repair_count") or 0),
                    "blender_weight_repairs": probe_repairs,
                    "pristine_weight_repair_count": int(baseline_writer.get("blender_weight_repair_count") or 0),
                    "pristine_weight_repairs": baseline_repairs,
                    "blender_weight_edits_authorized": bool(auto_rigid_weight_repair),
                }
                probes.append(probe)
                if probe_status != "PASS":
                    return {
                        "status": "FAIL", "kind": kind,
                        "blockers": ["MODEL_LOD_PROBE_VERIFICATION_FAILED"],
                        "probes": probes,
                    }
                if probe["edit_observed"]:
                    changed_objects.append(object_name)

            lod_groups = dict(selected_context.get("lod_groups") or {})
            eligible_keys = {name.casefold(): name for name in all_objects}
            changed_keys = {name.casefold() for name in changed_objects}
            probe_by_key = {str(row.get("object") or "").casefold(): row for row in probes}
            lod_coverage: dict[str, Any] = {}
            for lod in ("high", "default", "low"):
                nodes = [eligible_keys[str(raw).casefold()] for raw in (lod_groups.get(lod) or []) if str(raw).casefold() in eligible_keys]
                if not nodes:
                    continue
                changed_nodes = [name for name in nodes if name.casefold() in changed_keys]
                supported_nodes = [
                    name for name in nodes
                    if (probe_by_key.get(name.casefold()) or {}).get("status") == "PASS"
                ]
                unsupported_nodes = [name for name in nodes if name not in supported_nodes]
                lod_coverage[lod] = {
                    "eligible_nodes": nodes,
                    "supported_nodes": supported_nodes,
                    "unsupported_nodes": unsupported_nodes,
                    "changed_nodes": changed_nodes,
                    "writer_covered": len(supported_nodes) == len(nodes),
                    "edit_observed": bool(changed_nodes),
                    "all_nodes_edited": len(changed_nodes) == len(nodes),
                }
            available_lods = list(lod_coverage)
            changed_lods = [lod for lod, row in lod_coverage.items() if row.get("edit_observed")]
            partial_lods = [lod for lod, row in lod_coverage.items() if row.get("changed_nodes") and not row.get("all_nodes_edited")]
            unmodified_lods = [lod for lod, row in lod_coverage.items() if not row.get("edit_observed")]
            uncovered_lods = [lod for lod, row in lod_coverage.items() if not row.get("writer_covered")]
            runtime_lod_coverage_complete = bool(available_lods) and not uncovered_lods
            physique_preserve_objects = [
                row["object"] for row in probes if int(row.get("blender_weight_mismatch_count") or 0) > 0
            ]
            physique_workspace_mismatch_count = sum(
                int(row.get("blender_weight_mismatch_count") or 0) for row in probes
            )
            probe_weight_repair_count = sum(
                int(row.get("blender_weight_repair_count") or 0) for row in probes
            )
            probe_weight_repairs = [
                {"object": row["object"], "lod": row.get("lod"), **repair}
                for row in probes for repair in (row.get("blender_weight_repairs") or [])
            ]
            probe_weight_repair_strategy_counts: dict[str, int] = {}
            for repair in probe_weight_repairs:
                key = str(repair.get("strategy") or "UNKNOWN")
                probe_weight_repair_strategy_counts[key] = probe_weight_repair_strategy_counts.get(key, 0) + 1

            if not changed_objects:
                return {
                    "status": "UNCHANGED", "kind": kind,
                    "candidate": None, "candidate_sha256": None, "candidate_size": 0,
                    "plan": {
                        "selected_context": selected_context,
                        "all_lod_objects": all_objects,
                        "object_lods": object_lods,
                    },
                    "verification": {
                        "status": "PASS",
                        "edit_observed": False,
                        "reason": "NO_SEMANTIC_MODEL_EDIT_DETECTED",
                    },
                    "probes": probes,
                    "pristine_baseline": pristine_state,
                    "changed_objects": [],
                    "available_lods": available_lods,
                    "changed_lods": [],
                    "partial_lods": [],
                    "unmodified_lods": available_lods,
                    "uncovered_lods": uncovered_lods,
                    "runtime_lod_coverage_complete": runtime_lod_coverage_complete,
                    "physique_policy": "AUTO_REPAIR" if auto_rigid_weight_repair else "STRICT",
                    "physique_probe_policy": "PRISTINE_VS_EDITED_" + ("AUTO_REPAIR" if auto_rigid_weight_repair else "STRICT"),
                    "physique_preserve_objects": physique_preserve_objects,
                    "blender_weight_mismatch_count": physique_workspace_mismatch_count,
                    "probe_weight_repair_count": probe_weight_repair_count,
                    "probe_weight_repairs": probe_weight_repairs[:64],
                    "probe_weight_repairs_truncated": max(0, len(probe_weight_repairs) - 64),
                    "probe_weight_repair_strategy_counts": probe_weight_repair_strategy_counts,
                    "auto_rigid_weight_repair_enabled": bool(auto_rigid_weight_repair),
                    "blender_weight_edits_authorized": bool(auto_rigid_weight_repair),
                    "candidate_only": True,
                    "local_explicit_deploy_eligible": True,
                }

            steps_dir = evidence / "lod_steps"
            steps_dir.mkdir(parents=True, exist_ok=True)
            current_source = source
            step_rows: list[dict[str, Any]] = []
            for idx, object_name in enumerate(changed_objects, start=1):
                is_last = idx == len(changed_objects)
                step_output = candidate_output if is_last else (steps_dir / f"{idx:02d}_{object_name}.smd")
                step_report = steps_dir / f"{idx:02d}_{object_name}.writer.json"
                step_log = steps_dir / f"{idx:02d}_{object_name}.build.log"
                step_plan = plan_rigid_saved_blender_candidate(
                    settings.project_root, resolver, asset, object_name=object_name,
                    output=step_output, lod_scope="all",
                )
                step_plan["source"] = str(current_source)
                step_plan["source_sha256"] = _sha256(current_source)
                step_plan["physique_policy"] = "auto" if auto_rigid_weight_repair else "strict"
                run_logged(build_rigid_candidate_blender_command(settings, step_plan, report=step_report), step_log)
                step_writer = json.loads(step_report.read_text(encoding="utf-8")) if step_report.is_file() else {}
                step_rows.append({
                    "object": object_name, "lod": object_lods.get(object_name),
                    "input": str(current_source), "output": str(step_output),
                    "writer_report": str(step_report), "log": str(step_log),
                    "physique_policy": step_plan["physique_policy"],
                    "blender_weight_repair_count": int(step_writer.get("blender_weight_repair_count") or 0),
                    "blender_weight_repairs": list(step_writer.get("blender_weight_repairs") or []),
                })
                current_source = step_output.resolve()

            auto_weight_repairs = [
                {"object": row["object"], "lod": row.get("lod"), **repair}
                for row in step_rows for repair in (row.get("blender_weight_repairs") or [])
            ]
            auto_weight_repair_count = sum(int(row.get("blender_weight_repair_count") or 0) for row in step_rows)
            auto_weight_repair_strategy_counts: dict[str, int] = {}
            for repair in auto_weight_repairs:
                key = str(repair.get("strategy") or "UNKNOWN")
                auto_weight_repair_strategy_counts[key] = auto_weight_repair_strategy_counts.get(key, 0) + 1

            if skeleton is None:
                raise RuntimeError("rigid LOD build resolved no skeleton")
            verification = validate_rigid_profile_stress_output(
                settings.project_root, source, candidate_output, skeleton, changed_objects
            )
            plan = {
                "status": "READY",
                "source": str(source),
                "skeleton": str(skeleton),
                "selected_context": selected_context,
                "all_lod_objects": all_objects,
                "object_lods": object_lods,
                "changed_objects": changed_objects,
                "steps": step_rows,
            }
            writer_report.write_text(json.dumps({
                "tool": "PT_WORKSPACE_RIGID_MULTI_LOD_WRITER_V1",
                "changed_objects": changed_objects,
                "object_lods": object_lods,
                "steps": step_rows,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            build_log.write_text(
                f"RIGID_MULTI_LOD changed_objects={changed_objects} available_lods={available_lods}\n",
                encoding="utf-8",
            )
        else:
            return {
                "status": "BLOCKED",
                "kind": "UNSUPPORTED",
                "blockers": ["MODEL_WORKSPACE_BUNDLE_WRITER_NOT_SUPPORTED_FOR_FAMILY"],
                "family": asset.family,
            }
    except Exception as exc:
        return {
            "status": "FAIL",
            "kind": str(asset.family),
            "blockers": ["MODEL_CANDIDATE_BUILD_FAILED"],
            "error": f"{type(exc).__name__}:{exc}",
            "log": str(build_log),
        }

    if verification.get("status") != "PASS":
        return {
            "status": "FAIL",
            "kind": kind,
            "blockers": ["MODEL_CANDIDATE_VERIFICATION_FAILED"],
            "plan": plan,
            "verification": verification,
            "candidate": str(candidate_output),
            "log": str(build_log),
        }
    edit_observed = bool(verification.get("edit_observed")) if kind != "RIGID" else bool(changed_objects)
    result = {
        "status": "MODIFIED" if edit_observed else "UNCHANGED",
        "kind": kind,
        "candidate": str(candidate_output),
        "candidate_sha256": _sha256(candidate_output),
        "candidate_size": candidate_output.stat().st_size,
        "plan": plan,
        "verification": verification,
        "writer_report": str(writer_report),
        "log": str(build_log),
        "target_object": plan.get("object"),
        "skeleton": plan.get("skeleton"),
        "candidate_only": True,
        "local_explicit_deploy_eligible": True,
    }
    if kind == "RIGID":
        result.update({
            "target_object": changed_objects[0] if len(changed_objects) == 1 else None,
            "target_objects": changed_objects,
            "probes": probes,
            "pristine_baseline": pristine_state,
            "available_lods": available_lods,
            "changed_lods": changed_lods,
            "partial_lods": partial_lods,
            "unmodified_lods": unmodified_lods,
            "uncovered_lods": uncovered_lods,
            "lod_coverage": lod_coverage,
            "runtime_lod_coverage_complete": runtime_lod_coverage_complete,
            "selected_lod": str(selected_context.get("lod") or ""),
            "physique_policy": "AUTO_REPAIR" if auto_rigid_weight_repair else "STRICT",
            "physique_probe_policy": "PRISTINE_VS_EDITED_" + ("AUTO_REPAIR" if auto_rigid_weight_repair else "STRICT"),
            "probe_weight_repair_count": probe_weight_repair_count,
            "probe_weight_repairs": probe_weight_repairs[:64],
            "probe_weight_repairs_truncated": max(0, len(probe_weight_repairs) - 64),
            "physique_preserve_objects": physique_preserve_objects,
            "blender_weight_mismatch_count": physique_workspace_mismatch_count,
            "auto_rigid_weight_repair_enabled": bool(auto_rigid_weight_repair),
            "blender_weight_repair_count": auto_weight_repair_count,
            "blender_weight_repairs": auto_weight_repairs[:64],
            "blender_weight_repairs_truncated": max(0, len(auto_weight_repairs) - 64),
            "blender_weight_repair_strategy_counts": auto_weight_repair_strategy_counts,
            "blender_weight_edits_authorized": bool(auto_rigid_weight_repair),
        })
    return result


def _copy_verified(source: pathlib.Path, destination: pathlib.Path) -> dict[str, Any]:
    source = pathlib.Path(source).resolve()
    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_sha = _sha256(source)
    dest_sha = _sha256(destination)
    if source.stat().st_size != destination.stat().st_size or source_sha != dest_sha:
        raise RuntimeError(f"verified copy failed: {source} -> {destination}")
    return {"path": str(destination), "sha256": dest_sha, "size": destination.stat().st_size, "verified": True}


def _entry_for_source(client_root: pathlib.Path, source: pathlib.Path, *, role: str, state: str = "PRESERVE_ONLY") -> dict[str, Any]:
    source = pathlib.Path(source).resolve()
    return {
        "logical_path": _safe_client_relative(client_root, source),
        "role": role,
        "state": state,
        "destination": str(source),
        "source": {"sha256": _sha256(source), "size": source.stat().st_size},
        "backup": None,
        "staged": None,
    }


def prepare_workspace_bundle(settings, resolver, registry, target: str, *, include_model: bool = True, auto_rigid_weight_repair: bool = True) -> dict[str, Any]:
    """Build a fail-closed deploy bundle from one verified generic Blender workspace.

    Preparation never writes the configured client. It snapshots every tracked
    file (model, texture and selected INX/SMB dependencies), rebuilds edited
    protected textures into their runtime container, and optionally produces a
    verified Model0.62 candidate from the saved Blender workspace.
    """
    project_root = pathlib.Path(settings.project_root).resolve()
    client_root = pathlib.Path(settings.client_root).resolve()
    build_root = (project_root / "pt_build").resolve()
    asset = registry.resolve(target)
    workspace, authoring_manifest, workspace_info, import_summary = _load_workspace(project_root, asset)

    safe_asset = asset_workspace_name(asset.primary_path)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    txid = f"{stamp}_{uuid.uuid4().hex[:10]}"
    txroot = (build_root / "deploy_bundles" / safe_asset / txid).resolve()
    txroot.mkdir(parents=True, exist_ok=False)
    manifest_path = txroot / "transaction.json"

    errors: list[str] = []
    warnings: list[str] = []
    entries_by_key: dict[str, dict[str, Any]] = {}

    source_model = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    model_entry = _entry_for_source(client_root, source_model, role="MODEL")
    entries_by_key[model_entry["logical_path"].casefold()] = model_entry

    # Context/dependency files are tracked and backed up even when they are not
    # writable through this workspace. Drift in these files blocks apply.
    for dep in authoring_manifest.get("dependencies") or []:
        p = pathlib.Path(str(dep.get("path") or "")).resolve()
        if not p.is_file() or not _inside(client_root, p):
            continue
        rel = _safe_client_relative(client_root, p)
        key = rel.casefold()
        if key not in entries_by_key:
            role = "MODEL_CONTEXT"
            if p.suffix.lower() == ".inx":
                role = "MODEL_INFO_INX"
            elif p.suffix.lower() == ".smb":
                role = "SKELETON_OR_MOTION_SMB"
            entries_by_key[key] = _entry_for_source(client_root, p, role=role)

    texture_report_path = workspace / "texture_overlay_report.json"
    texture_changes = 0
    if texture_report_path.is_file():
        texture_report = json.loads(texture_report_path.read_text(encoding="utf-8"))
        for row in texture_report.get("entries") or []:
            prepared_raw = row.get("prepared")
            physical_raw = row.get("physical")
            if not prepared_raw or not physical_raw:
                continue
            edited = pathlib.Path(str(prepared_raw)).resolve()
            source = pathlib.Path(str(physical_raw)).resolve()
            if not edited.is_file() or not source.is_file():
                continue
            if not _inside(workspace, edited):
                errors.append(f"TEXTURE_EDIT_OUTSIDE_WORKSPACE:{edited}")
                continue
            if not _inside(client_root, source):
                errors.append(f"TEXTURE_SOURCE_OUTSIDE_CLIENT:{source}")
                continue
            rel = _safe_client_relative(client_root, source)
            key = rel.casefold()
            try:
                game_bytes, build = _build_texture_game_bytes(source, edited)
            except Exception as exc:
                errors.append(f"TEXTURE_REBUILD_FAILED:{rel}:{type(exc).__name__}:{exc}")
                continue
            entry = entries_by_key.get(key) or _entry_for_source(client_root, source, role="TEXTURE")
            entry["role"] = "TEXTURE"
            entry["serialized_logical"] = str(row.get("logical") or "")
            entry["runtime_alias"] = row.get("runtime_alias")
            entry["texture_build"] = build
            if build.get("status") == "MODIFIED":
                staged = txroot / "staged" / pathlib.PurePosixPath(rel)
                _atomic_bytes(staged, game_bytes)
                entry["state"] = "MODIFIED"
                entry["staged"] = {
                    "path": str(staged), "sha256": _sha256(staged), "size": staged.stat().st_size, "verified": True
                }
                texture_changes += 1
            entries_by_key[key] = entry
    else:
        warnings.append("TEXTURE_OVERLAY_REPORT_MISSING")

    model_build = {"status": "SKIPPED", "reason": "MODEL_BUILD_DISABLED"}
    if include_model:
        model_build = _build_model_candidate(settings, resolver, asset, txroot, auto_rigid_weight_repair=auto_rigid_weight_repair)
        if model_build.get("status") == "MODIFIED":
            candidate = pathlib.Path(str(model_build["candidate"])).resolve()
            staged = txroot / "staged" / pathlib.PurePosixPath(asset.primary_path)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, staged)
            if _sha256(staged) != str(model_build.get("candidate_sha256")):
                errors.append("MODEL_STAGED_COPY_VERIFICATION_FAILED")
            else:
                model_entry["state"] = "MODIFIED"
                model_entry["staged"] = {
                    "path": str(staged), "sha256": _sha256(staged), "size": staged.stat().st_size, "verified": True
                }
                model_entry["model_build"] = model_build
        elif model_build.get("status") in {"FAIL", "BLOCKED"}:
            errors.extend(str(x) for x in (model_build.get("blockers") or ["MODEL_BUILD_BLOCKED"]))
        else:
            model_entry["model_build"] = model_build
        if model_build.get("status") == "MODIFIED" and model_build.get("kind") == "RIGID":
            if model_build.get("runtime_lod_coverage_complete") is False:
                warnings.append(
                    "RUNTIME_LOD_WRITER_COVERAGE_INCOMPLETE:"
                    f"changed={model_build.get('changed_lods') or []}:"
                    f"uncovered={model_build.get('uncovered_lods') or []}"
                )
            if model_build.get("unmodified_lods"):
                warnings.append(
                    "RUNTIME_LODS_UNMODIFIED:" + ",".join(str(x) for x in model_build.get("unmodified_lods") or [])
                )
            if int(model_build.get("blender_weight_repair_count") or 0) > 0:
                warnings.append(
                    "AUTO_RIGID_WEIGHT_REPAIR:"
                    f"count={int(model_build.get('blender_weight_repair_count') or 0)}:"
                    f"strategies={model_build.get('blender_weight_repair_strategy_counts') or {}}:"
                    "source correspondence is preferred, then unique highest Blender weight, then deterministic tie-break; "
                    "each repaired vertex is serialized at weight 1.0; use --no-auto-rigid-weight-repair to block instead"
                )
            elif int(model_build.get("blender_weight_mismatch_count") or 0) > 0:
                warnings.append(
                    "BLENDER_PHYSIQUE_PROBE_MISMATCH:"
                    f"objects={model_build.get('physique_preserve_objects') or []}:"
                    f"vertex_mismatches={int(model_build.get('blender_weight_mismatch_count') or 0)}"
                )

    entries = sorted(entries_by_key.values(), key=lambda x: (str(x.get("role")), str(x.get("logical_path")).casefold()))

    # Snapshot the entire bundle before any future apply. This includes
    # preserve-only INX/SMB context, so restore/history has a complete session.
    for entry in entries:
        src = pathlib.Path(str(entry["destination"])).resolve()
        backup = txroot / "backup" / pathlib.PurePosixPath(str(entry["logical_path"]))
        try:
            entry["backup"] = _copy_verified(src, backup)
        except Exception as exc:
            errors.append(f"BACKUP_FAILED:{entry['logical_path']}:{type(exc).__name__}:{exc}")

    changed = [x for x in entries if x.get("state") == "MODIFIED"]
    texture_changed = [x for x in changed if x.get("role") == "TEXTURE"]
    model_changed = [x for x in changed if x.get("role") == "MODEL"]
    status = "READY" if changed and not errors else ("NO_CHANGES" if not changed and not errors else "BLOCKED")
    payload: dict[str, Any] = {
        "format": FORMAT,
        "status": status,
        "state": "PREPARED" if status == "READY" else status,
        "transaction_id": txid,
        "generated_at": time.time(),
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "family": asset.family,
        "kind": asset.kind,
        "project_root": str(project_root),
        "client_root": str(client_root),
        "workspace": str(workspace),
        "workspace_manifest": str(workspace / "authoring_manifest.json"),
        "workspace_info": workspace_info,
        "import_summary": {
            "mode": import_summary.get("mode"), "lod": import_summary.get("lod"),
            "selected_context": import_summary.get("selected_context"),
        },
        "transaction_root": str(txroot),
        "entries": entries,
        "model_build": model_build,
        "summary": {
            "tracked_file_count": len(entries),
            "changed_file_count": len(changed),
            "changed_model_count": len(model_changed),
            "changed_texture_count": len(texture_changed),
            "preserve_only_count": len(entries) - len(changed),
            "texture_overlay_changed_count": texture_changes,
            "changed_model_objects": list(model_build.get("target_objects") or ([model_build.get("target_object")] if model_build.get("target_object") else [])),
            "changed_model_lods": list(model_build.get("changed_lods") or []),
            "unmodified_model_lods": list(model_build.get("unmodified_lods") or []),
            "uncovered_model_lods": list(model_build.get("uncovered_lods") or []),
            "runtime_lod_coverage_complete": model_build.get("runtime_lod_coverage_complete"),
            "blender_weight_mismatch_count": int(model_build.get("blender_weight_mismatch_count") or 0),
            "blender_weight_repair_count": int(model_build.get("blender_weight_repair_count") or 0),
            "blender_weight_repair_strategy_counts": dict(model_build.get("blender_weight_repair_strategy_counts") or {}),
            "auto_rigid_weight_repair_enabled": bool(model_build.get("auto_rigid_weight_repair_enabled", auto_rigid_weight_repair)),
            "physique_preserve_objects": list(model_build.get("physique_preserve_objects") or []),
        },
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "policy": {
            "explicit_client_deploy_arm_required": True,
            "create_or_replace_only_known_tracked_paths": True,
            "prewrite_full_bundle_drift_gate": True,
            "verified_backup_required_for_every_tracked_file": True,
            "atomic_replace": True,
            "rollback_all_written_files_on_any_failure": True,
            "postwrite_hash_verification": True,
            "candidate_model_requires_candidate_verification_pass": True,
            "rigid_publish_requires_complete_runtime_lod_writer_coverage_by_default": True,
            "rigid_weight_policy": "AUTO_REPAIR" if auto_rigid_weight_repair else "STRICT",
            "auto_rigid_weight_repair_is_deterministic": True,
            "auto_rigid_weight_repair_can_be_disabled": True,
            "preserve_only_context_never_written": True,
        },
        "client_write_authorized": False,
        "client_modified": False,
        "rollback_performed": False,
        "events": [{"event": "PREPARED", "at": time.time(), "status": status}],
    }
    _atomic_json(manifest_path, payload)
    payload["manifest"] = str(manifest_path)
    return payload


def _load_transaction(manifest_path: str | pathlib.Path) -> tuple[pathlib.Path, dict[str, Any]]:
    p = pathlib.Path(manifest_path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise RuntimeError(f"workspace bundle transaction format mismatch: {data.get('format')}")
    txroot = pathlib.Path(str(data.get("transaction_root") or p.parent)).resolve()
    project_root = pathlib.Path(str(data.get("project_root") or "")).resolve()
    if not _inside(project_root / "pt_build", txroot) or not _inside(txroot, p):
        raise RuntimeError("workspace bundle manifest is not contained by pt_build transaction root")
    return p, data


def verify_workspace_bundle_transaction(manifest_path: str | pathlib.Path, *, allow_managed: bool = False) -> dict[str, Any]:
    p, data = _load_transaction(manifest_path)
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    client_root = pathlib.Path(str(data.get("client_root") or "")).resolve()
    txroot = pathlib.Path(str(data.get("transaction_root") or p.parent)).resolve()
    for entry in data.get("entries") or []:
        dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
        logical = str(entry.get("logical_path") or "")
        if not _inside(client_root, dest):
            errors.append(f"DESTINATION_OUTSIDE_CLIENT:{logical}")
            continue
        source = entry.get("source") or {}
        staged = entry.get("staged") or {}
        backup = entry.get("backup") or {}
        source_match = bool(dest.is_file() and dest.stat().st_size == int(source.get("size") or -1) and _sha256(dest) == str(source.get("sha256") or ""))
        managed_match = bool(
            entry.get("state") == "MODIFIED" and staged and dest.is_file()
            and dest.stat().st_size == int(staged.get("size") or -1)
            and _sha256(dest) == str(staged.get("sha256") or "")
        )
        if not source_match and not (allow_managed and managed_match):
            errors.append(f"CLIENT_DRIFT:{logical}")
        bp = pathlib.Path(str(backup.get("path") or "")).resolve()
        backup_ready = bool(
            bp.is_file() and _inside(txroot, bp)
            and bp.stat().st_size == int(source.get("size") or -1)
            and _sha256(bp) == str(source.get("sha256") or "")
        )
        if not backup_ready:
            errors.append(f"BACKUP_DRIFT:{logical}")
        staged_ready = True
        if entry.get("state") == "MODIFIED":
            sp = pathlib.Path(str(staged.get("path") or "")).resolve()
            staged_ready = bool(
                sp.is_file() and _inside(txroot, sp)
                and sp.stat().st_size == int(staged.get("size") or -1)
                and _sha256(sp) == str(staged.get("sha256") or "")
            )
            if not staged_ready:
                errors.append(f"STAGED_DRIFT:{logical}")
        rows.append({
            "logical_path": logical, "state": entry.get("state"),
            "source_match": source_match, "managed_match": managed_match,
            "backup_ready": backup_ready, "staged_ready": staged_ready,
        })
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_VERIFY_V1",
        "status": "PASS" if not errors else "FAIL",
        "manifest": str(p),
        "transaction_id": data.get("transaction_id"),
        "errors": sorted(set(errors)),
        "entries": rows,
        "allow_managed": bool(allow_managed),
        "client_modified": False,
    }


def _post_validate_model(data: dict[str, Any]) -> dict[str, Any]:
    model_build = data.get("model_build") or {}
    if model_build.get("status") != "MODIFIED":
        return {"status": "SKIP", "reason": "MODEL_NOT_MODIFIED"}
    model_entry = next((x for x in data.get("entries") or [] if x.get("role") == "MODEL"), None)
    if not model_entry:
        return {"status": "FAIL", "errors": ["MODEL_ENTRY_MISSING"]}
    original = pathlib.Path(str((model_entry.get("backup") or {}).get("path") or "")).resolve()
    deployed = pathlib.Path(str(model_entry.get("destination") or "")).resolve()
    kind = str(model_build.get("kind") or "")
    try:
        if kind == "STATIC":
            return validate_static_candidate_output(original, deployed, str(model_build.get("target_object") or ""))
        if kind == "RIGID":
            targets = list(model_build.get("target_objects") or [])
            if not targets and model_build.get("target_object"):
                targets = [str(model_build.get("target_object"))]
            if not targets:
                return {"status": "FAIL", "errors": ["POST_MODEL_TARGETS_MISSING"]}
            return validate_rigid_profile_stress_output(
                pathlib.Path(str(data.get("project_root") or "")).resolve(),
                original,
                deployed,
                pathlib.Path(str(model_build.get("skeleton") or "")).resolve(),
                targets,
            )
    except Exception as exc:
        return {"status": "FAIL", "errors": [f"POST_MODEL_VALIDATOR_EXCEPTION:{type(exc).__name__}:{exc}"]}
    return {"status": "FAIL", "errors": [f"POST_MODEL_VALIDATOR_UNSUPPORTED:{kind}"]}


def _rollback_entries(entries: list[dict[str, Any]], written: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for entry in reversed(written):
        logical = str(entry.get("logical_path") or "")
        backup = pathlib.Path(str((entry.get("backup") or {}).get("path") or "")).resolve()
        dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
        try:
            _atomic_replace_from(backup, dest)
            src = entry.get("source") or {}
            if dest.stat().st_size != int(src.get("size") or -1) or _sha256(dest) != str(src.get("sha256") or ""):
                raise RuntimeError("rollback postwrite identity mismatch")
        except Exception as exc:
            errors.append(f"ROLLBACK_FAILED:{logical}:{type(exc).__name__}:{exc}")
    return not errors, errors


def apply_workspace_bundle_transaction(manifest_path: str | pathlib.Path, *, confirm: str) -> dict[str, Any]:
    if str(confirm) != APPLY_CONFIRMATION:
        raise RuntimeError(f"client bundle apply requires exact confirmation: {APPLY_CONFIRMATION}")
    p, data = _load_transaction(manifest_path)
    if data.get("status") not in {"READY", "APPLIED_VERIFIED"} and data.get("state") not in {"PREPARED", "APPLIED_VERIFIED"}:
        raise RuntimeError(f"workspace bundle is not apply-ready: status={data.get('status')} state={data.get('state')}")
    if data.get("state") == "APPLIED_VERIFIED":
        raise RuntimeError("workspace bundle is already applied")
    verify = verify_workspace_bundle_transaction(p)
    if verify.get("status") != "PASS":
        raise RuntimeError(f"workspace bundle prewrite verification failed: {verify.get('errors')}")

    entries = list(data.get("entries") or [])
    changed = [x for x in entries if x.get("state") == "MODIFIED"]
    if not changed:
        raise RuntimeError("workspace bundle contains no modified files")
    written: list[dict[str, Any]] = []
    errors: list[str] = []
    rollback_performed = False
    rollback_pass = False
    try:
        for entry in changed:
            logical = str(entry.get("logical_path") or "")
            staged = pathlib.Path(str((entry.get("staged") or {}).get("path") or "")).resolve()
            dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
            _atomic_replace_from(staged, dest)
            expected = entry.get("staged") or {}
            if dest.stat().st_size != int(expected.get("size") or -1) or _sha256(dest) != str(expected.get("sha256") or ""):
                raise RuntimeError(f"postwrite hash mismatch: {logical}")
            written.append(entry)

        model_validation = _post_validate_model(data)
        if model_validation.get("status") == "FAIL":
            raise RuntimeError(f"post-write model validation failed: {model_validation.get('errors')}")
        data["post_model_validation"] = model_validation
    except Exception as exc:
        errors.append(f"{type(exc).__name__}:{exc}")
        if written:
            rollback_performed = True
            rollback_pass, rollback_errors = _rollback_entries(entries, written)
            errors.extend(rollback_errors)
        data["rollback_performed"] = rollback_performed
        data["rollback_pass"] = rollback_pass
        data["status"] = "FAIL"
        data["state"] = "ROLLED_BACK" if rollback_performed and rollback_pass else "APPLY_FAILED"
        data["client_modified"] = bool(written and not rollback_pass)
        data.setdefault("events", []).append({"event": data["state"], "at": time.time(), "errors": errors})
        _atomic_json(p, data)
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_APPLY_V1",
            "status": "FAIL",
            "state": data["state"],
            "manifest": str(p),
            "written_file_count": len(written),
            "rollback_performed": rollback_performed,
            "rollback_pass": rollback_pass,
            "errors": errors,
            "client_modified": data["client_modified"],
        }

    data["status"] = "APPLIED_VERIFIED"
    data["state"] = "APPLIED_VERIFIED"
    data["client_write_authorized"] = True
    data["client_modified"] = True
    data["applied_at"] = time.time()
    data["written_file_count"] = len(written)
    data["rollback_performed"] = False
    data.setdefault("events", []).append({"event": "APPLIED_VERIFIED", "at": time.time(), "written_file_count": len(written)})
    _atomic_json(p, data)
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_APPLY_V1",
        "status": "PASS",
        "state": "APPLIED_VERIFIED",
        "manifest": str(p),
        "asset": data.get("asset"),
        "written_file_count": len(written),
        "written_files": [x.get("logical_path") for x in written],
        "post_model_validation": data.get("post_model_validation"),
        "rollback_performed": False,
        "client_modified": True,
    }


def workspace_bundle_status(manifest_path: str | pathlib.Path) -> dict[str, Any]:
    p, data = _load_transaction(manifest_path)
    verify = verify_workspace_bundle_transaction(p, allow_managed=True)
    states: list[dict[str, Any]] = []
    for row in verify.get("entries") or []:
        if row.get("source_match"):
            state = "ORIGINAL"
        elif row.get("managed_match"):
            state = "DEPLOYED"
        else:
            state = "DRIFT"
        states.append({"logical_path": row.get("logical_path"), "state": state})
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_STATE_V1",
        "status": "PASS" if verify.get("status") == "PASS" else "BLOCKED",
        "manifest": str(p),
        "transaction_id": data.get("transaction_id"),
        "asset": data.get("asset"),
        "transaction_state": data.get("state"),
        "entries": states,
        "drift_count": sum(1 for x in states if x["state"] == "DRIFT"),
        "deployed_count": sum(1 for x in states if x["state"] == "DEPLOYED"),
        "original_count": sum(1 for x in states if x["state"] == "ORIGINAL"),
        "client_modified": False,
    }


def _restore_workspace_bundle_entries(
    manifest_path: str | pathlib.Path,
    *,
    confirm: str,
    roles: set[str] | None = None,
    operation: str = "BUNDLE",
) -> dict[str, Any]:
    if str(confirm) != RESTORE_CONFIRMATION:
        raise RuntimeError(f"client bundle restore requires exact confirmation: {RESTORE_CONFIRMATION}")
    p, data = _load_transaction(manifest_path)
    if data.get("state") not in ACTIVE_DEPLOY_STATES:
        raise RuntimeError(
            f"restore requires an active deployed transaction, got {data.get('state')}"
        )
    status = workspace_bundle_status(p)
    if status.get("status") != "PASS" or status.get("drift_count"):
        raise RuntimeError("restore refuses unknown client drift")

    current_state = {
        str(row.get("logical_path") or "").casefold(): str(row.get("state") or "")
        for row in (status.get("entries") or [])
    }
    changed = [x for x in data.get("entries") or [] if x.get("state") == "MODIFIED"]
    if roles is not None:
        wanted = {str(x).upper() for x in roles}
        changed = [x for x in changed if str(x.get("role") or "").upper() in wanted]
    if not changed:
        role_text = ",".join(sorted(roles or set())) or "ANY"
        raise RuntimeError(f"no modified entries are available for restore role={role_text}")

    deployed: list[dict[str, Any]] = []
    already_original: list[str] = []
    for entry in changed:
        logical = str(entry.get("logical_path") or "")
        state = current_state.get(logical.casefold(), "DRIFT")
        if state == "ORIGINAL":
            already_original.append(logical)
            continue
        if state != "DEPLOYED":
            raise RuntimeError(f"restore refuses unknown client drift: {logical}:{state}")
        dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
        staged = entry.get("staged") or {}
        if (
            not dest.is_file()
            or dest.stat().st_size != int(staged.get("size") or -1)
            or _sha256(dest) != str(staged.get("sha256") or "")
        ):
            raise RuntimeError(f"restore refuses destination not equal to managed artifact: {logical}")
        deployed.append(entry)

    restored: list[str] = []
    errors: list[str] = []
    try:
        for entry in deployed:
            backup = pathlib.Path(str((entry.get("backup") or {}).get("path") or "")).resolve()
            dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
            _atomic_replace_from(backup, dest)
            original = entry.get("source") or {}
            if (
                dest.stat().st_size != int(original.get("size") or -1)
                or _sha256(dest) != str(original.get("sha256") or "")
            ):
                raise RuntimeError(f"restore postwrite verification failed: {entry.get('logical_path')}")
            restored.append(str(entry.get("logical_path") or ""))
    except Exception as exc:
        errors.append(f"{type(exc).__name__}:{exc}")
        # Fail closed: return entries restored by this operation to the managed
        # artifact identity that existed immediately before the manual restore.
        reapply_errors: list[str] = []
        for entry in deployed:
            if str(entry.get("logical_path") or "") not in restored:
                continue
            try:
                staged = pathlib.Path(str((entry.get("staged") or {}).get("path") or "")).resolve()
                dest = pathlib.Path(str(entry.get("destination") or "")).resolve()
                _atomic_replace_from(staged, dest)
                expected = entry.get("staged") or {}
                if (
                    dest.stat().st_size != int(expected.get("size") or -1)
                    or _sha256(dest) != str(expected.get("sha256") or "")
                ):
                    raise RuntimeError("restore reapply postwrite identity mismatch")
            except Exception as rex:
                reapply_errors.append(
                    f"RESTORE_REAPPLY_FAILED:{entry.get('logical_path')}:{type(rex).__name__}:{rex}"
                )
        errors.extend(reapply_errors)
        data.setdefault("events", []).append({
            "event": f"{operation}_RESTORE_FAILED",
            "at": time.time(),
            "errors": errors,
        })
        _atomic_json(p, data)
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_RESTORE_V2",
            "status": "FAIL",
            "state": "RESTORE_FAILED",
            "operation": operation,
            "manifest": str(p),
            "errors": errors,
            "client_modified": True,
        }

    final_status = workspace_bundle_status(p)
    remaining_deployed = int(final_status.get("deployed_count") or 0)
    if remaining_deployed:
        new_state = "PARTIALLY_RESTORED_VERIFIED"
        data["client_modified"] = True
        data["partial_restore_at"] = time.time()
    else:
        new_state = "RESTORED_VERIFIED"
        data["client_modified"] = False
        data["restored_at"] = time.time()
    data["status"] = new_state
    data["state"] = new_state
    data.setdefault("events", []).append({
        "event": f"{operation}_RESTORED_VERIFIED",
        "at": time.time(),
        "restored_file_count": len(restored),
        "already_original_count": len(already_original),
        "remaining_deployed_count": remaining_deployed,
    })
    _atomic_json(p, data)
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_RESTORE_V2",
        "status": "PASS",
        "state": new_state,
        "operation": operation,
        "manifest": str(p),
        "asset": data.get("asset"),
        "restored_file_count": len(restored),
        "restored_files": restored,
        "already_original_files": already_original,
        "remaining_deployed_count": remaining_deployed,
        "client_modified": bool(remaining_deployed),
    }


def restore_workspace_bundle_transaction(manifest_path: str | pathlib.Path, *, confirm: str) -> dict[str, Any]:
    """Restore all still-deployed entries from one verified workspace bundle.

    A previous model-only restore is accepted: entries that are already back at
    their original identity are skipped and the remaining managed entries are
    restored atomically/fail-closed.
    """
    return _restore_workspace_bundle_entries(
        manifest_path, confirm=confirm, roles=None, operation="BUNDLE"
    )


def restore_workspace_bundle_model_transaction(manifest_path: str | pathlib.Path, *, confirm: str) -> dict[str, Any]:
    """Restore only MODEL entries from an active verified bundle.

    This is the manual "retirar modelo" path used by the UI. Texture entries
    remain deployed. Unknown drift is refused and a failed partial restore is
    rolled back to the managed artifact bytes that existed before the request.
    """
    return _restore_workspace_bundle_entries(
        manifest_path, confirm=confirm, roles={"MODEL"}, operation="MODEL_ONLY"
    )


def bundle_history(project_root: pathlib.Path, target: str) -> dict[str, Any]:
    project_root = pathlib.Path(project_root).resolve()
    root = project_root / "pt_build" / "deploy_bundles" / asset_workspace_name(target)
    rows: list[dict[str, Any]] = []
    if root.is_dir():
        for manifest in sorted(root.glob("*/transaction.json"), reverse=True):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("format") != FORMAT:
                continue
            rows.append({
                "transaction_id": data.get("transaction_id"),
                "asset": data.get("asset"),
                "state": data.get("state"),
                "status": data.get("status"),
                "generated_at": data.get("generated_at"),
                "applied_at": data.get("applied_at"),
                "restored_at": data.get("restored_at"),
                "summary": data.get("summary"),
                "manifest": str(manifest.resolve()),
            })
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_HISTORY_V1",
        "status": "PASS",
        "asset": str(target).replace("\\", "/"),
        "count": len(rows),
        "transactions": rows,
        "client_modified": False,
    }


def latest_applied_bundle_manifest(project_root: pathlib.Path, target: str) -> pathlib.Path | None:
    """Return the newest transaction that still has managed bytes in client.

    PARTIALLY_RESTORED_VERIFIED remains active because a model-only rollback
    may intentionally leave textures deployed.
    """
    history = bundle_history(project_root, target)
    for row in history.get("transactions") or []:
        if row.get("state") in ACTIVE_DEPLOY_STATES:
            return pathlib.Path(str(row["manifest"])).resolve()
    return None


def workspace_bundle_restore_capabilities(project_root: pathlib.Path, target: str) -> dict[str, Any]:
    manifest = latest_applied_bundle_manifest(project_root, target)
    if manifest is None:
        return {
            "status": "NO_ACTIVE_BUNDLE", "manifest": None,
            "can_restore_bundle": False, "can_restore_model": False,
            "deployed_count": 0, "deployed_model_count": 0,
            "deployed_texture_count": 0, "drift_count": 0,
        }
    _p, data = _load_transaction(manifest)
    state = workspace_bundle_status(manifest)
    by_path = {
        str(row.get("logical_path") or "").casefold(): str(row.get("state") or "")
        for row in (state.get("entries") or [])
    }
    deployed_entries = [
        entry for entry in (data.get("entries") or [])
        if entry.get("state") == "MODIFIED"
        and by_path.get(str(entry.get("logical_path") or "").casefold()) == "DEPLOYED"
    ]
    model = [x for x in deployed_entries if str(x.get("role") or "").upper() == "MODEL"]
    textures = [x for x in deployed_entries if str(x.get("role") or "").upper() == "TEXTURE"]
    clean = state.get("status") == "PASS" and not int(state.get("drift_count") or 0)
    return {
        "status": "PASS" if clean else "BLOCKED",
        "manifest": str(manifest),
        "transaction_state": data.get("state"),
        "can_restore_bundle": bool(clean and deployed_entries),
        "can_restore_model": bool(clean and model),
        "deployed_count": len(deployed_entries),
        "deployed_model_count": len(model),
        "deployed_texture_count": len(textures),
        "drift_count": int(state.get("drift_count") or 0),
        "deployed_files": [str(x.get("logical_path") or "") for x in deployed_entries],
    }


def publish_workspace_bundle(
    settings, resolver, registry, target: str, *, confirm: str, include_model: bool = True,
    allow_partial_lod: bool = False, auto_rigid_weight_repair: bool = True,
) -> dict[str, Any]:
    prepared = prepare_workspace_bundle(
        settings, resolver, registry, target, include_model=include_model,
        auto_rigid_weight_repair=auto_rigid_weight_repair,
    )
    if prepared.get("status") == "NO_CHANGES":
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_PUBLISH_V1",
            "status": "PASS",
            "state": "NO_CHANGES",
            "asset": prepared.get("asset"),
            "manifest": prepared.get("manifest"),
            "summary": prepared.get("summary"),
            "client_modified": False,
        }
    model_build = dict(prepared.get("model_build") or {})
    if (
        include_model
        and model_build.get("status") == "MODIFIED"
        and model_build.get("kind") == "RIGID"
        and model_build.get("runtime_lod_coverage_complete") is False
        and not allow_partial_lod
    ):
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_PUBLISH_V1",
            "status": "FAIL",
            "state": "RUNTIME_LOD_COVERAGE_INCOMPLETE",
            "asset": prepared.get("asset"),
            "manifest": prepared.get("manifest"),
            "summary": prepared.get("summary"),
            "errors": [
                "MODEL_WRITER_DOES_NOT_COVER_ALL_RUNTIME_LODS; "
                f"changed_lods={model_build.get('changed_lods') or []}; "
                f"uncovered_lods={model_build.get('uncovered_lods') or []}; "
                "the uncovered LOD cannot be safely serialized; pass --allow-partial-lod only to preserve it unchanged intentionally"
            ],
            "model_build": model_build,
            "client_modified": False,
        }
    if prepared.get("status") != "READY":
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_PUBLISH_V1",
            "status": "FAIL",
            "state": "PREPARE_BLOCKED",
            "asset": prepared.get("asset"),
            "manifest": prepared.get("manifest"),
            "summary": prepared.get("summary"),
            "errors": prepared.get("errors"),
            "model_build": prepared.get("model_build"),
            "client_modified": False,
        }
    applied = apply_workspace_bundle_transaction(str(prepared["manifest"]), confirm=confirm)
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_PUBLISH_V1",
        "status": applied.get("status"),
        "state": applied.get("state"),
        "asset": prepared.get("asset"),
        "manifest": prepared.get("manifest"),
        "summary": prepared.get("summary"),
        "prepared": {"status": prepared.get("status"), "model_build": prepared.get("model_build")},
        "apply": applied,
        "client_modified": bool(applied.get("client_modified")),
    }


def check_latest_workspace_bundle(project_root: pathlib.Path, target: str) -> dict[str, Any]:
    """Re-check only the latest deployed bundle for one asset; never scans the corpus."""
    manifest = latest_applied_bundle_manifest(project_root, target)
    if manifest is None:
        return {
            "format": "PT_ASSET_WORKSPACE_BUNDLE_FOCUSED_CHECK_V1",
            "status": "FAIL",
            "asset": str(target).replace("\\", "/"),
            "errors": ["NO_APPLIED_VERIFIED_BUNDLE"],
            "client_modified": False,
        }
    _p, data = _load_transaction(manifest)
    state = workspace_bundle_status(manifest)
    drift = [row for row in (state.get("entries") or []) if row.get("state") == "DRIFT"]
    model_validation = _post_validate_model(data)
    errors: list[str] = []
    if state.get("status") != "PASS" or drift:
        errors.append("DEPLOYED_BUNDLE_DRIFT")
    if model_validation.get("status") not in {"PASS", "SKIP"}:
        errors.append("DEPLOYED_MODEL_VALIDATION_FAILED")
    modified = [str(x.get("logical_path")) for x in (data.get("entries") or []) if x.get("state") == "MODIFIED"]
    return {
        "format": "PT_ASSET_WORKSPACE_BUNDLE_FOCUSED_CHECK_V1",
        "status": "PASS" if not errors else "FAIL",
        "asset": data.get("asset"),
        "transaction_id": data.get("transaction_id"),
        "manifest": str(manifest),
        "modified_files": modified,
        "modified_file_count": len(modified),
        "bundle_state": state,
        "model_validation": model_validation,
        "model_build": data.get("model_build"),
        "errors": errors,
        "scope": "LATEST_DEPLOYED_BUNDLE_ONLY",
        "client_modified": False,
    }


def restore_latest_workspace_bundle(project_root: pathlib.Path, target: str, *, confirm: str) -> dict[str, Any]:
    manifest = latest_applied_bundle_manifest(project_root, target)
    if manifest is None:
        raise RuntimeError(f"no active verified bundle exists for {target}")
    return restore_workspace_bundle_transaction(manifest, confirm=confirm)


def restore_latest_workspace_model(project_root: pathlib.Path, target: str, *, confirm: str) -> dict[str, Any]:
    manifest = latest_applied_bundle_manifest(project_root, target)
    if manifest is None:
        raise RuntimeError(f"no active verified bundle exists for {target}")
    return restore_workspace_bundle_model_transaction(manifest, confirm=confirm)
