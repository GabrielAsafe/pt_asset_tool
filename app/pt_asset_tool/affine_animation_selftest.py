from __future__ import annotations

"""Host-side Blender persistence gate for non-TRS legacy animation representation."""

import json
import pathlib
import shutil
from typing import Any

from .utils import run_logged

FORMAT = "PT_ASSET_AFFINE_ANIMATION_SELFTEST_V2"


def _read_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def run_affine_animation_selftest(settings, *, timeout_seconds: float = 90.0) -> dict[str, Any]:
    root = pathlib.Path(settings.project_root).resolve()
    work = root / "pt_build" / "devtest" / "affine_animation_selftest"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    blend = work / "affine_selftest.blend"
    expected = work / "expected.json"
    build_report = work / "build_report.json"
    check_report = work / "check_report.json"
    build_script = root / "pt_asset_tool" / "blender" / "affine_rig_selftest_build.py"
    check_script = root / "pt_asset_tool" / "blender" / "affine_rig_selftest_check.py"
    failure = None
    try:
        run_logged(
            settings.blender_command() + [
                "--background", "--factory-startup", "--python-exit-code", "1",
                "--python", str(build_script), "--",
                "--out", str(blend), "--expected", str(expected), "--report", str(build_report),
            ],
            work / "01_build.log", timeout_seconds=float(timeout_seconds),
        )
        run_logged(
            settings.blender_command() + [
                "--background", str(blend), "--python-exit-code", "1",
                "--python", str(check_script), "--",
                "--expected", str(expected), "--report", str(check_report),
            ],
            work / "02_reopen_check.log", timeout_seconds=float(timeout_seconds),
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"

    build = _read_json(build_report)
    check = _read_json(check_report)
    ok = (
        failure is None
        and isinstance(build, dict) and build.get("status") == "PASS"
        and isinstance(check, dict) and check.get("status") == "PASS"
        and blend.is_file()
    )
    result = {
        "format": FORMAT,
        "status": "PASS" if ok else "FAIL",
        "representation": "SVD_BLENDER_RESIDUAL_TWO_BONE_TRS_V2",
        "purpose": "prove full-rank non-TRS local bases persist through Blender Action save/reopen using Blender-aware residual conversion; rank-deficient non-TRS remains explicitly blocked",
        "build": build,
        "reopen_check": check,
        "failure": failure,
        "timeout_seconds_per_blender_operation": float(timeout_seconds),
        "blend": str(blend) if blend.is_file() else None,
        "client_write_authorized": False,
        "server_write_authorized": False,
        "production_authorized": False,
        "client_modified": False,
        "server_modified": False,
    }
    rp = work / "result.json"
    result["report"] = str(rp)
    rp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
