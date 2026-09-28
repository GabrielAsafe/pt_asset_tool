from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Any

from .runtime_paths import app_command


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    group: str
    description: str
    mutates_build: bool = False
    long_running: bool = False
    interactive: bool = False
    mutates_client: bool = False


ACTION_SPECS: dict[str, ActionSpec] = {
    "inspect": ActionSpec("inspect", "Inspect", "Analyze", "Physical/semantic inspection of the asset."),
    "authoring_plan": ActionSpec("authoring_plan", "Edit plan", "Analyze", "Shows which asset channels can be edited today, which writers exist, and which gates still block build/publish."),
    "validate_structural": ActionSpec("validate_structural", "Structural", "Validate", "Runs the structural validator."),
    "bindings": ActionSpec("bindings", "Bindings", "Analyze", "Discovers skeleton/Physique candidates.", long_running=True),
    "motions": ActionSpec("motions", "Animations", "Analyze", "Lists motions associated with the asset."),
    "heads": ActionSpec("heads", "Compatible heads", "Analyze", "Lists verified head/face parts for the same animation root."),
    "texlinks": ActionSpec("texlinks", "TexLinks", "Analyze", "Inspects TexLink/material relationships."),
    "object_local": ActionSpec("object_local", "Object Local", "Analyze", "Inspects object-local transform semantics."),
    "validate_visual": ActionSpec("validate_visual", "Validate visual", "Validate", "Opens the asset in Blender for human geometry/texture evaluation; answer from the Jobs tab.", long_running=True, interactive=True),
    "validate_roundtrip": ActionSpec("validate_roundtrip", "Roundtrip Model", "Validate", "Rebuilds a static copy with a controlled witness and requests human evaluation from the Jobs tab.", long_running=True, interactive=True),
    "validate_object_local": ActionSpec("validate_object_local", "Roundtrip Object Local", "Validate", "Validates animation/object-local transforms in Blender; human responses are sent from the Jobs tab.", long_running=True, interactive=True),
    "validate_texlink_roundtrip": ActionSpec("validate_texlink_roundtrip", "Roundtrip TexLink", "Validate", "Validates TexLink/UV roundtrip.", long_running=True),
    "validate_stage072_preview": ActionSpec("validate_stage072_preview", "Stage Preview", "Validate", "Validates Stage0.72 transport/preview.", long_running=True),
    "validate_stage072_uv_roundtrip": ActionSpec("validate_stage072_uv_roundtrip", "Stage UV Roundtrip", "Validate", "Validates Stage0.72 UV roundtrip.", long_running=True),
    "validate_stage072_geometry_roundtrip": ActionSpec("validate_stage072_geometry_roundtrip", "Stage Geometry", "Validate", "Validates Stage0.72 geometry roundtrip.", long_running=True),
    "validate_animation": ActionSpec("validate_animation", "Animation", "Validate", "Visual evaluation without guard/timer. To edit or paint, use Import into Blender.", long_running=True, interactive=True),
    "diagnose_animation": ActionSpec("diagnose_animation", "Diagnose animation", "Analyze", "Compares source motion and Blender armature; human responses are sent from the Jobs tab.", long_running=True, interactive=True),
    "import_blender": ActionSpec("import_blender", "Import into Blender", "Edit", "Creates separate workspaces: stable Paint/Edit and Animation Preview; both share pt_build textures.", mutates_build=True, long_running=True),
    "view_rare": ActionSpec("view_rare", "Open in Blender", "Open", "Opens rare Model0.62 preview in Blender.", long_running=True),
    "view_stage072": ActionSpec("view_stage072", "Open Stage0.72", "Open", "Opens Stage0.72 preview in Blender.", long_running=True),
    "paint_stage072": ActionSpec("paint_stage072", "Texture Paint", "Edit", "Opens the Stage0.72 texture-paint workspace.", mutates_build=True, long_running=True),
    "upscale_texture": ActionSpec("upscale_texture", "Enhance / Upscale texture", "Enhancement", "Generates an enhanced 2x/3x/4x copy in the project enhancement folder; preserves alpha and protected TGA/BMP headers and does not write to the client.", mutates_build=True, long_running=True),
    "publish_enhancement": ActionSpec("publish_enhancement", "Publish enhancement to client", "Enhancement", "Publishes only the latest verified candidate compatible with the current asset hash, with backup, post-write hash verification, and drift rejection.", mutates_build=True, long_running=True, mutates_client=True),
    "restore_enhancement": ActionSpec("restore_enhancement", "Restore enhancement", "Enhancement", "Restores bytes from before the latest published enhancement; rejects unknown drift.", mutates_build=True, long_running=True, mutates_client=True),
    "edit_rare": ActionSpec("edit_rare", "Edit in Blender", "Edit", "Creates/opens the guarded rare-model workspace.", mutates_build=True, long_running=True),
    "write_rare": ActionSpec("write_rare", "Generate SMD", "Build", "Runs the guarded writer; output remains in pt_build.", mutates_build=True, long_running=True),
    "prepare_bundle": ActionSpec("prepare_bundle", "Prepare roundtrip", "Roundtrip", "Analyzes only this workspace: detects changed LODs/textures, simulates the writer, summarizes Physique repairs, and prepares backup/staging without writing to the client.", mutates_build=True, long_running=True),
    "publish_bundle": ActionSpec("publish_bundle", "Publish roundtrip", "Roundtrip", "Runs prepare + full backup + atomic write + post-write validation. Writes only actually modified files and automatically rolls back on failure.", mutates_build=True, long_running=True, mutates_client=True),
    "check_bundle": ActionSpec("check_bundle", "Verify roundtrip", "Roundtrip", "Validates only the latest bundle for this asset (hashes, drift, and post-write model); does not scan the entire corpus.", long_running=True),
    "restore_model_only": ActionSpec("restore_model_only", "Roll back model", "Roundtrip", "Manual rollback of only the model from the latest verified deploy. Keeps published textures, uses the original backup, and rejects unknown drift.", long_running=True, mutates_client=True),
    "restore_bundle": ActionSpec("restore_bundle", "Restore roundtrip", "Roundtrip", "Restores all files still published from the latest verified bundle; accepts a prior partial rollback and rejects any unknown drift.", long_running=True, mutates_client=True),
    "doctor": ActionSpec("doctor", "Doctor", "System", "Runs pt_asset doctor."),
}

