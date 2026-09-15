from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from .authoring import verify_workspace_manifest
from .blender_workspace import asset_workspace_name, blender_edit_root
from .stage072_geometry import (
    compare_stage072_geometry_roundtrip,
    strict_write_stage072_geometry_witness,
)
from .stage072_roundtrip import (
    compare_stage072_uv_roundtrip,
    strict_write_stage072_uv_witness,
)

FORMAT = "PT_STAGE072_SAVED_BLENDER_CANDIDATE_PLAN_V1"
BUILD_FORMAT = "PT_STAGE072_SAVED_BLENDER_CANDIDATE_BUILD_V1"


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    root = pathlib.Path(root).resolve()
    path = pathlib.Path(path).resolve()
    return path == root or root in path.parents


def plan_stage072_saved_blender_candidate(
    project_root: pathlib.Path | str,
    resolver,
    asset,
    *,
    output: pathlib.Path | str | None = None,
) -> dict[str, Any]:
    """Plan a tightly scoped Stage0.72 saved-Blender candidate build.

    The candidate accepts two preservation-gated edit families:
    - UV-only changes while geometry/StageArea/material/light metadata stay fixed;
    - one or more XYZ vertex changes on the exact 1/256 grid, with StageArea and
      every incident face normal rebuilt by the strict geometry writer.

    The edited Blend is scanned inside Blender before the host-side strict writer
    runs.  This never authorizes a client write.
    """
    project_root = pathlib.Path(project_root).resolve()
    if asset.kind != "SMD_STAGE_072":
        raise RuntimeError(f"Stage0.72 candidate requires SMD_STAGE_072, got {asset.kind}/{asset.family}")

    source = pathlib.Path(resolver.resolve(asset.primary_path, required=True)).resolve()
    source_sha = _sha256(source)
    workspace = blender_edit_root(project_root, "generic_import", asset.primary_path)
    blend = workspace / "imported.blend"
    manifest = workspace / "authoring_manifest.json"
    blockers: list[str] = []
    if not blend.is_file():
        blockers.append("GENERIC_IMPORT_WORKSPACE_MISSING")
    if not manifest.is_file():
        manifest_verify = {
            "status": "FAIL",
            "errors": ["AUTHORING_MANIFEST_MISSING"],
            "build_authorized": False,
            "client_write_authorized": False,
        }
        blockers.append("AUTHORING_MANIFEST_MISSING")
    else:
        manifest_verify = verify_workspace_manifest(manifest)
        if manifest_verify.get("status") != "PASS":
            blockers.append("AUTHORING_WORKSPACE_PROVENANCE_FAILED")
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_sha = str(((manifest_data.get("source") or {}).get("sha256")) or "")
            if manifest_sha.lower() != source_sha.lower():
                blockers.append("AUTHORING_MANIFEST_SOURCE_SHA_MISMATCH")
        except Exception:
            blockers.append("AUTHORING_MANIFEST_READ_FAILED")

    if output is None:
        output_path = (
            project_root / "pt_build" / "candidate_build" /
            asset_workspace_name(asset.primary_path) /
            pathlib.PurePosixPath(asset.primary_path).name
        ).resolve()
    else:
        raw = pathlib.Path(output).expanduser()
        output_path = (project_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if not _inside(project_root / "pt_build", output_path):
        blockers.append("OUTPUT_OUTSIDE_PT_BUILD")

    return {
        "format": FORMAT,
        "status": "READY" if not blockers else "BLOCKED",
        "authorization": "CANDIDATE_PT_BUILD_ONLY",
        "asset_id": asset.asset_id,
        "asset": asset.primary_path,
        "source": str(source),
        "source_sha256": source_sha,
        "workspace": str(workspace),
        "blend": str(blend),
        "authoring_manifest": str(manifest),
        "manifest_verification": manifest_verify,
        "output": str(output_path),
        "accepted_edit_modes": ["UV_ONLY", "GEOMETRY_GRID_MULTI"],
        "forbidden_edits": [
            "topology", "material assignment/metadata", "vertex color", "light metadata",
            "mixed UV+geometry in one candidate build", "non-grid geometry",
        ],
        "blockers": blockers,
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }


def build_stage072_edit_extract_command(settings, candidate: dict[str, Any], *, witness: pathlib.Path, report: pathlib.Path) -> list[str]:
    if candidate.get("status") != "READY":
        raise RuntimeError(f"candidate plan is not ready: {candidate.get('blockers')}")
    project_root = pathlib.Path(settings.project_root).resolve()
    helper = project_root / "pt_asset_tool" / "blender" / "extract_stage072_saved_edit.py"
    if not helper.is_file():
        raise FileNotFoundError(helper)
    return settings.blender_command() + [
        "--background", str(pathlib.Path(candidate["blend"]).resolve()),
        "--python-exit-code", "1",
        "--python", str(helper), "--",
        "--smd", str(pathlib.Path(candidate["source"]).resolve()),
        "--witness", str(pathlib.Path(witness).resolve()),
        "--report", str(pathlib.Path(report).resolve()),
        "--expected-source-sha256", str(candidate["source_sha256"]),
    ]


def apply_stage072_candidate_witness(candidate: dict[str, Any], witness: pathlib.Path | str) -> dict[str, Any]:
    """Apply an edit witness extracted from the saved Blend using strict host writers."""
    if candidate.get("status") != "READY":
        raise RuntimeError(f"candidate plan is not ready: {candidate.get('blockers')}")
    witness = pathlib.Path(witness).resolve()
    payload = json.loads(witness.read_text(encoding="utf-8"))
    source = pathlib.Path(candidate["source"]).resolve()
    output = pathlib.Path(candidate["output"]).resolve()
    if str(payload.get("source_sha256") or "").lower() != str(candidate["source_sha256"]).lower():
        raise RuntimeError("Stage0.72 saved-edit witness/source sha256 mismatch")
    mode = str(payload.get("edit_mode") or "")
    output.parent.mkdir(parents=True, exist_ok=True)
    writer_report = output.with_suffix(output.suffix + ".strict_writer.json")
    compare_report = output.with_suffix(output.suffix + ".strict_compare.json")

    if mode == "UV_ONLY":
        writer = strict_write_stage072_uv_witness(
            source, output, witness,
            expected_source_sha256=str(candidate["source_sha256"]),
            report_path=writer_report,
        )
        compare = compare_stage072_uv_roundtrip(source, output, witness, report_path=compare_report)
    elif mode == "GEOMETRY_GRID_MULTI":
        writer = strict_write_stage072_geometry_witness(
            source, output, witness,
            expected_source_sha256=str(candidate["source_sha256"]),
            report_path=writer_report,
        )
        compare = compare_stage072_geometry_roundtrip(source, output, witness, report_path=compare_report)
    else:
        raise RuntimeError(f"unsupported Stage0.72 saved-edit witness mode: {mode!r}")

    passed = writer.get("check") == "PASS" and compare.get("check") == "PASS"
    return {
        "format": BUILD_FORMAT,
        "status": "PASS" if passed else "FAIL",
        "edit_mode": mode,
        "candidate_plan": candidate,
        "witness": str(witness),
        "writer": writer,
        "compare": compare,
        "output": str(output),
        "production_authorized": False,
        "client_write_authorized": False,
        "client_modified": False,
    }
