from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from typing import Any

from .motion_core import _smb_track_key_counts, load_smb_evaluator, write_payload
from .release_1_coverage import content_domain
from .standalone_rigid_devtest import explicit_skeleton_candidate, standalone_rigid_context_eligible
from .utils import run_logged
from .validation import ValidationContext, ValidationRunner

FORMAT = "PT_PLAYER_SCALE_WITNESS_V1"
MAX_FRAMES_PER_CONTAINER = 120


def _norm(value: str | None) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sample_logical_frames(start: int, end: int, *, limit: int = MAX_FRAMES_PER_CONTAINER) -> tuple[int, int, list[int]]:
    logical_start = int(start) // 160
    logical_end = int(end) // 160
    frames = list(range(logical_start, logical_end))
    if not frames:
        frames = [logical_start]
    limit = max(1, int(limit))
    if len(frames) > limit:
        last = len(frames) - 1
        idxs = sorted({round(i * last / (limit - 1)) for i in range(limit)}) if limit > 1 else [0]
        frames = [frames[i] for i in idxs]
    return logical_start, logical_end, frames


def scan_scale_containers(
    root: pathlib.Path,
    smb_path: pathlib.Path,
    *,
    max_frames_per_container: int = MAX_FRAMES_PER_CONTAINER,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit every active TmFrame container without suppressing evaluator failures.

    A scale witness container is eligible only when every deterministically sampled
    frame evaluates successfully and at least one sampled frame activates scale.
    Failed containers remain in diagnostics and can never be selected.
    """
    root = pathlib.Path(root).resolve()
    smb_path = pathlib.Path(smb_path).resolve()
    evaluator = load_smb_evaluator(root)
    smb = evaluator.parse_smb(smb_path)
    active = [
        dict(row)
        for row in (smb.get("header_frames") or [])
        if int(row.get("end") or 0) > int(row.get("start") or 0)
    ]
    rows: list[dict[str, Any]] = []
    for container in active:
        slot = int(container.get("slot") or 0)
        start = int(container["start"])
        end = int(container["end"])
        logical_start, logical_end, frames = _sample_logical_frames(
            start, end, limit=int(max_frames_per_container)
        )
        failures: list[dict[str, Any]] = []
        active_scale_samples = 0
        active_scale_total = 0
        for logical in frames:
            engine = int(logical) * 160
            try:
                _results, _a, _b, stats = evaluator.evaluate_pose(smb, engine, end)
                n = int((stats or {}).get("active_scale") or 0)
                active_scale_total += n
                if n > 0:
                    active_scale_samples += 1
            except Exception as exc:
                failures.append({
                    "logical_frame": int(logical),
                    "engine_frame": engine,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        rows.append({
            "slot": slot,
            "start": start,
            "end": end,
            "logical_start": logical_start,
            "logical_end": logical_end,
            "sample_count": len(frames),
            "failure_count": len(failures),
            "failure_sample": failures[:8],
            "active_scale_samples": active_scale_samples,
            "active_scale_total": active_scale_total,
            "eligible_scale_container": bool(not failures and active_scale_samples > 0),
        })
    return smb, rows


def build_scale_container_bake_payload(
    root: pathlib.Path,
    smb_path: pathlib.Path,
    *,
    container: dict[str, Any],
    fps: int = 30,
    max_frames_per_container: int = MAX_FRAMES_PER_CONTAINER,
) -> dict[str, Any]:
    """Build one complete sampled scale-bearing TmFrame action for Blender.

    This is intentionally not a generic recovery path. The chosen container must
    have zero evaluator failures under the same bounded sampling policy and must
    activate scale on at least one sampled frame.
    """
    root = pathlib.Path(root).resolve()
    smb_path = pathlib.Path(smb_path).resolve()
    evaluator = load_smb_evaluator(root)
    smb = evaluator.parse_smb(smb_path)
    slot = int(container.get("slot") or 0)
    start = int(container["start"])
    end = int(container["end"])
    logical_start, logical_end, logical_frames = _sample_logical_frames(
        start, end, limit=int(max_frames_per_container)
    )
    frames: list[dict[str, Any]] = []
    active_scale_samples = 0
    for scene_frame, logical in enumerate(logical_frames, start=1):
        engine = int(logical) * 160
        matrices, _a, _b, stats = evaluator.evaluate_pose(smb, engine, end)
        if int((stats or {}).get("active_scale") or 0) > 0:
            active_scale_samples += 1
        frames.append({
            "frame": scene_frame,
            "engine_frame": engine,
            "matrices": matrices,
        })
    if active_scale_samples <= 0:
        raise RuntimeError(f"SMB slot {slot} produced no active scale sample")

    action_name = f"PT_SMB_SLOT_{slot:02d}"
    action = {
        "name": action_name,
        "index": slot,
        "state": 0,
        "state_name": f"SMB_SLOT_{slot:02d}",
        "repeat": 0,
        "motion_frame": slot + 1,
        "global_start": logical_start,
        "global_end": logical_end,
        "engine_start": start,
        "engine_end": end,
        "frame_count": len(frames),
        "frames": frames,
        "source_pose_reference": "GLOBAL_BIND",
        "pose_guard": "NONE",
        "pose_guard_bones": [],
    }
    bones = [
        {"name": b["name"], "parent": b["parent_name"], "bind_tm": b["tm"]}
        for b in smb["bones"]
    ]
    return {
        "format": "PT_ASSET_MOTION_BAKE_V1",
        "source_mode": "STANDALONE_SMB_TMFRAME_SCALE_WITNESS",
        "inx": "",
        "smb": str(smb_path),
        "fps": int(fps),
        "selected_action": action_name,
        "selected_motion_index": slot,
        "load_actions": "single_scale_container",
        "motion_count": 1,
        "active_motion_count": 1,
        "actions": [action],
        "bones": bones,
        "tm_sort": list(smb["tm_sort"]),
        "quaternion_null_semantics": "IDENTITY",
        "source_pose_reference_policy": "GLOBAL_BIND",
        "pose_guard_policy": "NONE",
        "track_key_counts": _smb_track_key_counts(smb),
        "scale_witness": {
            "slot": slot,
            "sample_count": len(frames),
            "active_scale_sample_count": active_scale_samples,
            "all_sampled_frames_evaluable": True,
        },
        "client_modified": False,
    }


def _candidate_rows(registry, resolver, *, domain: str = "PLAYER") -> list[dict[str, Any]]:
    root = pathlib.Path(__file__).resolve().parents[1]
    evaluator = load_smb_evaluator(root)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for asset in registry.assets:
        if content_domain(asset) != str(domain):
            continue
        if not standalone_rigid_context_eligible(asset):
            continue
        try:
            probe = explicit_skeleton_candidate(registry, asset)
            if not probe.get("candidate_available"):
                continue
            logical = _norm(probe.get("candidate_smb"))
            if not logical:
                continue
            key = (str(asset.primary_path).casefold(), logical.casefold())
            if key in seen:
                continue
            seen.add(key)
            physical = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            smb = evaluator.parse_smb(physical)
            scale = sum(len(b.get("scale") or []) for b in (smb.get("bones") or []))
            if scale <= 0:
                continue
            rows.append({
                "asset_id": asset.asset_id,
                "asset": asset.primary_path,
                "domain": str(domain),
                "skeleton_smb": logical,
                "candidate_basis": probe.get("candidate_basis"),
                "scale_key_count": int(scale),
            })
        except Exception:
            continue
    rows.sort(key=lambda r: (-int(r["scale_key_count"]), str(r["asset"]).casefold()))
    return rows


def choose_player_scale_witness(registry, resolver) -> dict[str, Any]:
    """Select a deterministic PLAYER scale witness without hiding bad containers."""
    root = pathlib.Path(__file__).resolve().parents[1]
    candidates = _candidate_rows(registry, resolver, domain="PLAYER")
    diagnostics: list[dict[str, Any]] = []
    seen_smb: set[str] = set()
    for row in candidates:
        logical = _norm(row["skeleton_smb"])
        key = logical.casefold()
        if key in seen_smb:
            continue
        seen_smb.add(key)
        try:
            physical = pathlib.Path(resolver.resolve(logical, required=True)).resolve()
            _smb, scans = scan_scale_containers(root, physical)
        except Exception as exc:
            diagnostics.append({
                "skeleton_smb": logical,
                "error": f"{type(exc).__name__}: {exc}",
                "containers": [],
            })
            continue
        diagnostics.append({"skeleton_smb": logical, "containers": scans})
        eligible = [x for x in scans if bool(x.get("eligible_scale_container"))]
        if not eligible:
            continue
        eligible.sort(key=lambda x: (-int(x.get("active_scale_samples") or 0), int(x.get("slot") or 0)))
        chosen = dict(row)
        chosen["selected_container"] = dict(eligible[0])
        chosen["container_scan"] = scans
        chosen["candidate_count"] = len(candidates)
        chosen["smb_diagnostics"] = diagnostics
        return chosen
    return {
        "status": "BLOCKED_NO_FULLY_EVALUABLE_SCALE_CONTAINER",
        "candidate_count": len(candidates),
        "smb_diagnostics": diagnostics,
    }


def _work(root: pathlib.Path, asset_path: str) -> pathlib.Path:
    safe = _norm(asset_path).replace("/", "__")
    return pathlib.Path(root).resolve() / "pt_build" / "devtest" / "player_scale_witness" / safe


def _run_player_scale_witness_impl(
    settings,
    registry,
    resolver,
    certifications,
    *,
    fps: int = 30,
) -> dict[str, Any]:
    """Run one physical Blender PLAYER scale witness at existing pose tolerances."""
    root = pathlib.Path(settings.project_root).resolve()
    selection = choose_player_scale_witness(registry, resolver)
    if not selection.get("asset"):
        out = root / "pt_build" / "devtest" / "player_scale_witness" / "result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "format": FORMAT,
            "status": str(selection.get("status") or "BLOCKED_NO_CERTIFIABLE_PLAYER_SCALE_CANDIDATE"),
            "domain": "PLAYER",
            "candidate_count": int(selection.get("candidate_count") or 0),
            "smb_diagnostics": selection.get("smb_diagnostics") or [],
            "witness_track_counts": {"rot": 0, "pos": 0, "scale": 0},
            "runtime_authorized": False,
            "production_authorized": False,
            "client_write_authorized": False,
            "server_write_authorized": False,
            "client_modified": False,
        }
        result["report"] = str(out)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    asset = registry.resolve(selection["asset"])
    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    skeleton = pathlib.Path(resolver.resolve(selection["skeleton_smb"], required=True)).resolve()
    before = {str(source): _sha256(source), str(skeleton): _sha256(skeleton)}

    work = _work(root, asset.primary_path)
    if work.exists():
        shutil.rmtree(work)
    import_work = work / "01_import"
    bake_work = work / "02_bake"
    check_work = work / "03_pose_check"
    for path in (import_work, bake_work, check_work):
        path.mkdir(parents=True, exist_ok=True)

    runner = ValidationRunner(ValidationContext(settings, resolver, certifications))
    overlay, texture_report = runner._texture_overlay(asset, import_work)
    pristine = import_work / "pristine_import.blend"
    importer = root / "pt_asset_tool" / "legacy_runtime" / "pt_smd_blender_import_v3_static_armature.py"
    run_logged(settings.blender_command() + [
        "--background", "--python-exit-code", "1", "--python", str(importer), "--",
        "--smd", str(source), "--skeleton", str(skeleton), "--client-root", str(overlay),
        "--out", str(pristine), "--no-pack",
    ], import_work / "01_import.log")

    payload = build_scale_container_bake_payload(
        root,
        skeleton,
        container=dict(selection["selected_container"]),
        fps=int(fps),
        max_frames_per_container=MAX_FRAMES_PER_CONTAINER,
    )
    payload_path = bake_work / "motion_bake_payload.json"
    write_payload(payload_path, payload)
    animated = bake_work / "animated.blend"
    bake_report = bake_work / "bake_report.json"
    run_logged(settings.blender_command() + [
        "--background", str(pristine), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "bake_actions.py"), "--",
        "--payload", str(payload_path), "--out", str(animated), "--report", str(bake_report),
    ], bake_work / "01_bake.log")
    baked = json.loads(bake_report.read_text(encoding="utf-8"))
    if baked.get("check") != "PASS":
        raise RuntimeError(f"PLAYER scale bake failed: {baked}")

    pose_report = check_work / "pose_space.json"
    run_logged(settings.blender_command() + [
        "--background", str(animated), "--python-exit-code", "1",
        "--python", str(root / "pt_asset_tool" / "blender" / "check_baked_animation_pose.py"), "--",
        "--payload", str(payload_path), "--report", str(pose_report),
    ], check_work / "01_pose_check.log")
    pose = json.loads(pose_report.read_text(encoding="utf-8"))
    if pose.get("status") != "PASS":
        raise RuntimeError(f"PLAYER scale pose-space gate failed: {pose.get('errors')}")

    after = {str(source): _sha256(source), str(skeleton): _sha256(skeleton)}
    changes = [path for path in before if before[path] != after[path]]
    if changes:
        raise RuntimeError(f"PLAYER scale witness modified physical client assets: {changes}")

    scale_witness = dict(payload.get("scale_witness") or {})
    if int(scale_witness.get("active_scale_sample_count") or 0) <= 0:
        raise RuntimeError("PLAYER scale witness passed Blender without an active scale sample")
    track_counts = dict(payload.get("track_key_counts") or {})
    if int(track_counts.get("scale") or 0) <= 0:
        raise RuntimeError("PLAYER scale witness selected SMB with zero scale keys")

    result = {
        "format": FORMAT,
        "status": "PASS",
        "domain": "PLAYER",
        "asset": asset.primary_path,
        "skeleton_smb": _norm(selection["skeleton_smb"]),
        "candidate_basis": selection.get("candidate_basis"),
        "selected_container": selection.get("selected_container"),
        "container_scan": selection.get("container_scan") or [],
        "candidate_count": int(selection.get("candidate_count") or 0),
        "source_mode": "STANDALONE_SMB_TMFRAME_SCALE_WITNESS",
        "automatic_actions_checked": int(pose.get("action_count") or 0),
        "checked_frames": int(pose.get("checked_frames") or 0),
        "checked_bone_frames": int(pose.get("checked_bone_frames") or 0),
        "max_abs_matrix_error": pose.get("max_abs_matrix_error"),
        "pose_report": str(pose_report),
        "bake_report": str(bake_report),
        "texture_ready": bool(texture_report.get("ready", True)),
        "automatic_pose_space_pass": True,
        "track_key_counts": track_counts,
        # Only scale is credited to the special witness. Existing representative
        # gates remain responsible for rotation/position coverage.
        "witness_track_counts": {"rot": 0, "pos": 0, "scale": int(track_counts.get("scale") or 0)},
        "scale_active_sample_count": int(scale_witness.get("active_scale_sample_count") or 0),
        "client_hash_changes": [],
        "runtime_authorized": False,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
        "client_modified": False,
    }
    out = root / "pt_build" / "devtest" / "player_scale_witness" / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    result["report"] = str(out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_player_scale_witness(
    settings,
    registry,
    resolver,
    certifications,
    *,
    fps: int = 30,
) -> dict[str, Any]:
    """Fail-closed wrapper used by the release orchestrator.

    A malformed physical candidate or Blender failure becomes a gate-level FAIL
    report instead of aborting the entire release regression.
    """
    root = pathlib.Path(settings.project_root).resolve()
    try:
        return _run_player_scale_witness_impl(
            settings, registry, resolver, certifications, fps=int(fps)
        )
    except Exception as exc:
        out = root / "pt_build" / "devtest" / "player_scale_witness" / "result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "format": FORMAT,
            "status": "FAIL",
            "domain": "PLAYER",
            "error": f"{type(exc).__name__}: {exc}",
            "witness_track_counts": {"rot": 0, "pos": 0, "scale": 0},
            "runtime_authorized": False,
            "production_authorized": False,
            "client_write_authorized": False,
            "server_write_authorized": False,
            "client_modified": False,
            "report": str(out),
        }
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
