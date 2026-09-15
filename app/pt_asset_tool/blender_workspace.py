from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str, *, fallback: str = "item", max_len: int = 64) -> str:
    text = _SAFE.sub("_", str(value or "").strip()).strip("._-") or fallback
    if len(text) <= max_len:
        return text
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{text[:max_len-12]}__{digest}"


def asset_workspace_name(logical: str) -> str:
    """Stable, readable directory name derived from a client-relative asset path."""
    raw = str(logical or "asset").replace("\\", "/").strip("/")
    p = pathlib.PurePosixPath(raw)
    parts = list(p.parts)
    if parts:
        parts[-1] = pathlib.PurePosixPath(parts[-1]).stem or parts[-1]
    readable = "__".join(_safe_component(x, max_len=40) for x in parts if x not in {"", ".", ".."})
    readable = readable or "asset"
    if len(readable) <= 150:
        return readable
    digest = hashlib.sha256(raw.lower().encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{readable[:136]}__{digest}"


def blender_edit_root(project_root: pathlib.Path, workflow: str, logical: str, *segments: str) -> pathlib.Path:
    root = pathlib.Path(project_root).resolve() / "pt_build" / "blender_edits"
    path = root / _safe_component(workflow, fallback="workflow") / asset_workspace_name(logical)
    for segment in segments:
        path = path / _safe_component(segment, fallback="workspace")
    return path


def write_workspace_info(
    workspace: pathlib.Path,
    *,
    workflow: str,
    logical: str,
    editable: bool = True,
    extra: dict[str, Any] | None = None,
) -> pathlib.Path:
    workspace = pathlib.Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "format": "PT_BLENDER_EDIT_WORKSPACE_V1",
        "workflow": workflow,
        "asset": str(logical).replace("\\", "/"),
        "workspace": str(workspace.resolve()),
        "editable": bool(editable),
        "client_modified": False,
        "policy": "all editable Blender artifacts remain under pt_build/blender_edits",
    }
    if extra:
        data.update(extra)
    out = workspace / "workspace_info.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
