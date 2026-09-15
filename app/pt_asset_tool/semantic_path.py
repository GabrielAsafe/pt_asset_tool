from __future__ import annotations

import pathlib


def semantic_group_for_path(path: str, fallback: str = "") -> str:
    """Return conservative semantic group from proven top-level physical trees.

    This is navigation/classification evidence only. It must never be used as
    runtime binding or writer authorization.
    """
    parts = pathlib.PurePosixPath(str(path).replace("\\", "/")).parts
    low = [p.casefold() for p in parts]
    if low and low[0] == "startimage":
        return "UI"
    if len(low) >= 2 and low[0] == "image" and low[1] == "sinimage":
        return "UI"
    if len(parts) >= 2 and parts[0].casefold() == "char":
        if parts[1].casefold() == "monster":
            return "MONSTER"
        if parts[1].casefold() == "npc":
            return "NPC"
    return str(fallback or "UNKNOWN").upper()


def entity_folder_for_path(path: str) -> str:
    parts = pathlib.PurePosixPath(str(path).replace("\\", "/")).parts
    if len(parts) >= 3 and parts[0].casefold() == "char" and parts[1].casefold() in {"monster", "npc"}:
        return parts[2]
    return ""
