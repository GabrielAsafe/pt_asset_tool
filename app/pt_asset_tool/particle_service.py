from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pt_effect_preview as effect_preview
import pt_part_editor as editor

from .config import Settings

FORMAT = "PT_PARTICLE_SERVICE_V1"


def safe_asset_path(client_root: Path, asset: str) -> tuple[Path, Path]:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset is required")
    root = client_root.resolve()
    p = (root / asset).resolve()
    try:
        rel = p.relative_to(root)
    except ValueError as exc:
        raise ValueError("asset escapes client root") from exc
    if p.suffix.lower() != ".part":
        raise ValueError("only .part assets are allowed")
    if not p.is_file():
        raise FileNotFoundError(rel.as_posix())
    return p, rel


def safe_preview_image(project_root: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("preview image path is required")
    root = (project_root.resolve() / "pt_build" / "devtest" / "effect_preview" / "blender").resolve()
    p = Path(raw_path).expanduser().resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise ValueError("preview image escapes effect preview root") from exc
    if p.suffix.lower() != ".png":
        raise ValueError("preview image must be PNG")
    if not p.is_file():
        raise FileNotFoundError(str(p))
    return p


def asset_index(client_root: Path, query: str = "") -> list[dict[str, Any]]:
    root = client_root.resolve()
    q = (query or "").casefold().strip()
    rows: list[dict[str, Any]] = []
    for p in editor.iter_part_files(root):
        rel = p.relative_to(root).as_posix()
        if q and q not in rel.casefold():
            continue
        rows.append({"asset": rel, "size": p.stat().st_size})
    return rows


def inspect_asset(client_root: Path, build_root: Path, asset: str) -> dict[str, Any]:
    p, rel = safe_asset_path(client_root, asset)
    data = p.read_bytes()
    meta = editor.inspect_bytes(data)
    draft = editor.show_draft(client_root, rel.as_posix(), build_root)
    return {
        "format": FORMAT,
        "asset": rel.as_posix(),
        "size": len(data),
        "source_sha256": editor.sha256(data),
        "parse_status": meta["parse_status"],
        "authoring_status": meta["authoring_status"],
        "eol": meta["eol"],
        "brace_open_count": meta["brace_open_count"],
        "brace_close_count": meta["brace_close_count"],
        "occurrences": meta["occurrences"],
        "draft": draft,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }


def apply_stage_edit(client_root: Path, build_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    asset = payload.get("asset")
    selector = payload.get("selector")
    value = payload.get("value")
    fresh = bool(payload.get("fresh", False))
    if not isinstance(selector, str) or not selector:
        raise ValueError("selector is required")
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    _, rel = safe_asset_path(client_root, str(asset or ""))
    return editor.stage_edit(client_root, rel.as_posix(), build_root, [f"{selector}={value}"], fresh=fresh)


def verify_asset_draft(client_root: Path, build_root: Path, asset: str) -> dict[str, Any]:
    _, rel = safe_asset_path(client_root, asset)
    return editor.verify_draft(client_root, rel.as_posix(), build_root)


def _blender_command(project_root: Path, client_root: Path) -> list[str]:
    return Settings.discover(project_root, client_root).blender_command()


def build_effect_preview(client_root: Path, build_root: Path, project_root: Path, asset: str) -> dict[str, Any]:
    _, rel = safe_asset_path(client_root, asset)
    plan = effect_preview.build_preview_plan(client_root, build_root, rel.as_posix(), prefer_staged=True, write=True)
    cmd = effect_preview.blender_command(
        project_root,
        Path(plan["plan_path"]),
        blender=_blender_command(project_root, client_root),
    )
    return {
        "status": "PASS",
        "asset": rel.as_posix(),
        "event_count": plan["event_count"],
        "missing_texture_reference_count": plan["missing_texture_reference_count"],
        "complexity": plan["complexity"],
        "source_base_kind": plan["source"]["base_kind"],
        "preview_certification": plan["preview_certification"],
        "plan_path": plan["plan_path"],
        "blender_command": cmd,
        "production_authorized": False,
        "client_write_authorized": False,
        "server_write_authorized": False,
    }


def run_effect_preview(
    client_root: Path,
    build_root: Path,
    project_root: Path,
    asset: str,
    lock: threading.Lock,
) -> dict[str, Any]:
    _, rel = safe_asset_path(client_root, asset)
    if not lock.acquire(blocking=False):
        raise RuntimeError("another Blender particle preview is already running")
    try:
        plan = effect_preview.build_preview_plan(client_root, build_root, rel.as_posix(), prefer_staged=True, write=True)
        run = effect_preview.run_blender_preview(
            project_root,
            Path(plan["plan_path"]),
            timeout_seconds=120.0,
            blender=_blender_command(project_root, client_root),
        )
        run["asset"] = rel.as_posix()
        run["preview_certification"] = plan["preview_certification"]
        run["plan_path"] = plan["plan_path"]
        return run
    finally:
        lock.release()
