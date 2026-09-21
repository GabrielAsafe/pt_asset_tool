from __future__ import annotations

import pathlib
from typing import Any

import pt_inx_motion_core_v2 as inxcore

from .multilayer_texlink import parse_multilayer_semantics
from .object_local import parse_object_local_smd
from .rare_rigid_context import RARE_SMD_FILES
from .utils import low_path
from .texture_upscale import PILLOW_AVAILABLE, SUPPORTED_SUFFIXES

# Interactive validators are now supported by the UI job console via a
# constrained stdin bridge (y/n/s only). Applicability remains family-specific.

_RARE_KEYS = {low_path(x) for x in RARE_SMD_FILES}
_AT_DRAGON = low_path("char/tmABCD/at_dragon.smd")


def _texlink_roundtrip_ready(path: pathlib.Path) -> bool:
    try:
        parsed = parse_multilayer_semantics(path)
    except Exception:
        return False
    return (
        parsed.get("source_semantics") == "PASS"
        and int(parsed.get("max_layers") or 0) == 2
        and int(parsed.get("multilayer_faces") or 0) >= 1
    )



def _object_local_ready(path: pathlib.Path) -> bool:
    try:
        parsed = parse_object_local_smd(path, strict_v1=False)
    except Exception:
        return False
    if int(parsed.get("animated_object_count") or 0) < 1:
        return False
    return True


