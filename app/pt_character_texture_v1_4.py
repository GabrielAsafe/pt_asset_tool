#!/usr/bin/env python3
"""
PT Character Texture Core V1.2

Character-profile driven BMP texture workflow.

Current proven/supported protected format:
  BMP_PRISTON_PREFIX14
  256x256
  24 bpp
  BI_RGB
  40-byte BITMAPINFOHEADER

Safety model:
- registered source bytes are immutable baseline;
- editable file is a standard BMP;
- game build preserves ALL baseline bytes outside the pixel payload;
- only pixel payload bytes are copied from the artist BMP;
- no-op decode -> build must be byte-identical;
- publish modifies workspace only;
- deploy uses hardened Restore V3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import struct
import subprocess
import sys


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def resolve(root: pathlib.Path, value):
    p = pathlib.Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def norm_rel(value: str) -> str:
    s = str(value).replace("\\", "/").strip("/")
    if not s or s.startswith("../") or "/../" in f"/{s}/":
        raise ValueError(f"unsafe relative path: {value}")
    return s


def safe_join(root: pathlib.Path, rel: str) -> pathlib.Path:
    rel = norm_rel(rel)
    p = (root / pathlib.PurePosixPath(rel)).resolve()
    rr = root.resolve()
    try:
        p.relative_to(rr)
    except ValueError:
        raise ValueError(f"path escapes root: {rel}")
    return p


def load_profile(root, profile_arg):
    path = resolve(root, profile_arg)
    if not path.is_file():
        raise FileNotFoundError(path)
    p = load_json(path)
    return path, p


def component_for_role(profile, role):
    rows = [x for x in profile.get("components", []) if x.get("role") == role]
    if len(rows) != 1:
        raise ValueError(f"profile role {role!r}: expected exactly one component, found {len(rows)}")
    row = rows[0]
    if not row.get("editable"):
        raise ValueError(f"profile role {role!r} is not editable")
    if not row.get("roundtrip_target") or not row.get("workspace_path"):
        raise ValueError(f"profile role {role!r} lacks roundtrip/workspace mapping")
    return row


def load_workspace(workspace):
    workspace = pathlib.Path(workspace).expanduser().resolve()
    mp = workspace / "workspace_manifest.json"
    if not mp.is_file():
        raise FileNotFoundError(mp)
    return workspace, mp, load_json(mp)


def workspace_entry(data, target):
    wanted = norm_rel(target).lower()
    rows = [
        x for x in data.get("files", [])
        if norm_rel(str(x.get("roundtrip_target", ""))).lower() == wanted
    ]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one workspace entry for {target}; found {len(rows)}")
    return rows[0]


def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def i32(b, o): return struct.unpack_from("<i", b, o)[0]


def inspect_bmp_bytes(data: bytes):
    if len(data) < 54:
        raise ValueError("BMP too small")

    standard = data[:2] == b"BM"
    dib_size = u32(data, 14)
    if dib_size != 40:
        raise ValueError(f"unsupported DIB header size {dib_size}; current gate requires 40")

    width = i32(data, 18)
    height = i32(data, 22)
    planes = u16(data, 26)
    bpp = u16(data, 28)
    compression = u32(data, 30)
    image_size_field = u32(data, 34)
    colors_used = u32(data, 46)

    if width <= 0 or height == 0:
        raise ValueError(f"unsupported BMP dimensions {width}x{height}")
    if planes != 1:
        raise ValueError(f"unsupported planes={planes}")
    if bpp not in (8, 24, 32):
        raise ValueError(f"unsupported bpp={bpp}; current texture core supports BI_RGB 8/24/32")
    if compression != 0:
        raise ValueError(f"unsupported compression={compression}; current texture core requires BI_RGB")

    palette_entries = (colors_used or (1 << bpp)) if bpp <= 8 else 0
    palette_bytes = palette_entries * 4

    if standard:
        declared_size = u32(data, 2)
        pixel_offset = u32(data, 10)
        if declared_size not in (0, len(data)):
            raise ValueError(f"BMP declared size {declared_size} != actual {len(data)}")
        fmt = "BMP_STANDARD_24BPP"
        prefix14 = data[:14]
    else:
        # Current runtime-proven proprietary family replaces exactly the
        # BITMAPFILEHEADER. For this supported gate the pixel data starts
        # immediately after the 14 + 40-byte headers.
        pixel_offset = 14 + dib_size + palette_bytes
        prefix14 = data[:14]
        fmt = f"BMP_PRISTON_PREFIX14_DIB40_RGB{bpp}"

    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_bytes = row_stride * abs(height)
    pixel_end = pixel_offset + pixel_bytes
    if pixel_end > len(data):
        raise ValueError(
            f"pixel payload exceeds file: offset={pixel_offset} bytes={pixel_bytes} size={len(data)}"
        )

    return {
        "format": fmt,
        "standard": standard,
        "file_size": len(data),
        "dib_size": dib_size,
        "width": width,
        "height": height,
        "planes": planes,
        "bpp": bpp,
        "compression": compression,
        "image_size_field": image_size_field,
        "colors_used": colors_used,
        "palette_entries": palette_entries,
        "palette_bytes": palette_bytes,
        "pixel_offset": pixel_offset,
        "row_stride": row_stride,
        "pixel_bytes": pixel_bytes,
        "pixel_end": pixel_end,
        "trailing_bytes": len(data) - pixel_end,
        "prefix14_hex": prefix14.hex(),
    }


def canonical_bmp_header(file_size, pixel_offset):
    return (
        b"BM"
        + struct.pack("<I", file_size)
        + b"\x00\x00\x00\x00"
        + struct.pack("<I", pixel_offset)
    )


def decode_editable(source: bytes, info: dict) -> bytes:
    if info["standard"]:
        return source
    return canonical_bmp_header(len(source), info["pixel_offset"]) + source[14:]


def validate_edited_against_baseline(edited: bytes, baseline_info: dict):
    info = inspect_bmp_bytes(edited)
    if not info["standard"]:
        raise ValueError("artist editable must be a standard BMP beginning with 'BM'")

    keys = ("width", "height", "planes", "bpp", "compression", "palette_entries", "palette_bytes", "row_stride", "pixel_bytes")
    diffs = {k: (baseline_info[k], info[k]) for k in keys if baseline_info[k] != info[k]}
    if diffs:
        raise ValueError(f"artist BMP structure differs from baseline: {diffs}")

    return info


def build_game_bytes(baseline: bytes, edited: bytes):
    binfo = inspect_bmp_bytes(baseline)
    einfo = validate_edited_against_baseline(edited, binfo)

    bstart, bend = binfo["pixel_offset"], binfo["pixel_end"]
    estart, eend = einfo["pixel_offset"], einfo["pixel_end"]
    pixels = edited[estart:eend]
    if len(pixels) != binfo["pixel_bytes"]:
        raise ValueError("artist pixel payload length mismatch")

    out = bytearray(baseline)
    out[bstart:bend] = pixels
    out = bytes(out)

    # Strong invariant: outside the pixel payload every byte must be exactly
    # the registered baseline.
    if out[:bstart] != baseline[:bstart] or out[bend:] != baseline[bend:]:
        raise RuntimeError("non-pixel baseline bytes changed unexpectedly")

    return out, binfo, einfo


def paths_for(root, profile, role, component):
    pid = profile["profile_id"]
    target_name = pathlib.PurePosixPath(component["roundtrip_target"]).name
    stem = pathlib.Path(target_name).stem
    safe_pid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(pid)).strip("._-") or "profile"
    safe_role = re.sub(r"[^A-Za-z0-9._-]+", "_", str(role)).strip("._-") or "texture"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(stem)).strip("._-") or "asset"
    # Artist-editable texture work is isolated under pt_build so normal use no
    # longer creates top-level blender/, textures/ and logs/ trees.
    workspace = root / "pt_build" / "blender_edits" / "character_texture" / safe_pid / safe_role / safe_stem
    texture_root = workspace / "source"
    baseline = texture_root / target_name
    editable = workspace / "editable" / f"{stem}_editable.bmp"
    log_dir = workspace / "logs"
    build_dir = workspace / "builds"
    prep_manifest = log_dir / "texture_prepare_manifest.json"
    latest_build_manifest = log_dir / "latest_texture_build_manifest.json"
    return {
        "workspace": workspace,
        "texture_root": texture_root,
        "baseline": baseline,
        "editable": editable,
        "log_dir": log_dir,
        "build_dir": build_dir,
        "prep_manifest": prep_manifest,
        "latest_build_manifest": latest_build_manifest,
    }


def acquire_baseline(root, profile, role, workspace):
    component = component_for_role(profile, role)
    ws, mp, wm = load_workspace(workspace)
    entry = workspace_entry(wm, component["roundtrip_target"])
    source_sha = entry.get("source_sha256")
    source_size = entry.get("source_size")
    if not source_sha:
        raise ValueError("workspace entry lacks source_sha256")

    paths = paths_for(root, profile, role, component)
    baseline = paths["baseline"]

    if baseline.is_file():
        if sha256_file(baseline) != source_sha:
            raise RuntimeError("immutable texture baseline SHA differs from registered source")
        if source_size is not None and baseline.stat().st_size != int(source_size):
            raise RuntimeError("immutable texture baseline size differs from registered source")
        return component, entry, paths, baseline

    workspace_file = safe_join(ws, entry["workspace_path"])
    if not workspace_file.is_file():
        raise FileNotFoundError(workspace_file)

    current_sha = sha256_file(workspace_file)
    if current_sha != source_sha:
        raise RuntimeError(
            "cannot create immutable baseline: workspace slot no longer contains registered source. "
            "Restore the registered source or provide the baseline before continuing."
        )

    baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(workspace_file, baseline)
    if sha256_file(baseline) != source_sha:
        baseline.unlink(missing_ok=True)
        raise RuntimeError("baseline copy verification failed")
    return component, entry, paths, baseline


def cmd_inspect(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    ws, mp, wm = load_workspace(resolve(root, args.workspace))
    entry = workspace_entry(wm, component["roundtrip_target"])
    wf = safe_join(ws, entry["workspace_path"])
    if not wf.is_file():
        raise FileNotFoundError(wf)
    data = wf.read_bytes()
    info = inspect_bmp_bytes(data)

    print("PT_CHARACTER_TEXTURE_CORE_V1_4")
    print("action=inspect")
    print(f"profile_id={profile['profile_id']}")
    print(f"asset_set_id={profile.get('asset_set_id')}")
    print(f"role={args.role}")
    print(f"asset_id={entry.get('asset_id')}")
    print(f"roundtrip_target={component['roundtrip_target']}")
    print(f"workspace_path={entry['workspace_path']}")
    print(f"workspace_sha256={sha256_file(wf)}")
    print(f"registered_source_sha256={entry.get('source_sha256')}")
    print(f"format={info['format']}")
    print(f"size={info['file_size']}")
    print(f"dimensions={info['width']}x{info['height']}")
    print(f"bpp={info['bpp']}")
    print(f"compression={info['compression']}")
    print(f"pixel_offset={info['pixel_offset']}")
    print(f"pixel_bytes={info['pixel_bytes']}")
    print(f"prefix14_hex={info['prefix14_hex']}")
    print("texture_inspect_check=PASS")


def cmd_prepare(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component, entry, paths, baseline = acquire_baseline(
        root, profile, args.role, resolve(root, args.workspace)
    )
    source = baseline.read_bytes()
    info = inspect_bmp_bytes(source)
    editable_bytes = decode_editable(source, info)

    editable = paths["editable"]
    if editable.exists() and not args.overwrite:
        raise FileExistsError(f"editable texture exists; use --overwrite intentionally: {editable}")
    editable.parent.mkdir(parents=True, exist_ok=True)
    editable.write_bytes(editable_bytes)

    # Decode -> game rebuild must be exact before the artist touches anything.
    noop, _, einfo = build_game_bytes(source, editable_bytes)
    noop_exact = noop == source
    if not noop_exact:
        raise RuntimeError("decode/rebuild no-op is not byte-identical")

    manifest = {
        "tool": "PT_CHARACTER_TEXTURE_CORE_V1_4",
        "prepare_check": "PASS",
        "profile": str(pp),
        "profile_id": profile["profile_id"],
        "asset_set_id": profile.get("asset_set_id"),
        "role": args.role,
        "asset_id": entry.get("asset_id"),
        "roundtrip_target": component["roundtrip_target"],
        "workspace_path": entry["workspace_path"],
        "baseline": str(baseline),
        "baseline_size": baseline.stat().st_size,
        "baseline_sha256": sha256_file(baseline),
        "source_format": info,
        "editable": str(editable),
        "editable_size": editable.stat().st_size,
        "editable_sha256": sha256_file(editable),
        "editable_format": einfo,
        "noop_byte_identical": True,
        "runtime_installed": False,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(paths["prep_manifest"], manifest)

    print("PT_CHARACTER_TEXTURE_CORE_V1_4")
    print("action=prepare")
    print(f"profile_id={profile['profile_id']}")
    print(f"role={args.role}")
    print(f"asset_id={entry.get('asset_id')}")
    print(f"format={info['format']}")
    print(f"baseline={baseline}")
    print(f"baseline_sha256={manifest['baseline_sha256']}")
    print(f"editable={editable}")
    print(f"editable_sha256={manifest['editable_sha256']}")
    print("noop_byte_identical=True")
    print(f"manifest={paths['prep_manifest']}")
    print("texture_prepare_check=PASS")


def cmd_build(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    paths = paths_for(root, profile, args.role, component)
    if not paths["prep_manifest"].is_file():
        raise FileNotFoundError(
            f"prepare manifest missing; run texture-prepare first: {paths['prep_manifest']}"
        )
    prep = load_json(paths["prep_manifest"])
    if prep.get("prepare_check") != "PASS":
        raise ValueError("prepare manifest is not PASS")

    baseline = pathlib.Path(prep["baseline"]).resolve()
    if not baseline.is_file():
        raise FileNotFoundError(baseline)
    if sha256_file(baseline) != prep["baseline_sha256"]:
        raise RuntimeError("baseline changed since prepare")

    edited = resolve(root, args.edited) if args.edited else pathlib.Path(prep["editable"]).resolve()
    if not edited.is_file():
        raise FileNotFoundError(edited)

    baseline_bytes = baseline.read_bytes()
    edited_bytes = edited.read_bytes()
    out_bytes, binfo, einfo = build_game_bytes(baseline_bytes, edited_bytes)

    bstart, bend = binfo["pixel_offset"], binfo["pixel_end"]
    estart, eend = einfo["pixel_offset"], einfo["pixel_end"]
    old_pixels = baseline_bytes[bstart:bend]
    new_pixels = edited_bytes[estart:eend]
    changed_pixel_bytes = sum(a != b for a, b in zip(old_pixels, new_pixels))

    name = args.name or f"{pathlib.Path(component['roundtrip_target']).stem}_texture_build"
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        raise ValueError("unsafe --name")
    out = paths["build_dir"] / f"{name}{pathlib.Path(component['roundtrip_target']).suffix}"
    report = paths["log_dir"] / f"{name}_texture_build_manifest.json"
    if out.exists() and not args.overwrite:
        raise FileExistsError(f"texture build exists; use --overwrite: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(out_bytes)

    # Verify game artifact and immutable header/non-pixel region.
    verify = out.read_bytes()
    if verify[:bstart] != baseline_bytes[:bstart] or verify[bend:] != baseline_bytes[bend:]:
        raise RuntimeError("built game texture changed non-pixel bytes")

    manifest = {
        "tool": "PT_CHARACTER_TEXTURE_CORE_V1_4",
        "build_check": "PASS",
        "profile": str(pp),
        "profile_id": profile["profile_id"],
        "asset_set_id": profile.get("asset_set_id"),
        "role": args.role,
        "roundtrip_target": component["roundtrip_target"],
        "artifact": str(out),
        "artifact_size": out.stat().st_size,
        "artifact_sha256": sha256_file(out),
        "baseline": str(baseline),
        "baseline_size": baseline.stat().st_size,
        "baseline_sha256": sha256_file(baseline),
        "edited": str(edited),
        "edited_size": edited.stat().st_size,
        "edited_sha256": sha256_file(edited),
        "format": binfo["format"],
        "width": binfo["width"],
        "height": binfo["height"],
        "bpp": binfo["bpp"],
        "pixel_offset": binfo["pixel_offset"],
        "pixel_bytes": binfo["pixel_bytes"],
        "changed_pixel_bytes": changed_pixel_bytes,
        "non_pixel_bytes_preserved_exactly": True,
        "noop_build": changed_pixel_bytes == 0,
        "runtime_installed": False,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(report, manifest)
    write_json(paths["latest_build_manifest"], manifest)

    print("PT_CHARACTER_TEXTURE_CORE_V1_4")
    print("action=build")
    print(f"profile_id={profile['profile_id']}")
    print(f"role={args.role}")
    print(f"artifact={out}")
    print(f"artifact_size={manifest['artifact_size']}")
    print(f"artifact_sha256={manifest['artifact_sha256']}")
    print(f"changed_pixel_bytes={changed_pixel_bytes}")
    print("non_pixel_bytes_preserved_exactly=True")
    print(f"noop_build={str(manifest['noop_build'])}")
    print(f"manifest={report}")
    print("texture_build_check=PASS")


def blender_command():
    raw = os.environ.get("PT_BLENDER_COMMAND")
    if raw:
        return shlex.split(raw)
    return ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]


def run_checked(cmd):
    print("COMMAND=" + " ".join(shlex.quote(str(x)) for x in cmd))
    subprocess.run(cmd, check=True)


def cmd_bind_blend(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    paths = paths_for(root, profile, args.role, component)
    if not paths["prep_manifest"].is_file():
        raise FileNotFoundError("run texture-prepare first")
    prep = load_json(paths["prep_manifest"])
    texture = resolve(root, args.texture) if args.texture else pathlib.Path(prep["editable"]).resolve()
    blend = resolve(root, args.artist)
    out = resolve(root, args.out)
    helper = root / "pt_blender_bind_editable_texture_v2.py"
    if not helper.is_file():
        raise FileNotFoundError(helper)
    if not blend.is_file():
        raise FileNotFoundError(blend)
    if not texture.is_file():
        raise FileNotFoundError(texture)
    if out.exists() and not args.overwrite:
        raise FileExistsError(f"output blend exists; use --overwrite: {out}")

    source_name = pathlib.PurePosixPath(component["roundtrip_target"]).name
    cmd = blender_command() + [
        "--background", str(blend),
        "--python-exit-code", "1",
        "--python", str(helper), "--",
        "--source-basename", source_name,
        "--texture", str(texture),
        "--out", str(out),
    ]
    for material_slot in component.get("material_slots", []):
        cmd += ["--material-slot", str(int(material_slot))]
    if args.overwrite:
        cmd.append("--overwrite")
    run_checked(cmd)
    print("texture_bind_blend_check=PASS")


def resolve_build_manifest(root, profile, role, manifest_arg=None):
    component = component_for_role(profile, role)
    paths = paths_for(root, profile, role, component)
    mp = resolve(root, manifest_arg) if manifest_arg else paths["latest_build_manifest"]
    if not mp.is_file():
        raise FileNotFoundError(mp)
    m = load_json(mp)
    if m.get("build_check") != "PASS":
        raise ValueError("texture build manifest is not PASS")
    if m.get("profile_id") != profile["profile_id"] or m.get("role") != role:
        raise ValueError("texture build manifest profile/role mismatch")
    artifact = pathlib.Path(m["artifact"]).expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if sha256_file(artifact) != m["artifact_sha256"]:
        raise RuntimeError("texture artifact SHA differs from build manifest")
    if artifact.stat().st_size != int(m["artifact_size"]):
        raise RuntimeError("texture artifact size differs from build manifest")
    return mp, m, artifact


def cmd_publish(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    workspace = resolve(root, args.workspace)
    manifest, m, artifact = resolve_build_manifest(
        root, profile, args.role, args.build_manifest
    )
    bridge = root / "summit_workspace_asset_bridge_v1_2.py"
    if not bridge.is_file():
        raise FileNotFoundError(bridge)

    cmd = [
        sys.executable, str(bridge), "publish-file",
        str(workspace),
        "--build-manifest", str(manifest),
        "--target", component["roundtrip_target"],
    ]
    if args.replace_published:
        cmd.append("--replace-published")
    run_checked(cmd)
    print("texture_publish_check=PASS")


def cmd_deploy(args, apply):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    workspace = resolve(root, args.workspace)
    restore = root / "summit_roundtrip_restore_v4.py"
    if not restore.is_file():
        raise FileNotFoundError(restore)
    cmd = [
        sys.executable, str(restore), str(workspace),
        "--target", component["roundtrip_target"],
    ]
    if apply:
        cmd.append("--apply")
    run_checked(cmd)
    print("texture_deploy_check=PASS" if apply else "texture_deploy_plan_check=PASS")


def cmd_status(args):
    root = args.root.resolve()
    pp, profile = load_profile(root, args.profile)
    component = component_for_role(profile, args.role)
    ws, mp, wm = load_workspace(resolve(root, args.workspace))
    entry = workspace_entry(wm, component["roundtrip_target"])
    wf = safe_join(ws, entry["workspace_path"])
    wsha = sha256_file(wf) if wf.is_file() else None

    current_pub = entry.get("published_build") or {}
    source_sha = entry.get("source_sha256")
    if wsha == source_sha:
        wstate = "REGISTERED_SOURCE"
    elif current_pub.get("sha256") == wsha:
        wstate = "CURRENT_PUBLISHED_BUILD"
    else:
        wstate = "WORKSPACE_DRIFT"

    game_root = pathlib.Path(wm["game_root"]).expanduser().resolve()
    cf = safe_join(game_root, component["roundtrip_target"])
    csha = sha256_file(cf) if cf.is_file() else None
    managed = {source_sha}
    if current_pub.get("sha256"):
        managed.add(current_pub["sha256"])
    for item in entry.get("published_history", []) or []:
        if item.get("sha256"):
            managed.add(item["sha256"])
    if csha == source_sha:
        cstate = "REGISTERED_SOURCE"
    elif current_pub.get("sha256") == csha:
        cstate = "CURRENT_PUBLISHED_BUILD"
    elif csha in managed:
        cstate = "PREVIOUSLY_PUBLISHED_BUILD"
    else:
        cstate = "CLIENT_DRIFT"

    check = "PASS" if wstate != "WORKSPACE_DRIFT" and cstate != "CLIENT_DRIFT" else "FAIL"
    print("PT_CHARACTER_TEXTURE_CORE_V1_4")
    print("action=status")
    print(f"profile_id={profile['profile_id']}")
    print(f"role={args.role}")
    print(f"asset_id={entry.get('asset_id')}")
    print(f"roundtrip_target={component['roundtrip_target']}")
    print(f"workspace_state={wstate}")
    print(f"workspace_sha256={wsha}")
    print(f"client_state={cstate}")
    print(f"client_sha256={csha}")
    print(f"registered_source_sha256={source_sha}")
    print(f"current_published_sha256={current_pub.get('sha256')}")
    print(f"texture_status_check={check}")
    if check != "PASS":
        raise SystemExit(2)


def parser():
    root_default = pathlib.Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=pathlib.Path, default=root_default)
    p.add_argument(
        "--profile",
        default="profiles/pt_character_profile_pikeman_c01_m5_v2.json",
    )
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("inspect")
    i.add_argument("--workspace", required=True)
    i.add_argument("--role", default="texture")
    i.set_defaults(func=cmd_inspect)

    pr = sub.add_parser("prepare")
    pr.add_argument("--workspace", required=True)
    pr.add_argument("--role", default="texture")
    pr.add_argument("--overwrite", action="store_true")
    pr.set_defaults(func=cmd_prepare)

    b = sub.add_parser("build")
    b.add_argument("--role", default="texture")
    b.add_argument("--edited")
    b.add_argument("--name")
    b.add_argument("--overwrite", action="store_true")
    b.set_defaults(func=cmd_build)

    bb = sub.add_parser("bind-blend")
    bb.add_argument("--role", default="texture")
    bb.add_argument("--artist", required=True)
    bb.add_argument("--texture")
    bb.add_argument("--out", required=True)
    bb.add_argument("--overwrite", action="store_true")
    bb.set_defaults(func=cmd_bind_blend)

    pub = sub.add_parser("publish")
    pub.add_argument("--workspace", required=True)
    pub.add_argument("--role", default="texture")
    pub.add_argument("--build-manifest")
    pub.add_argument("--replace-published", action="store_true")
    pub.set_defaults(func=cmd_publish)

    st = sub.add_parser("status")
    st.add_argument("--workspace", required=True)
    st.add_argument("--role", default="texture")
    st.set_defaults(func=cmd_status)

    dp = sub.add_parser("deploy-plan")
    dp.add_argument("--workspace", required=True)
    dp.add_argument("--role", default="texture")
    dp.set_defaults(func=lambda a: cmd_deploy(a, False))

    de = sub.add_parser("deploy")
    de.add_argument("--workspace", required=True)
    de.add_argument("--role", default="texture")
    de.set_defaults(func=lambda a: cmd_deploy(a, True))

    return p


def main():
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"texture_core_check=FAIL: {type(exc).__name__}: {exc}")
        raise
