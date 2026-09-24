# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import tarfile
from PyInstaller.utils.hooks import collect_submodules

APP_ROOT = Path(SPECPATH).resolve()
PKG_ROOT = APP_ROOT / "pt_asset_tool"

datas = []
binaries = []

# Keep package resources physically addressable. Blender workflows pass many
# helper scripts by filesystem path to the external Blender runtime, so source
# files are intentionally available under the one-file extraction root as well
# as compiled into PYZ where imported normally.
for src in PKG_ROOT.rglob("*"):
    if not src.is_file() or "__pycache__" in src.parts or src.suffix == ".pyc":
        continue
    dest = str(src.parent.relative_to(APP_ROOT))
    datas.append((str(src), dest))

# Top-level helper scripts are invoked by the embedded Python runner or passed
# to Blender. Keep them physically addressable without making system Python a
# runtime dependency.
for src in APP_ROOT.glob("*.py"):
    if src.name == "pt_asset_app.py":
        continue
    datas.append((str(src), "."))
for name in ("VERSION.txt",):
    src = APP_ROOT / name
    if src.is_file():
        datas.append((str(src), "."))

# Certified enrichment vendor is application payload, not a machine-local
# dependency. Its scripts are run with the embedded interpreter.
vendor_root = APP_ROOT.parent / "vendor"
if vendor_root.is_dir():
    for src in vendor_root.rglob("*"):
        if src.is_file() and "__pycache__" not in src.parts and src.suffix != ".pyc":
            datas.append((str(src), str(Path("vendor") / src.parent.relative_to(vendor_root))))

# Real-ESRGAN is bundled when present, but as a compressed opaque payload.
# PyInstaller reclassifies executable-looking data and may run ldd against it;
# that is undesirable because the shipped NCNN binary intentionally targets the
# host Vulkan stack and a newer glibc floor than the main application. Packaging
# it inside a tarball prevents build-time relinking/dependency collection while
# preserving the executable bit and model files for runtime materialization.
tools = APP_ROOT.parent / "tools" / "realesrgan"
if not tools.is_dir():
    tools = APP_ROOT / "tools" / "realesrgan"
if not tools.is_dir():
    raise SystemExit("PORTABLE_BUILD_REALESRGAN_PAYLOAD_MISSING")
payload_dir = APP_ROOT / "build" / "_portable_payloads"
payload_dir.mkdir(parents=True, exist_ok=True)
payload_archive = payload_dir / "realesrgan_payload.tar.gz"
with tarfile.open(payload_archive, "w:gz") as tf:
    for src in sorted(tools.rglob("*")):
        if not src.is_file():
            continue
        arcname = Path("realesrgan") / src.relative_to(tools)
        tf.add(src, arcname=arcname.as_posix(), recursive=False)
datas.append((str(payload_archive), "payloads"))

# Package modules are discovered comprehensively. Top-level helper .py files
# are present as data and ordinary imports from pt_asset.py are also discovered
# by Analysis, avoiding accidental inclusion of development/test modules.
hiddenimports = sorted(set(collect_submodules("pt_asset_tool")))

# pyodbc belongs to the historical SQL Server adapter. bpy/bmesh/mathutils are
# supplied by external Blender. bs4/pytest are development/test-only.
excludes = ["pyodbc", "bpy", "bmesh", "mathutils", "bs4", "pytest"]

a = Analysis(
    [str(APP_ROOT / "pt_asset_app.py")],
    pathex=[str(APP_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pt-asset-tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
