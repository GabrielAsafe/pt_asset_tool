from __future__ import annotations

import pathlib
from typing import Any

from .multilayer_texlink import parse_multilayer_semantics
from .object_local import parse_object_local_smd
from .rare_rigid_context import RARE_SMD_FILES
from .utils import low_path

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