def capabilities_for_asset(asset: Any, physical_path: pathlib.Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Return only actions the current GUI can execute for this exact asset.

    Backend validators remain authoritative. This layer is intentionally
    conservative: it suppresses known-inapplicable actions instead of letting
    users discover compatibility only after a RuntimeError. Interactive human
    review is supported by the UI job console.
    """
    caps: set[str] = {"inspect"}
    reasons: dict[str, str] = {}
    family = str(getattr(asset, "family", "") or "")
    kind = str(getattr(asset, "kind", "") or "")
    logical = str(getattr(asset, "primary_path", "") or "")
    key = low_path(logical)
    if PILLOW_AVAILABLE and pathlib.PurePosixPath(logical.replace("\\", "/")).suffix.lower() in SUPPORTED_SUFFIXES:
        caps.add("upscale_texture")

    if kind == "SMD_STAGE_072":
        caps.add("authoring_plan")
        caps.update({
            "view_stage072",
            "paint_stage072",
            "validate_stage072_preview",
            "validate_stage072_uv_roundtrip",
            "validate_stage072_geometry_roundtrip",
        })
        return sorted(caps), reasons

    if kind != "SMD_MODEL_062":
        # Textures and all support files are inspection/preview targets. There
        # is no generic structural validator for BMP/TGA/INX/SMB/WAV.
        return sorted(caps), reasons

    caps.add("authoring_plan")

    if family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"}:
        caps.add("texlinks")

    if family == "SMD_MODEL_062_STATIC":
        caps.update({"validate_structural", "object_local", "import_blender", "validate_visual", "validate_roundtrip"})
        if physical_path is not None and _object_local_ready(physical_path):
            caps.add("validate_object_local")
        else:
            reasons["validate_object_local"] = "NO_SUPPORTED_OBJECT_LOCAL_ANIMATION"
    elif family == "SMD_MODEL_062_RIGID_PHYSIQUE":
        if bool(getattr(asset, "rigid_binding_ready", False)):
            caps.update({"validate_structural", "import_blender", "validate_visual"})
        if str(getattr(asset, "binding_mode", "") or "") != "SELF_CONTAINED":
            caps.add("bindings")
        if bool(getattr(asset, "animation_binding_ready", False)):
            caps.update({"motions", "validate_animation", "diagnose_animation"})

    # The automatic strict TexLink roundtrip is source-shape dependent, so do
    # the same cheap physical preflight that the validator requires.
    if (
        physical_path is not None
        and family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"}
        and getattr(asset, "visual_mode", None)
        and _texlink_roundtrip_ready(physical_path)
    ):
        caps.add("validate_texlink_roundtrip")

    if key in _RARE_KEYS:
        caps.add("view_rare")
    if key == _AT_DRAGON:
        caps.update({"edit_rare", "write_rare"})

    return sorted(caps), reasons


_MOTION_ORDER = ("STAND", "WALK", "RUN", "ATTACK", "DAMAGE", "SKILL", "DEAD", "FALLDOWN")


def motion_inventory_for_asset(asset: Any, resolver: Any) -> list[dict[str, Any]]:
    """Return only physically present active MotionInfo clips for one asset.

    Entries are de-duplicated by the physical clip identity (SMB + frame slot +
    decoded range). Multiple state names pointing at the same clip become
    aliases instead of duplicate playable choices.
    """
    if not bool(getattr(asset, "animation_binding_ready", False)) or resolver is None:
        return []
    grouped: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    for cfg in getattr(asset, "configs", []) or []:
        if not isinstance(cfg, dict):
            continue
        inx = str(cfg.get("motion_inx") or cfg.get("inx") or "").replace("\\", "/")
        smb = str(cfg.get("motion_smb") or getattr(asset, "binding_skeleton_smb", "") or "").replace("\\", "/")
        if not inx or not smb:
            continue
        physical = resolver.resolve(inx, required=False)
        if physical is None:
            continue
        try:
            parsed = inxcore.parse_inx(pathlib.Path(physical))
        except Exception:
            continue
        for m in parsed.get("motions") or []:
            if int(m.get("motion_frame") or 0) <= 0:
                continue
            if not bool(m.get("start_ok", True)) or not bool(m.get("end_ok", True)):
                continue
            state = str(m.get("state_name") or f"MOTION_{m.get('index')}").upper()
            key = (smb.casefold(), int(m.get("motion_frame") or 0), int(m.get("start") or 0), int(m.get("end") or 0))
            row = grouped.setdefault(key, {
                "canonical": state,
                "aliases": set(),
                "clips": [],
                "playable": True,
                "source": inx,
                "motion_smb": smb,
                "evidence": "ACTIVE_INX_MOTIONINFO_PHYSICAL",
                "motion_frame": int(m.get("motion_frame") or 0),
                "start": int(m.get("start") or 0),
                "end": int(m.get("end") or 0),
            })
            if row["canonical"] != state:
                row["aliases"].add(state)
            row["clips"].append({"index": int(m.get("index") or 0), "state": state, "source": inx})
    order = {name: i for i, name in enumerate(_MOTION_ORDER)}
    out = []
    for row in grouped.values():
        states = {row["canonical"], *row["aliases"]}
        canonical = sorted(states, key=lambda x: (order.get(x, 999), x.casefold()))[0]
        aliases = sorted(states - {canonical}, key=lambda x: (order.get(x, 999), x.casefold()))
        row["canonical"] = canonical
        row["aliases"] = aliases
        row["clips"] = sorted(row["clips"], key=lambda x: (x["index"], x["state"]))
        out.append(row)
    return sorted(out, key=lambda x: (order.get(x["canonical"], 999), x["canonical"].casefold(), x["source"].casefold()))


def ui_options_for_asset(
    asset: Any,
    resolver: Any,
    *,
    model_info_options: list[dict[str, Any]] | None = None,
    head_candidates: list[dict[str, Any]] | None = None,
    animation_binding_ready_physical: bool = False,
) -> dict[str, Any]:
    infos = list(model_info_options or [])
    heads = list(head_candidates or [])
    motions = motion_inventory_for_asset(asset, resolver) if animation_binding_ready_physical else []
    available_lods = []
    for tier in ("high", "default", "low"):
        if any(tier in (x.get("available_lods") or []) for x in infos):
            available_lods.append(tier)
    motion_names = [x["canonical"] for x in motions]
    default_motion = ""
    if len(motion_names) == 1:
        default_motion = motion_names[0]
    elif "STAND" in motion_names:
        default_motion = "STAND"
    elif motion_names:
        default_motion = motion_names[0]
    category = str(getattr(asset, "category", "") or "").upper()
    family = str(getattr(asset, "family", "") or "")
    return {
        "supports_paint": family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"},
        "supports_animation": bool(animation_binding_ready_physical and motions),
        "available_motions": motion_names,
        "motion_inventory": motions,
        "default_motion": default_motion or None,
        "supports_lod_selection": bool(available_lods),
        "available_lods": available_lods,
        "requires_model_info": len(infos) > 1,
        "model_info_options": infos,
        "supports_head": bool(category == "CHARACTER" and heads),
        "head_candidates": heads,
        "supports_roundtrip": family in {"SMD_MODEL_062_STATIC", "SMD_MODEL_062_RIGID_PHYSIQUE"},
    }
