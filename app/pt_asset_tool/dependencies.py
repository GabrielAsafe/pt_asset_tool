from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

FORMAT = "PT_ASSET_DEPENDENCY_REPORT_V1"


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _which(name: str) -> str | None:
    return shutil.which(name)


def _project_root(project_root: Path | None = None) -> Path:
    return (project_root or Path(__file__).resolve().parents[1]).resolve()


def _repo_root(project_root: Path) -> Path:
    # Normal distribution layout: <repo>/app/pt_asset_tool/dependencies.py.
    return project_root.parent.resolve()


def _flatpak_blender_ready() -> tuple[bool, str]:
    fp = _which("flatpak")
    if not fp:
        return False, "flatpak executable not found"
    try:
        cp = subprocess.run(
            [fp, "info", "org.blender.Blender"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return False, f"flatpak probe failed: {type(exc).__name__}: {exc}"
    if cp.returncode == 0:
        return True, "Flatpak Blender org.blender.Blender is installed"
    detail = (cp.stderr or "").strip().replace("\n", " ")
    return False, detail or "Flatpak Blender org.blender.Blender is not installed"


def resolve_blender_command(project_root: Path | None = None) -> tuple[list[str], bool, str]:
    del project_root  # reserved for future project-local launchers
    raw = os.environ.get("PT_BLENDER_COMMAND") or os.environ.get("PT_ASSET_BLENDER_COMMAND")
    if raw:
        import shlex
        cmd = shlex.split(raw)
        if not cmd:
            return [], False, "PT_BLENDER_COMMAND is empty"
        exe = _which(cmd[0]) if not Path(cmd[0]).expanduser().is_file() else str(Path(cmd[0]).expanduser().resolve())
        if not exe:
            return cmd, False, f"configured Blender launcher was not found: {cmd[0]}"
        if Path(cmd[0]).name == "flatpak" and "org.blender.Blender" in cmd:
            ok, detail = _flatpak_blender_ready()
            return cmd, ok, detail
        return cmd, True, f"configured launcher available: {exe}"

    native = _which("blender")
    if native:
        return [native], True, f"native Blender available: {native}"
    ok, detail = _flatpak_blender_ready()
    return ["flatpak", "run", "--filesystem=home", "org.blender.Blender"], ok, detail


def bundled_realesrgan(project_root: Path | None = None) -> Path | None:
    project = _project_root(project_root)
    repo = _repo_root(project)
    names = ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan.exe")
    for base in (repo / "tools" / "realesrgan", project / "tools" / "realesrgan"):
        for name in names:
            p = base / name
            if p.is_file():
                return p.resolve()
    return None


def resolve_realesrgan(project_root: Path | None = None, explicit: str | None = None) -> tuple[str | None, str]:
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return str(p.resolve()), "explicit path"
        found = _which(explicit)
        if found:
            return found, "explicit executable resolved on PATH"
        return None, f"explicit Real-ESRGAN executable not found: {explicit}"
    bundled = bundled_realesrgan(project_root)
    if bundled:
        return str(bundled), "bundled with PT Asset Tool"
    for name in ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan.exe"):
        found = _which(name)
        if found:
            return found, "resolved on PATH"
    return None, "no bundled executable was found and Real-ESRGAN was not found on PATH"


def dependency_report(project_root: Path | None = None) -> dict[str, Any]:
    project = _project_root(project_root)
    py_ok = sys.version_info >= (3, 11)
    blender_cmd, blender_ok, blender_detail = resolve_blender_command(project)
    realesrgan_path, realesrgan_source = resolve_realesrgan(project)

    vulkan_tool = _which("vulkaninfo")
    vulkan_ready = bool(vulkan_tool)
    # vulkaninfo is a diagnostic proxy. Real-ESRGAN may still work when it is
    # absent, so this remains a recommended/diagnostic dependency, not a hard gate.

    rows: list[dict[str, Any]] = [
        {
            "id": "python",
            "name": "Python 3.11+",
            "kind": "required",
            "status": "READY" if py_ok else "MISSING",
            "required_for": ["CLI", "GUI", "parsers", "validators", "build/staging"],
            "reason": "The application and all first-party workflows run on Python; 3.11+ is the supported baseline.",
            "detail": sys.version.split()[0],
            "install": "Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip",
        },
        {
            "id": "pillow",
            "name": "Pillow",
            "kind": "feature",
            "status": "READY" if _module("PIL") else "MISSING",
            "required_for": ["texture enhancement", "image preview", "image-producing asset compiler paths"],
            "reason": "Image decoding, resizing, sharpening and several preview/build paths use Pillow.",
            "detail": "PIL import available" if _module("PIL") else "PIL import unavailable",
            "install": "python3 -m pip install -r app/requirements.txt  # or: python3 -m pip install Pillow",
        },
        {
            "id": "numpy",
            "name": "NumPy",
            "kind": "feature",
            "status": "READY" if _module("numpy") else "MISSING",
            "required_for": ["fast Stage 0.72 normal analysis"],
            "reason": "The Stage 0.72 normal analyzer has a NumPy implementation used for fast vectorized validation.",
            "detail": "numpy import available" if _module("numpy") else "numpy import unavailable",
            "install": "python3 -m pip install -r app/requirements.txt  # or: python3 -m pip install numpy",
        },
        {
            "id": "blender",
            "name": "Blender",
            "kind": "feature",
            "status": "READY" if blender_ok else "MISSING",
            "required_for": ["3D preview", "visual validation", "model import/edit", "animation checks", "particle preview"],
            "reason": "These workflows execute Blender-side scripts and therefore need the Blender runtime (bpy/bmesh/mathutils are provided by Blender itself).",
            "detail": f"{' '.join(blender_cmd)} · {blender_detail}",
            "install": "Option A: sudo apt install blender. Option B: flatpak install flathub org.blender.Blender. To use another launcher: export PT_BLENDER_COMMAND='blender'",
        },
        {
            "id": "realesrgan",
            "name": "Real-ESRGAN NCNN Vulkan",
            "kind": "feature_bundled",
            "status": "READY" if realesrgan_path else "MISSING",
            "required_for": ["AI texture enhancement backend"],
            "reason": "The AI enhancement backend invokes realesrgan-ncnn-vulkan; Lanczos remains available without it when Pillow is installed.",
            "detail": f"{realesrgan_path or 'not found'} · {realesrgan_source}",
            "install": "A compatible binary is normally bundled under tools/realesrgan. Otherwise install realesrgan-ncnn-vulkan and put it on PATH, or pass --realesrgan /path/to/realesrgan-ncnn-vulkan. Use --backend lanczos when AI enhancement is not required.",
        },
        {
            "id": "vulkan",
            "name": "Vulkan runtime / driver",
            "kind": "recommended",
            "status": "READY" if vulkan_ready else "OPTIONAL_MISSING",
            "required_for": ["Real-ESRGAN NCNN Vulkan GPU execution"],
            "reason": "The bundled Real-ESRGAN backend uses Vulkan. vulkaninfo is used only as a diagnostic proxy and is not a hard application gate.",
            "detail": vulkan_tool or "vulkaninfo not found",
            "install": "Ubuntu/Debian diagnostic tools: sudo apt install vulkan-tools. Also install the Vulkan driver appropriate for your GPU.",
        },
        {
            "id": "git",
            "name": "Git",
            "kind": "release",
            "status": "READY" if _which("git") else "MISSING",
            "required_for": ["READY_TO_DEPLOY commit workflow", "source control"],
            "reason": "The release finalizer stages and commits the clean, verified tree to Git.",
            "detail": _which("git") or "git executable not found",
            "install": "Ubuntu/Debian: sudo apt install git",
        },
        {
            "id": "pytest",
            "name": "pytest",
            "kind": "development",
            "status": "READY" if _module("pytest") else "MISSING",
            "required_for": ["regression suite", "READY_TO_DEPLOY default test gate"],
            "reason": "The clean-release workflow runs the automated regression suite before it removes run artifacts and commits.",
            "detail": "pytest import available" if _module("pytest") else "pytest import unavailable",
            "install": "python3 -m pip install -r app/requirements-dev.txt",
        },
    ]
    blocking = [r["id"] for r in rows if r["kind"] == "required" and r["status"] != "READY"]
    feature_missing = [r["id"] for r in rows if r["kind"] in {"feature", "feature_bundled"} and r["status"] != "READY"]
    return {
        "format": FORMAT,
        "status": "PASS" if not blocking else "FAIL",
        "project_root": str(project),
        "platform": platform.platform(),
        "blocking_missing": blocking,
        "feature_missing": feature_missing,
        "dependencies": rows,
    }


def format_dependency_report(report: dict[str, Any]) -> str:
    lines = [f"Dependency check: {report.get('status', 'UNKNOWN')}"]
    for row in report.get("dependencies", []):
        lines.append("")
        lines.append(f"[{row['status']}] {row['name']} ({row['kind']})")
        lines.append("  Required for: " + ", ".join(row.get("required_for") or []))
        lines.append("  Why: " + str(row.get("reason") or ""))
        lines.append("  Detail: " + str(row.get("detail") or ""))
        if row.get("status") != "READY":
            lines.append("  Install/configure: " + str(row.get("install") or ""))
    return "\n".join(lines)


def cli_main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Diagnose PT Asset Tool external/Python dependencies")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ns = p.parse_args(argv)
    report = dependency_report(project_root)
    print(json.dumps(report, indent=2, ensure_ascii=False) if ns.json else format_dependency_report(report))
    return 0 if report["status"] == "PASS" else 2


def dependency_message(project_root: Path | None, dependency_id: str) -> str:
    """Return a user-facing actionable dependency message for an error path."""
    report = dependency_report(project_root)
    row = next((r for r in report.get("dependencies", []) if r.get("id") == dependency_id), None)
    if not row:
        return f"Dependency unavailable: {dependency_id}. Run `python3 pt_asset.py dependencies`."
    return (
        f"{row['name']} is unavailable. Required for: {', '.join(row.get('required_for') or [])}. "
        f"Why: {row.get('reason')}. Current state: {row.get('detail')}. "
        f"Install/configure: {row.get('install')}. Run `python3 pt_asset.py dependencies` for the full environment report."
    )
