from __future__ import annotations

import pathlib
from dataclasses import dataclass


ASSET_STATIC = "ASSET_STATIC_GAMEPLAY"
ASSET_MAP_METADATA = "ASSET_MAP_METADATA"
ASSET_MAP_METADATA_REVIEW = "ASSET_MAP_METADATA_REVIEW"
ASSET_SHARED_3D = "ASSET_SHARED_3D"
ASSET_SHARED_VISUAL = "ASSET_SHARED_VISUAL_REFERENCE"
CONFIG_REVIEW = "CONFIG_OPERATIONAL_REVIEW"
PERSISTENCE_BLOCKED = "PERSISTENCE_BLOCKED"
SECURITY_STATE_BLOCKED = "SECURITY_STATE_BLOCKED"
LOG_FORENSICS_EXCLUDED = "LOG_FORENSICS_EXCLUDED"
RUNTIME_INTEGRITY_BLOCKED = "RUNTIME_INTEGRITY_BLOCKED"
BINARY_TOOLING_EXCLUDED = "BINARY_TOOLING_EXCLUDED"
UNKNOWN_REVIEW = "UNKNOWN_REVIEW"


@dataclass(frozen=True)
class ServerPathClassification:
    relative_path: str
    lifecycle: str
    asset_candidate: bool
    design_visible: bool
    write_policy: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "relative_path": self.relative_path,
            "lifecycle": self.lifecycle,
            "asset_candidate": self.asset_candidate,
            "design_visible": self.design_visible,
            "write_policy": self.write_policy,
            "reason": self.reason,
        }


def _norm(relative_path: str | pathlib.PurePath) -> str:
    return str(relative_path).replace("\\", "/").lstrip("./")