MOTION_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,48}$")


def public_action_specs() -> list[dict[str, Any]]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "group": s.group,
            "description": s.description,
            "mutates_build": s.mutates_build,
            "long_running": s.long_running,
            "interactive": s.interactive,
            "mutates_client": s.mutates_client,
        }
        for s in ACTION_SPECS.values()
    ]


def build_command(project_root: pathlib.Path, action: str, rel: str | None, options: dict[str, Any] | None = None) -> list[str]:
    if action not in ACTION_SPECS:
        raise ValueError("ACTION_NOT_ALLOWED")
    options = options or {}
    base = app_command(project_root)
    if action == "doctor":
        return base + ["doctor"]
    if not rel:
        raise ValueError("ASSET_PATH_REQUIRED")
    rel = rel.replace("\\", "/").strip("/")
    if "\x00" in rel or rel.startswith("../") or "/../" in ("/" + rel + "/"):
        raise ValueError("INVALID_ASSET_PATH")
    if action == "inspect":
        return base + ["asset", "inspect", rel, "--physical"]
    if action == "authoring_plan":
        return base + ["asset", "authoring", rel]
    if action == "validate_structural":
        return base + ["validate", "structural", rel]
    if action == "bindings":
        return base + ["bindings", "--discover", rel]
    if action == "motions":
        return base + ["asset", "motions", rel]
    if action == "heads":
        return base + ["asset", "heads", rel, "--limit", "100"]
    if action == "texlinks":
        return base + ["asset", "texlinks", rel]
    if action == "object_local":
        return base + ["asset", "object-local", rel]
    if action == "validate_roundtrip":
        return base + ["validate", "roundtrip", rel]
    if action == "validate_object_local":
        return base + ["validate", "object-local", rel]
    if action == "validate_texlink_roundtrip":
        return base + ["validate", "texlink-roundtrip", rel]
    if action == "validate_stage072_preview":
        return base + ["validate", "stage072-preview", rel]
    if action == "validate_stage072_uv_roundtrip":
        return base + ["validate", "stage072-roundtrip", rel]
    if action == "validate_stage072_geometry_roundtrip":
        return base + ["validate", "stage072-geometry-roundtrip", rel]
    if action == "validate_visual":
        return base + ["validate", "visual", rel]
    if action in {"validate_animation", "diagnose_animation"}:
        motion = str(options.get("motion") or "STAND").strip().upper()
        if not MOTION_RE.match(motion):
            raise ValueError("INVALID_MOTION")
        prefix = ["validate", "animation"] if action == "validate_animation" else ["diagnose", "animation"]
        cmd = base + prefix + [rel, "--motion", motion]
        if "load_actions" in options:
            load_actions = str(options.get("load_actions") or "").strip().lower()
            if load_actions not in {"selected", "core", "all"}:
                raise ValueError("INVALID_LOAD_ACTIONS")
            cmd += ["--load-actions", load_actions]
        if action == "validate_animation" and ("head" in options or "head_tier" in options):
            head = str(options.get("head") or "auto").strip()
            head_tier = str(options.get("head_tier") or "auto").strip()
            if "\x00" in head or head.startswith("../") or "/../" in ("/" + head.replace("\\", "/") + "/"):
                raise ValueError("INVALID_HEAD")
            if not re.match(r"^[A-Za-z0-9_./\\ -]{1,240}$", head):
                raise ValueError("INVALID_HEAD")
            if not re.match(r"^[A-Za-z0-9_-]{1,32}$", head_tier):
                raise ValueError("INVALID_HEAD_TIER")
            cmd += ["--head", head, "--head-tier", head_tier]
        return cmd
    if action == "import_blender":
        cmd = base + ["import", rel]
        lod = str(options.get("lod") or "auto").strip().lower()
        if lod not in {"auto", "high", "default", "low"}:
            raise ValueError("INVALID_LOD")
        if lod != "auto":
            cmd += ["--lod", lod]
        model_info = str(options.get("model_info") or "").replace("\\", "/").strip("/")
        if model_info:
            if "\x00" in model_info or model_info.startswith("../") or "/../" in ("/" + model_info + "/"):
                raise ValueError("INVALID_MODEL_INFO")
            if not re.match(r"^[A-Za-z0-9_./ -]{1,240}\.inx$", model_info, re.IGNORECASE):
                raise ValueError("INVALID_MODEL_INFO")
            cmd += ["--model-info", model_info]
        load_actions = str(options.get("load_actions") or "all").strip().lower()
        if load_actions not in {"all", "selected", "none"}:
            raise ValueError("INVALID_IMPORT_LOAD_ACTIONS")
        cmd += ["--load-actions", load_actions]
        motion = str(options.get("motion") or "STAND").strip()
        if not MOTION_RE.match(motion):
            raise ValueError("INVALID_MOTION")
        cmd += ["--motion", motion]
        open_mode = str(options.get("open_mode") or "paint").strip().lower()
        if open_mode not in {"paint", "animation"}:
            raise ValueError("INVALID_IMPORT_OPEN_MODE")
        cmd += ["--open-mode", open_mode]
        if options.get("reset"):
            cmd.append("--reset")
        return cmd
    if action == "view_rare":
        return base + ["view", "rare-model", rel]
    if action == "view_stage072":
        return base + ["view", "stage072", rel]
    if action == "upscale_texture":
        scale = str(options.get("scale") or "4").strip()
        if scale not in {"2", "3", "4"}:
            raise ValueError("INVALID_TEXTURE_UPSCALE_SCALE")
        backend = str(options.get("backend") or "auto").strip().lower()
        if backend not in {"auto", "lanczos", "realesrgan"}:
            raise ValueError("INVALID_TEXTURE_UPSCALE_BACKEND")
        profile_raw = options.get("profile")
        profile = str(profile_raw or "balanced").strip().lower()
        if profile not in {"faithful", "balanced", "detail", "pixel-art"}:
            raise ValueError("INVALID_TEXTURE_QUALITY_PROFILE")
        if profile == "pixel-art" and backend == "realesrgan":
            raise ValueError("PIXEL_ART_REQUIRES_NON_AI_BACKEND")
        cmd = base + ["texture-upscale", "run", "--include-exact", rel, "--scale", scale, "--backend", backend]
        if profile_raw is not None:
            cmd += ["--profile", profile]
        if bool(options.get("include_ui")):
            cmd.append("--include-ui")
        return cmd
    if action == "publish_enhancement":
        return base + ["texture-upscale", "publish", "--include-exact", rel, "--confirm", "APPLY CLIENT ENHANCEMENT"]
    if action == "restore_enhancement":
        return base + ["texture-upscale", "restore", "--include-exact", rel, "--confirm", "RESTORE CLIENT ENHANCEMENT"]
    if action == "paint_stage072":
        stage = str(options.get("stage") if options.get("stage") is not None else "0")
        if stage not in {str(i) for i in range(8)}:
            raise ValueError("INVALID_STAGE")
        return base + ["paint", "stage072", rel, "--stage", stage]
    if action == "edit_rare":
        cmd = base + ["edit", "rare-model", rel]
        if options.get("reset"):
            cmd.append("--reset")
        return cmd
    if action == "write_rare":
        return base + ["write", "rare-model", rel]
    if action == "prepare_bundle":
        cmd = base + ["deploy", "workspace-prepare", rel]
        if bool(options.get("textures_only")):
            cmd.append("--textures-only")
        if bool(options.get("no_auto_rigid_weight_repair")):
            cmd.append("--no-auto-rigid-weight-repair")
        return cmd
    if action == "publish_bundle":
        cmd = base + ["deploy", "workspace-publish", rel, "--confirm", "APPLY CLIENT BUNDLE"]
        if bool(options.get("textures_only")):
            cmd.append("--textures-only")
        if bool(options.get("no_auto_rigid_weight_repair")):
            cmd.append("--no-auto-rigid-weight-repair")
        return cmd
    if action == "check_bundle":
        return base + ["deploy", "workspace-check", rel]
    if action == "restore_model_only":
        return base + ["deploy", "workspace-restore-model-latest", rel, "--confirm", "RESTORE CLIENT BUNDLE"]
    if action == "restore_bundle":
        return base + ["deploy", "workspace-restore-latest", rel, "--confirm", "RESTORE CLIENT BUNDLE"]
    raise AssertionError(action)
