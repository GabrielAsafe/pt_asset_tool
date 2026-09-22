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


_BLENDER_VERSION_CACHE: dict[tuple[str, ...], tuple[str | None, str | None]] = {}


def _resolve_launcher_executable(token: str) -> str | None:
    """Resolve one executable token without interpreting launcher arguments."""
    raw = str(token or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_file():
        return str(path.resolve())
    return _which(raw)


def _configured_blender_executable(project_root: Path) -> str | None:
    try:
        from .app_config import configured_blender_executable
        return configured_blender_executable(project_root)
    except Exception:
        return None


def _probe_blender_version(command: list[str]) -> tuple[str | None, str | None]:
    """Return (version, error) for a resolved Blender launcher.

    The probe intentionally uses ``--version`` rather than opening a GUI or
    importing a project.  This is safe for headless machines and also works for
    direct binaries, wrapper scripts and Flatpak launchers.  Results are cached
    per process because catalog preview requests may ask for the same runtime
    repeatedly.
    """
    key = tuple(command)
    cached = _BLENDER_VERSION_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        cp = subprocess.run(
            [*command, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception as exc:
        result = (None, f"version probe failed: {type(exc).__name__}: {exc}")
        _BLENDER_VERSION_CACHE[key] = result
        return result
    output = (cp.stdout or "").strip()
    if cp.returncode != 0:
        detail = output.replace("\n", " ")[:500]
        result = (None, f"version probe exited {cp.returncode}: {detail or 'no output'}")
        _BLENDER_VERSION_CACHE[key] = result
        return result
    import re
    match = re.search(r"\bBlender\s+([0-9]+(?:\.[0-9]+){1,2})", output, re.IGNORECASE)
    if not match:
        first = output.splitlines()[0] if output else "no output"
        result = (None, f"version probe returned unrecognized output: {first[:300]}")
        _BLENDER_VERSION_CACHE[key] = result
        return result
    result = (match.group(1), None)
    _BLENDER_VERSION_CACHE[key] = result
    return result


def blender_runtime_info(project_root: Path | None = None, *, probe_version: bool = False) -> dict[str, Any]:
    """Resolve the one Blender runtime used by every PT Asset Tool workflow.

    Precedence is intentionally explicit and portable:

    1. ``PT_BLENDER_EXE`` (single executable path/name)
    2. legacy ``PT_BLENDER_COMMAND`` / ``PT_ASSET_BLENDER_COMMAND``
    3. persistent machine-local ``blender_executable`` config
    4. native ``blender`` on PATH
    5. Flatpak ``org.blender.Blender``

    Explicit environment/configuration values are fail-closed: when configured
    but invalid, the resolver reports that error instead of silently selecting a
    different Blender installation.
    """
    project = _project_root(project_root)
    source = ""
    command: list[str] = []
    ready = False
    detail = ""

    explicit_exe = os.environ.get("PT_BLENDER_EXE")
    if explicit_exe is not None:
        source = "PT_BLENDER_EXE"
        raw = explicit_exe.strip()
        if not raw:
            detail = "PT_BLENDER_EXE is empty"
        else:
            exe = _resolve_launcher_executable(raw)
            if exe:
                command = [exe]
                ready = True
                detail = f"configured executable available: {exe}"
            else:
                command = [str(Path(raw).expanduser())]
                detail = f"configured Blender executable was not found: {raw}"
    else:
        raw_command = os.environ.get("PT_BLENDER_COMMAND") or os.environ.get("PT_ASSET_BLENDER_COMMAND")
        if raw_command is not None:
            import shlex
            source = "PT_BLENDER_COMMAND" if os.environ.get("PT_BLENDER_COMMAND") is not None else "PT_ASSET_BLENDER_COMMAND"
            command = shlex.split(raw_command)
            if not command:
                detail = f"{source} is empty"
            else:
                exe = _resolve_launcher_executable(command[0])
                if not exe:
                    detail = f"configured Blender launcher was not found: {command[0]}"
                else:
                    command[0] = exe
                    if Path(exe).name == "flatpak" and "org.blender.Blender" in command:
                        ready, detail = _flatpak_blender_ready()
                    else:
                        ready = True
                        detail = f"configured launcher available: {exe}"
        else:
            configured = _configured_blender_executable(project)
            if configured:
                source = "PERSISTENT_CONFIG"
                exe = _resolve_launcher_executable(configured)
                command = [exe or str(Path(configured).expanduser())]
                if exe:
                    ready = True
                    detail = f"persistent Blender executable available: {exe}"
                else:
                    detail = f"persistent Blender executable was not found: {configured}"
            else:
                native = _which("blender")
                if native:
                    source = "PATH"
                    command = [native]
                    ready = True
                    detail = f"native Blender available: {native}"
                else:
                    source = "FLATPAK"
                    command = ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
                    ready, detail = _flatpak_blender_ready()

    version = None
    probe_error = None
    if ready and probe_version:
        version, probe_error = _probe_blender_version(command)
        if probe_error:
            ready = False
            detail = f"{detail}; {probe_error}"
        elif version:
            detail = f"{detail}; Blender {version}"
    return {
        "command": command,
        "ready": bool(ready),
        "detail": detail,
        "source": source or "UNRESOLVED",
        "version": version,
        "probe_error": probe_error,
        "project_root": str(project),
    }


def resolve_blender_command(project_root: Path | None = None) -> tuple[list[str], bool, str]:
    """Backward-compatible tuple API used by existing Blender workflows."""
    info = blender_runtime_info(project_root, probe_version=False)
    return list(info["command"]), bool(info["ready"]), str(info["detail"])

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
    for name in ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan.exe"):
        found = _which(name)
        if found:
            return found, "resolved on PATH"
    bundled = bundled_realesrgan(project_root)
    if bundled:
        return str(bundled), "bundled with PT Asset Tool"
    return None, "not found on PATH and no bundled executable was found"


def dependency_report(project_root: Path | None = None) -> dict[str, Any]:
    project = _project_root(project_root)
    py_ok = sys.version_info >= (3, 11)
    blender_runtime = blender_runtime_info(project, probe_version=True)
    blender_cmd = list(blender_runtime["command"])
    blender_ok = bool(blender_runtime["ready"])
    blender_detail = str(blender_runtime["detail"])
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
            "install": "Fedora: sudo dnf install python3 python3-pip. Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip",
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
            "detail": (
                f"source={blender_runtime['source']} · "
                f"version={blender_runtime.get('version') or 'unverified'} · "
                f"command={' '.join(blender_cmd) or 'unresolved'} · {blender_detail}"
            ),
            "install": (
                "Fedora: sudo dnf install blender. Or: flatpak install flathub org.blender.Blender. "
                "Portable override: export PT_BLENDER_EXE=/path/to/blender. "
                "Persistent override: python3 pt_asset.py config set-blender-exe /path/to/blender. "
                "PT_BLENDER_COMMAND remains supported for launcher commands with arguments."
            ),
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
            "install": "Fedora diagnostic tools: sudo dnf install vulkan-tools. Also install the Vulkan driver appropriate for your GPU.",
        },
        {
            "id": "wine",
            "name": "Wine",
            "kind": "feature",
            "status": "READY" if (_which("wine") or _which("wine64")) else "MISSING",
            "required_for": ["local Server.exe launch/restart supervisor"],
            "reason": "The accepted Summit server runtime is Linux + Wine; the Python restarter launches the local Windows Server.exe through Wine.",
            "detail": _which("wine") or _which("wine64") or "wine executable not found",
            "install": "Fedora: sudo dnf install wine. No SQL Server/ODBC/firewall package is required for the SQLite runtime.",
        },
        {
            "id": "git",
            "name": "Git",
            "kind": "release",
            "status": "READY" if _which("git") else "MISSING",
            "required_for": ["READY_TO_DEPLOY commit workflow", "source control"],
            "reason": "The release finalizer stages and commits the clean, verified tree to Git.",
            "detail": _which("git") or "git executable not found",
            "install": "Fedora: sudo dnf install git. Debian/Ubuntu: sudo apt install git",
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