def classify_server_path(relative_path: str | pathlib.PurePath) -> ServerPathClassification:
    rel = _norm(relative_path)
    low = rel.casefold()
    p = pathlib.PurePosixPath(rel)
    ext = p.suffix.casefold()
    first = p.parts[0].casefold() if p.parts else ""

    def row(lifecycle: str, *, asset: bool, visible: bool, policy: str, reason: str) -> ServerPathClassification:
        return ServerPathClassification(rel, lifecycle, asset, visible, policy, reason)

    # Exact raw-runtime/state files must win over extension rules.
    if low == "blesscastle.dat":
        return row(SECURITY_STATE_BLOCKED, asset=False, visible=False, policy="BLOCKED_STATE", reason="raw runtime/event state")
    if low == "cpitem.dat":
        return row(SECURITY_STATE_BLOCKED, asset=False, visible=False, policy="BLOCKED_STATE", reason="anti-duplication/security signatures")
    if ext == ".war":
        return row(PERSISTENCE_BLOCKED, asset=False, visible=False, policy="BLOCKED_PERSISTENCE", reason="warehouse/player persistence snapshot")

    if first == "dataserver":
        return row(PERSISTENCE_BLOCKED, asset=False, visible=False, policy="BLOCKED_PERSISTENCE", reason="account/character/warehouse persistence")
    if first == "postbox":
        return row(PERSISTENCE_BLOCKED, asset=False, visible=False, policy="BLOCKED_PERSISTENCE", reason="per-account postbox persistence")
    if first == "blackuser":
        return row(SECURITY_STATE_BLOCKED, asset=False, visible=False, policy="BLOCKED_STATE", reason="runtime blacklist/security state")
    if first == "funcbox":
        return row(RUNTIME_INTEGRITY_BLOCKED, asset=False, visible=False, policy="BLOCKED_RUNTIME_INTEGRITY", reason="client-version function integrity state")

    log_roots = {
        "logitemdata", "logadmin", "logdebug", "logfile", "logs",
        "coinshop_log", "timeshop_log",
    }
    if first in log_roots or first.startswith("log"):
        return row(LOG_FORENSICS_EXCLUDED, asset=False, visible=False, policy="FORENSICS_ONLY", reason="runtime log/audit/forensics")

    if first == "configs":
        return row(CONFIG_REVIEW, asset=False, visible=True, policy="REVIEW_CONFIG_ONLY", reason="operational/balance configuration")

    if ext in {".exe", ".dll", ".ocx", ".pdb", ".lib", ".exp", ".reg", ".bat", ".vb", ".vbproj", ".resx"}:
        return row(BINARY_TOOLING_EXCLUDED, asset=False, visible=False, policy="EXCLUDED_TOOLING", reason="binary/tooling/development artifact")

    # Static gameplay roots are parser-driven and safe only as bundles.
    if low.startswith("gameserver/monster/") and ext == ".inf":
        return row(ASSET_STATIC, asset=True, visible=True, policy="STAGE_ONLY_BUNDLE_VALIDATION", reason="server monster definition")
    if low.startswith("gameserver/npc/") and ext in {".npc", ".inf"}:
        return row(ASSET_STATIC, asset=True, visible=True, policy="STAGE_ONLY_BUNDLE_VALIDATION", reason="server NPC definition")
    if low.startswith("gameserver/openitem/") and ext == ".txt":
        return row(ASSET_STATIC, asset=True, visible=True, policy="STAGE_ONLY_BUNDLE_VALIDATION", reason="server OpenItem definition")
    if ext == ".zhoon" and (first == "name" or "/name/" in f"/{low}"):
        return row(ASSET_STATIC, asset=True, visible=True, policy="STAGE_ONLY_ENCODING_PRESERVE", reason="name/chat/localization resource")
    if low.startswith("gameserver/field/") and ext == ".spm":
        return row(ASSET_STATIC, asset=True, visible=True, policy="STAGE_ONLY_BUNDLE_VALIDATION", reason="field monster spawn table")
    if low.startswith("gameserver/field/") and ext == ".spp":
        return row(ASSET_MAP_METADATA, asset=True, visible=True, policy="STAGE_ONLY_LAYOUT_VALIDATION", reason="field start-point metadata")
    if low.startswith("gameserver/field/") and ext == ".spc":
        return row(ASSET_MAP_METADATA_REVIEW, asset=True, visible=True, policy="STAGE_ONLY_LAYOUT_VALIDATION", reason="fixed NPC placement table; Win32 smTRNAS_PLAYERINFO ABI is source-derived and authorable")

    # Same 3D family is physically present server-side; use the PT asset pipeline,
    # never infer safety from the extension alone.
    if ext in {".inx", ".smd", ".smb", ".ase"}:
        return row(ASSET_SHARED_3D, asset=True, visible=True, policy="PT_ASSET_PIPELINE_READ_ONLY_UNTIL_CERTIFIED", reason="shared model/stage metadata or 3D container")
    if ext in {".bmp", ".tga", ".dds", ".jpg", ".jpeg", ".png"}:
        return row(ASSET_SHARED_VISUAL, asset=False, visible=True, policy="REFERENCE_REQUIRED", reason="visual resource; server necessity is path/reference dependent")

    # Model logical INI outside Configs participates in model resolution but is
    # not safe for generic INI editing.
    if ext == ".ini" and first in {"char", "field"}:
        return row(ASSET_SHARED_3D, asset=True, visible=True, policy="MODEL_LOGICAL_REFERENCE_ONLY", reason="logical model/stage reference or textual fallback")

    return row(UNKNOWN_REVIEW, asset=False, visible=False, policy="REVIEW", reason="path/format role not yet classified")


def is_hard_excluded_server_path(relative_path: str | pathlib.PurePath) -> bool:
    return classify_server_path(relative_path).lifecycle in {
        PERSISTENCE_BLOCKED,
        SECURITY_STATE_BLOCKED,
        LOG_FORENSICS_EXCLUDED,
        RUNTIME_INTEGRITY_BLOCKED,
        BINARY_TOOLING_EXCLUDED,
    }
