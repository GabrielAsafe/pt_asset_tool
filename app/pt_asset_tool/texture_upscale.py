from __future__ import annotations

import argparse
import collections
import fnmatch
import hashlib
import io
import json
import os
import secrets
import shutil
import struct
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image, ImageFilter, ImageStat
except Exception as exc:  # pragma: no cover - environment-specific
    Image = None
    ImageFilter = None
    ImageStat = None
    _PIL_IMPORT_ERROR = exc
else:
    _PIL_IMPORT_ERROR = None

from pt_protected_tga_v1 import (
    decode_bytes as decode_tga_bytes,
    inspect_bytes as inspect_tga_bytes,
    protect_header as protect_tga_header,
)
from pt_character_texture_v1_4 import (
    decode_editable as decode_bmp_editable,
    inspect_bmp_bytes,
)
from .rare_outliers import SHIP_BMP_DIB40_KEY, TGA_KEY, _probe_tga, _tga_decode_header
from .rare_support import decode_ship_bmp_bytes

TOOL = "PT_TEXTURE_UPSCALE_V3"
ENHANCEMENT_PUBLISH_CONFIRM = "APPLY CLIENT ENHANCEMENT"
ENHANCEMENT_RESTORE_CONFIRM = "RESTORE CLIENT ENHANCEMENT"
ENHANCEMENT_BATCH_PUBLISH_CONFIRM = "APPLY CLIENT ENHANCEMENT BATCH"
ENHANCEMENT_BATCH_RESTORE_CONFIRM = "RESTORE CLIENT ENHANCEMENT BATCH"
QUALITY_PROFILES = ("faithful", "balanced", "detail", "pixel-art")
PILLOW_AVAILABLE = Image is not None
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SUFFIXES = {".tga", ".bmp", ".png", ".jpg", ".jpeg"}

# Deliberately conservative. Old 2D/UI consumers may use source rectangles in
# pixel coordinates; resizing an atlas without changing those coordinates can
# alter which sub-region is sampled even when the image itself loads correctly.
DEFAULT_UI_RISK_PATTERNS = (
    "*/ui/*",
    "*/interface/*",
    "*/interfaces/*",
    "*/login/*",
    "*/startimage/*",
    "*/clanimage/*",
    "*/sinimage/help/*",
    "*/sinimage/messagebox/*",
    "*/sinimage/chipbutton/*",
    "*/font/*",
    "*/fonts/*",
    "*/cursor/*",
    "*/cursors/*",
)

# These paths are commonly consumed as world/model/effect textures. This is a
# useful risk label, not a proof that a specific file has only normalized-UV
# consumers; validation in the game is still required before promotion.
THREE_D_CANDIDATE_PATTERNS = (
    "*/char/*",
    "*/field/*",
    "*/effect/*",
    "*/effects/*",
    "*/terrain/*",
    "*/map/*",
    "*/maps/*",
)


def _need_pillow() -> None:
    if Image is None:
        raise RuntimeError(
            "Pillow is required for texture upscale. Install with: python -m pip install Pillow"
        ) from _PIL_IMPORT_ERROR


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _runtime_decrypt_tga(data: bytes) -> bytes:
    """Exact header transform used by the supplied Summit client format."""
    if len(data) < 18:
        raise ValueError("TGA too small")
    out = bytearray(data)
    if out[0] == ord("G") and out[1] == ord("8"):
        out[0] = 0
        out[1] = 0
        for c in range(2, 18):
            out[c] = (out[c] - (c * c)) & 0xFF
    return bytes(out)


def _runtime_g8_candidate(raw: bytes) -> tuple[bytes, dict] | None:
    """Recognize the exact legacy G8 header transform using a decode witness.

    Some shipped DropItem TGAs are accepted by the client runtime transform and
    Pillow after deprotection, while their historical container/trailer shape is
    intentionally outside rare_outliers' exact-layout census.  This bridge is
    therefore limited to the literal G8 signature and requires the decoded TGA
    header and Pillow's full decode to agree on dimensions.
    """
    if len(raw) < 18 or raw[:2] != b"G8":
        return None
    decoded = _runtime_decrypt_tga(raw)
    if decoded[0] != 0 or decoded[1] != 0 or decoded[2] not in (2, 10):
        return None
    width = int.from_bytes(decoded[12:14], "little")
    height = int.from_bytes(decoded[14:16], "little")
    depth = decoded[16]
    if width <= 0 or height <= 0 or depth not in (24, 32):
        return None
    _need_pillow()
    try:
        with Image.open(io.BytesIO(decoded)) as im:
            im.load()
            if im.format != "TGA" or im.size != (width, height):
                return None
    except Exception:
        return None
    return decoded, {
        "rare_tga": {
            "classification": "TGA_PROTECTED_G8_RUNTIME_DECODE_WITNESS",
            "protection_mode": "G8_RUNTIME",
            "decoded_width": width,
            "decoded_height": height,
            "pixel_depth": depth,
            "source_tga20_footer": len(raw) >= 26 and raw[-18:] == b"TRUEVISION-XFILE.\x00",
        },
        "protection_mode": "G8_RUNTIME",
    }


def _protect_tga_g8_runtime(standard: bytes, source_raw: bytes) -> bytes:
    """Rebuild a resized G8-runtime TGA using the exact reversible header transform."""
    if len(standard) < 18:
        raise ValueError("generated TGA too small")
    out = bytearray(protect_tga_header(standard[:18], "FULL18") + standard[18:])
    # Keep the old/no-footer shape when the source did not carry a TGA2 footer.
    # The runtime image loader does not require Pillow's generated footer.
    source_footer = len(source_raw) >= 26 and source_raw[-18:] == b"TRUEVISION-XFILE.\x00"
    generated_footer = len(out) >= 26 and bytes(out[-18:]) == b"TRUEVISION-XFILE.\x00"
    if not source_footer and generated_footer:
        del out[-26:]
    if out[:2] != b"G8":
        raise RuntimeError("G8 header rebuild invariant failed")
    return bytes(out)


def _rare_tga_decode_for_upscale(raw: bytes) -> tuple[bytes, dict] | None:
    """Decode only rare TGA families already proven by the physical-corpus audit.

    This is deliberately a bridge to rare_outliers, not a permissive image guess.
    Preview-only/corrupt/non-image classifications remain fail-closed.
    """
    probe = _probe_tga(raw)
    cls = str(probe.get("classification") or "")
    if cls == "TGA_STANDARD_TRUECOLOR":
        return raw, {"rare_tga": probe, "protection_mode": None}
    if cls.startswith("TGA_PROTECTED_"):
        mode = str(probe.get("protection_mode") or "")
        if mode in {"FULL18", "KEEP_00_16", "DIMENSIONS_12_15"}:
            decoded_header = _tga_decode_header(raw[:18], mode)
            return decoded_header + raw[18:], {"rare_tga": probe, "protection_mode": mode}
    # Final narrow bridge for the literal runtime G8 family.  Do this only after
    # the exact physical-corpus classifier has declined the file.
    return _runtime_g8_candidate(raw)


def _protect_tga_dimensions_12_15(standard: bytes, source_meta: dict | None) -> bytes:
    if len(standard) < 18:
        raise ValueError("generated TGA too small")
    out = bytearray(standard)
    for i in range(12, 16):
        out[i] = (out[i] + TGA_KEY[i]) & 0xFF
    # Preserve the physically proven old-TGA/no-footer container shape when the
    # source belongs to that exact subfamily. Pillow emits a TGA2 footer by default.
    rare = (source_meta or {}).get("rare_tga") or {}
    if str(rare.get("container_variant") or "") == "TGA1_STYLE_NO_FOOTER_EXACT_PAYLOAD":
        if len(out) >= 26 and bytes(out[-18:]) == b"TRUEVISION-XFILE.\x00":
            del out[-26:]
    return bytes(out)


def _encode_ship_bmp_resized(standard_bmp: bytes, baseline: bytes) -> bytes:
    """Encode a resized member of the proven chrselect ship BMP family.

    The first 14 bytes use the SourceCode transform and the 40-byte DIB uses the
    independently recovered physical family key. Pixel bytes are standard 24-bpp
    BMP bytes; the family-required two trailing zero bytes are retained.
    """
    if len(standard_bmp) < 54 or standard_bmp[:2] != b"BM":
        raise ValueError("standard BMP output required for ship family")
    dib = struct.unpack_from("<I", standard_bmp, 14)[0]
    width = struct.unpack_from("<i", standard_bmp, 18)[0]
    height = struct.unpack_from("<i", standard_bmp, 22)[0]
    planes = struct.unpack_from("<H", standard_bmp, 26)[0]
    bpp = struct.unpack_from("<H", standard_bmp, 28)[0]
    compression = struct.unpack_from("<I", standard_bmp, 30)[0]
    image_size = struct.unpack_from("<I", standard_bmp, 34)[0]
    offbits = struct.unpack_from("<I", standard_bmp, 10)[0]
    if not (dib == 40 and width > 0 and height > 0 and planes == 1 and bpp == 24 and compression == 0 and offbits == 54):
        raise ValueError("resized ship BMP is not canonical 24-bpp DIB40")
    expected_pixels = width * height * 3
    if image_size != expected_pixels or offbits + image_size != len(standard_bmp):
        raise ValueError("resized ship BMP payload layout differs from proven family")
    if len(baseline) < 56 or baseline[:2] == b"BM":
        raise ValueError("protected ship BMP baseline required")

    # Standard-equivalent form includes the two physical family trailer bytes and
    # advertises that physical size. decode_ship_bmp_bytes normalizes bfSize the
    # same way, giving us an exact roundtrip witness below.
    std = bytearray(standard_bmp + b"\0\0")
    struct.pack_into("<I", std, 2, len(std))
    out = bytearray(std)
    out[:2] = baseline[:2]
    for c in range(2, 14):
        out[c] = (std[c] + (c * c)) & 0xFF
    for i, key in enumerate(SHIP_BMP_DIB40_KEY):
        out[14 + i] = (std[14 + i] + key) & 0xFF

    rebuilt = bytes(out)
    decoded, _ = decode_ship_bmp_bytes(rebuilt)
    if decoded != bytes(std):
        raise RuntimeError("resized ship BMP protected roundtrip mismatch")
    return rebuilt

def _runtime_encrypt_bmp_header(standard_bmp: bytes, protected_prefix: bytes) -> bytes:
    """Create a BMP prefix inverse-compatible with the client DecryptBMP path."""
    if len(standard_bmp) < 14 or standard_bmp[:2] != b"BM":
        raise ValueError("standard BMP header required")
    if len(protected_prefix) < 2 or protected_prefix[:2] == b"BM":
        raise ValueError("protected BMP baseline marker required")
    out = bytearray(standard_bmp)
    out[0:2] = protected_prefix[:2]
    for c in range(2, 14):
        out[c] = (standard_bmp[c] + (c * c)) & 0xFF
    return bytes(out)


def _runtime_decrypt_bmp(data: bytes) -> bytes:
    """Python equivalent of the client DecryptBMP header transform."""
    if len(data) < 14:
        raise ValueError("BMP too small")
    out = bytearray(data)
    if out[:2] != b"BM":
        out[0:2] = b"BM"
        for c in range(2, 14):
            out[c] = (out[c] - (c * c)) & 0xFF
    out[2:6] = b"\0\0\0\0"
    return bytes(out)


@dataclass
class TextureRecord:
    source: str
    suffix: str
    format: str | None = None
    protected: bool = False
    protection_mode: str | None = None
    width: int | None = None
    height: int | None = None
    mode: str | None = None
    has_alpha: bool | None = None
    risk_class: str | None = None
    source_sha256: str | None = None
    source_unchanged: bool | None = None
    output: str | None = None
    output_sha256: str | None = None
    output_width: int | None = None
    output_height: int | None = None
    status: str = "pending"
    reason: str | None = None
    elapsed_seconds: float | None = None
    quality_profile: str | None = None
    backend_used: str | None = None
    backend_decision: str | None = None
    ai_enhancement_used: bool | None = None
    detail_metric_before: float | None = None
    detail_metric_after: float | None = None
    detail_gain_ratio: float | None = None


def _open_from_bytes(data: bytes, *, force_mode: str | None = None):
    _need_pillow()
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if force_mode:
            return im.convert(force_mode)
        return im.copy()


def inspect_texture(path: Path) -> tuple[TextureRecord, object | None]:
    _need_pillow()
    raw = path.read_bytes()
    rec = TextureRecord(
        source=str(path),
        suffix=path.suffix.lower(),
        source_sha256=sha256_bytes(raw),
    )
    meta: object | None = None

    if rec.suffix == ".tga":
        try:
            info = inspect_tga_bytes(raw)
            decoded, _ = decode_tga_bytes(raw)
            im = _open_from_bytes(decoded)
            rec.format = str(info["format"])
            rec.protected = bool(info["protected"])
            rec.protection_mode = info.get("protection_mode")
            meta = info
        except Exception:
            rare = _rare_tga_decode_for_upscale(raw)
            if rare is None:
                raise
            decoded, rare_meta = rare
            im = _open_from_bytes(decoded)
            mode = rare_meta.get("protection_mode")
            rec.format = "TGA_RARE_PHYSICAL_COMPAT"
            rec.protected = bool(mode)
            rec.protection_mode = mode
            meta = rare_meta
    elif rec.suffix == ".bmp":
        try:
            info = inspect_bmp_bytes(raw)
            decoded = decode_bmp_editable(raw, info)
            im = _open_from_bytes(decoded)
            rec.format = str(info["format"])
            rec.protected = not bool(info["standard"])
            meta = info
        except Exception as strict_error:
            # First try the independently proven chrselect ship protected family.
            # It is not a generic non-BM fallback: decode_ship_bmp_bytes closes
            # every header/payload/trailer invariant before returning.
            try:
                decoded, ship_meta = decode_ship_bmp_bytes(raw)
            except Exception:
                ship_meta = None
            if ship_meta is not None:
                im = _open_from_bytes(decoded)
                rec.format = "BMP_SHIP_DIB40_PROTECTED_EXACT"
                rec.protected = True
                rec.protection_mode = "SHIP_DIB40"
                meta = {"ship_meta": ship_meta}
            else:
                # Compatibility bridge for ordinary BM files that are fully
                # decodable by Pillow but fall outside the conservative legacy
                # adapter (for example stale bfSize fields or BITMAPV4/V5 DIBs).
                # Other non-BM proprietary/rare families remain fail-closed.
                if raw[:2] != b"BM":
                    raise strict_error
                im = _open_from_bytes(raw)
                rec.format = "BMP_STANDARD_PILLOW_COMPAT"
                rec.protected = False
                meta = {
                    "codec_bridge": "pillow_standard_bmp",
                    "strict_error": f"{type(strict_error).__name__}: {strict_error}",
                }
    else:
        im = _open_from_bytes(raw)
        rec.format = rec.suffix.lstrip(".").upper()

    rec.width, rec.height = im.size
    rec.mode = im.mode
    bands = im.getbands()
    rec.has_alpha = "A" in bands or (im.mode == "P" and "transparency" in im.info)
    return rec, meta


def decode_texture(path: Path, rec: TextureRecord, meta: object | None):
    raw = path.read_bytes()
    if rec.suffix == ".tga":
        if rec.format == "TGA_RARE_PHYSICAL_COMPAT":
            rare = _rare_tga_decode_for_upscale(raw)
            if rare is None:
                raise ValueError("rare TGA family no longer validates")
            decoded, _ = rare
        else:
            decoded, _ = decode_tga_bytes(raw)
        return _open_from_bytes(decoded).convert("RGBA" if rec.has_alpha else "RGB")
    if rec.suffix == ".bmp":
        if rec.format == "BMP_STANDARD_PILLOW_COMPAT":
            decoded = raw
        elif rec.format == "BMP_SHIP_DIB40_PROTECTED_EXACT":
            decoded, _ = decode_ship_bmp_bytes(raw)
        else:
            decoded = decode_bmp_editable(raw, meta)  # type: ignore[arg-type]
        return _open_from_bytes(decoded).convert("RGBA" if rec.has_alpha else "RGB")
    return _open_from_bytes(raw).convert("RGBA" if rec.has_alpha else "RGB")


def _save_standard_bytes(image, suffix: str, *, jpeg_quality: int = 95) -> bytes:
    _need_pillow()
    buf = io.BytesIO()
    if suffix == ".tga":
        image.save(buf, format="TGA", compression=None)
    elif suffix == ".bmp":
        # The runtime treats BMP as opaque. RGB avoids ambiguous BMP alpha
        # semantics across D3DX implementations.
        image.convert("RGB").save(buf, format="BMP")
    elif suffix == ".png":
        image.save(buf, format="PNG", optimize=False)
    elif suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality, subsampling=0)
    else:
        raise ValueError(f"unsupported output suffix: {suffix}")
    return buf.getvalue()


def encode_texture(image, source_raw: bytes, rec: TextureRecord, meta: object | None) -> bytes:
    standard = _save_standard_bytes(image, rec.suffix)
    if rec.suffix == ".tga" and rec.protected:
        if len(standard) < 18:
            raise ValueError("generated TGA too small")
        if rec.protection_mode == "DIMENSIONS_12_15":
            return _protect_tga_dimensions_12_15(standard, meta if isinstance(meta, dict) else None)
        if rec.protection_mode == "G8_RUNTIME":
            return _protect_tga_g8_runtime(standard, source_raw)
        mode = rec.protection_mode if rec.protection_mode in {"FULL18", "KEEP_00_16"} else "FULL18"
        return protect_tga_header(standard[:18], mode) + standard[18:]
    if rec.suffix == ".bmp" and rec.protected:
        if rec.protection_mode == "SHIP_DIB40":
            return _encode_ship_bmp_resized(standard, source_raw)
        return _runtime_encrypt_bmp_header(standard, source_raw[:14])
    return standard


def _alpha_channel(image, size: tuple[int, int]):
    _need_pillow()
    if "A" not in image.getbands():
        return None
    return image.getchannel("A").resize(size, Image.Resampling.LANCZOS)


def _detail_metric(image) -> float:
    """Small deterministic edge-energy witness; informative, never a quality gate."""
    _need_pillow()
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    return round(float(stat.rms[0] if stat.rms else 0.0), 6)


def _apply_quality_profile(image, profile: str, *, ai_backend: bool = False):
    _need_pillow()
    profile = str(profile or "balanced").lower()
    if profile not in QUALITY_PROFILES:
        raise ValueError(f"unknown quality profile: {profile}")
    if profile in {"faithful", "pixel-art"}:
        return image
    if profile == "balanced":
        percent = 105 if ai_backend else 112
        radius = 0.8 if ai_backend else 1.0
        threshold = 3
    else:  # detail
        percent = 118 if ai_backend else 145
        radius = 1.0 if ai_backend else 1.2
        threshold = 2
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    base = image.convert("RGB").filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))
    if alpha is not None:
        base = base.convert("RGBA")
        base.putalpha(alpha)
    return base


def upscale_lanczos(image, scale: int, *, profile: str = "balanced"):
    _need_pillow()
    target = (image.width * scale, image.height * scale)
    resampling = Image.Resampling.NEAREST if profile == "pixel-art" else Image.Resampling.LANCZOS
    result = image.resize(target, resampling)
    return _apply_quality_profile(result, profile, ai_backend=False)


def _resolve_realesrgan(executable: str | None) -> str:
    if executable:
        p = Path(executable).expanduser()
        if p.is_file():
            return str(p.resolve())
        found = shutil.which(executable)
        if found:
            return found
        raise FileNotFoundError(f"Real-ESRGAN executable not found: {executable}")
    for name in ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan.exe"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "realesrgan-ncnn-vulkan was not found. Install it or pass --realesrgan /path/to/realesrgan-ncnn-vulkan"
    )


def capability_status(executable: str | None = None) -> dict:
    pillow_ready = PILLOW_AVAILABLE
    realesrgan_path = None
    realesrgan_error = None
    try:
        realesrgan_path = _resolve_realesrgan(executable)
    except Exception as exc:
        realesrgan_error = f"{type(exc).__name__}:{exc}"
    return {
        "pillow_ready": pillow_ready,
        "pillow_error": None if pillow_ready else f"{type(_PIL_IMPORT_ERROR).__name__}:{_PIL_IMPORT_ERROR}",
        "lanczos_ready": pillow_ready,
        "realesrgan_ready": bool(pillow_ready and realesrgan_path),
        "realesrgan_executable": realesrgan_path,
        "realesrgan_error": realesrgan_error,
        "supported_suffixes": sorted(SUPPORTED_SUFFIXES),
        "quality_profiles": list(QUALITY_PROFILES),
        "auto_backend_ready": pillow_ready,
        "auto_profile_policy": {
            "faithful": "lanczos_preserve",
            "balanced": "lanczos_conservative",
            "detail": "realesrgan_if_available_else_lanczos",
            "pixel-art": "nearest_neighbour",
        },
    }


def upscale_realesrgan(
    image,
    *,
    scale: int,
    executable: str | None,
    model: str,
    tile: int,
    gpu: int,
    profile: str = "balanced",
) -> tuple[object, list[str]]:
    _need_pillow()
    exe = _resolve_realesrgan(executable)
    target = (image.width * scale, image.height * scale)
    original_alpha = _alpha_channel(image, target)

    with tempfile.TemporaryDirectory(prefix="pt_upscale_") as td:
        inp = Path(td) / "input.png"
        out = Path(td) / "output.png"
        image.save(inp, format="PNG")
        cmd = [
            exe,
            "-i", str(inp),
            "-o", str(out),
            "-n", model,
            "-s", str(scale),
            "-t", str(tile),
            "-g", str(gpu),
            "-f", "png",
        ]
        cp = subprocess.run(cmd, text=True, capture_output=True, cwd=str(Path(exe).resolve().parent))
        if cp.returncode != 0 or not out.is_file():
            detail = (cp.stderr or cp.stdout or "unknown Real-ESRGAN failure").strip()
            raise RuntimeError(f"Real-ESRGAN failed ({cp.returncode}): {detail}")
        result = _open_from_bytes(out.read_bytes()).convert("RGBA" if original_alpha is not None else "RGB")

    if result.size != target:
        raise RuntimeError(f"upscaler returned {result.size}, expected {target}")
    if original_alpha is not None:
        result.putalpha(original_alpha)
    result = _apply_quality_profile(result, profile, ai_backend=True)
    return result, cmd


def _matches_any(rel: str, patterns: Iterable[str]) -> bool:
    rel_norm = "/" + rel.replace("\\", "/").strip("/").lower()
    for pattern in patterns:
        pat = str(pattern).replace("\\", "/").strip().lower()
        if pat and not pat.startswith(("/", "*")):
            pat = "/" + pat.lstrip("/")
        if pat and fnmatch.fnmatch(rel_norm, pat):
            return True
    return False


def _risk_class(rel: str) -> str:
    if _matches_any(rel, DEFAULT_UI_RISK_PATTERNS):
        return "UI_ATLAS_RISK"
    if _matches_any(rel, THREE_D_CANDIDATE_PATTERNS):
        return "THREE_D_TEXTURE_CANDIDATE"
    return "UNKNOWN_USAGE_RISK"


def iter_textures(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES:
            yield p


def _selected(rel: str, include_patterns: list[str], include_exact: list[str]) -> bool:
    if not include_patterns and not include_exact:
        return True
    rel_key = rel.replace("\\", "/").strip("/").lower()
    exact = {x.replace("\\", "/").strip("/").lower() for x in include_exact}
    return rel_key in exact or _matches_any(rel, include_patterns)


def _is_within(root: Path, path: Path) -> bool:
    root = root.resolve()
    path = path.resolve()
    return path == root or root in path.parents


def _ensure_outside_source(root: Path, path: Path, label: str) -> None:
    if _is_within(root, path):
        raise ValueError(f"{label} must be outside the source/client root: {path}")


def _json_dump(path: Path, payload: dict, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_publish(path, data, overwrite=overwrite)


def _atomic_publish(path: Path, data: bytes, *, overwrite: bool) -> None:
    """Publish complete bytes atomically; do not overwrite unless explicitly allowed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise FileExistsError(f"output already exists: {path}")
            finally:
                tmp.unlink(missing_ok=True)
    finally:
        tmp.unlink(missing_ok=True)


def scan_tree(
    root: Path,
    *,
    include_ui: bool,
    extra_excludes: list[str],
    include_patterns: list[str] | None = None,
    include_exact: list[str] | None = None,
) -> dict:
    root = root.resolve()
    include_patterns = list(include_patterns or [])
    include_exact = list(include_exact or [])
    records: list[dict] = []
    counts: dict[str, int] = {}
    for path in iter_textures(root):
        rel = path.relative_to(root).as_posix()
        if not _selected(rel, include_patterns, include_exact):
            continue
        try:
            rec, _ = inspect_texture(path)
            rec.source = rel
            rec.risk_class = _risk_class(rel)
            rec.source_unchanged = True
            if not include_ui and rec.risk_class == "UI_ATLAS_RISK":
                rec.status = "skipped_ui_pixel_crop_risk"
                rec.reason = "path matches conservative UI/atlas exclusion"
            elif extra_excludes and _matches_any(rel, extra_excludes):
                rec.status = "skipped_pattern"
                rec.reason = "path matches --exclude"
            else:
                rec.status = "ready"
        except Exception as exc:
            rec = TextureRecord(
                source=rel,
                suffix=path.suffix.lower(),
                risk_class=_risk_class(rel),
                status="unsupported_or_invalid",
                reason=f"{type(exc).__name__}: {exc}",
            )
        records.append(asdict(rec))
        counts[rec.status] = counts.get(rec.status, 0) + 1
    return {
        "tool": TOOL,
        "action": "scan",
        "root": str(root),
        "include_patterns": include_patterns,
        "include_exact": include_exact,
        "texture_count": len(records),
        "status_counts": counts,
        "records": records,
        "source_write_attempted": False,
        "source_client_modified": False,
    }


def upscale_tree(
    root: Path,
    output_root: Path,
    *,
    scale: int,
    backend: str,
    profile: str = "balanced",
    include_ui: bool,
    extra_excludes: list[str],
    max_dimension: int,
    executable: str | None,
    model: str,
    tile: int,
    gpu: int,
    fail_fast: bool,
    include_patterns: list[str] | None = None,
    include_exact: list[str] | None = None,
    overwrite: bool = False,
    checkpoint_manifest: Path | None = None,
    checkpoint_every: int = 25,
    resume_records: list[dict] | None = None,
) -> dict:
    _need_pillow()
    if scale not in (2, 3, 4):
        raise ValueError("scale must be 2, 3, or 4")
    profile = str(profile or "balanced").lower()
    if profile not in QUALITY_PROFILES:
        raise ValueError(f"profile must be one of: {', '.join(QUALITY_PROFILES)}")
    backend = str(backend or "auto").lower()
    if backend not in {"auto", "lanczos", "realesrgan"}:
        raise ValueError("backend must be auto, lanczos, or realesrgan")
    if profile == "pixel-art" and backend == "realesrgan":
        raise ValueError("pixel-art profile cannot use realesrgan")

    root = root.resolve()
    output_root = output_root.resolve()
    _ensure_outside_source(root, output_root, "output root")
    include_patterns = list(include_patterns or [])
    include_exact = list(include_exact or [])
    checkpoint_manifest = checkpoint_manifest.expanduser().resolve() if checkpoint_manifest is not None else None
    checkpoint_every = max(1, int(checkpoint_every or 25))
    resume_map = {str(x.get("source") or "").replace("\\", "/").strip("/").casefold(): dict(x) for x in (resume_records or []) if isinstance(x, dict)}

    records: list[dict] = []
    counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}
    source_changed = False
    auto_realesrgan = None
    auto_realesrgan_error = None
    if backend == "auto" and profile == "detail":
        try:
            auto_realesrgan = _resolve_realesrgan(executable)
        except Exception as exc:
            auto_realesrgan = None
            auto_realesrgan_error = f"{type(exc).__name__}: {exc}"

    if backend == "realesrgan":
        backend_decision = "EXPLICIT_REALESRGAN"
    elif backend == "lanczos":
        backend_decision = "EXPLICIT_LANCZOS"
    elif profile == "pixel-art":
        backend_decision = "AUTO_PIXEL_ART_NEAREST"
    elif profile == "detail" and auto_realesrgan:
        backend_decision = "AUTO_DETAIL_REALESRGAN_AVAILABLE"
    elif profile == "detail":
        backend_decision = "AUTO_DETAIL_REALESRGAN_UNAVAILABLE_FALLBACK_LANCZOS"
    else:
        backend_decision = "AUTO_CONSERVATIVE_PROFILE_LANCZOS"

    def build_report() -> dict:
        return {
            "tool": TOOL,
            "action": "upscale",
            "root": str(root),
            "output_root": str(output_root),
            "scale": scale,
            "backend": backend,
            "backend_counts": dict(backend_counts),
            "backend_decision": backend_decision,
            "backend_fallback_reason": auto_realesrgan_error,
            "ai_enhancement_used": bool(backend_counts.get("realesrgan")),
            "enhancement_class": "AI_SUPER_RESOLUTION" if backend_counts.get("realesrgan") else ("PIXEL_ART_RESAMPLE" if profile == "pixel-art" else "DETERMINISTIC_RESAMPLE_SHARPEN"),
            "quality_profile": profile,
            "model": model if backend_counts.get("realesrgan") else None,
            "tile": tile if backend_counts.get("realesrgan") else None,
            "gpu": gpu if backend_counts.get("realesrgan") else None,
            "max_dimension": max_dimension,
            "include_ui": include_ui,
            "include_patterns": include_patterns,
            "include_exact": include_exact,
            "extra_excludes": list(extra_excludes or []),
            "overwrite": overwrite,
            "texture_count": len(records),
            "status_counts": dict(counts),
            "records": records,
            "source_write_attempted": False,
            "source_client_modified": source_changed,
            "checkpointed": checkpoint_manifest is not None,
        }

    def checkpoint(force: bool = False) -> None:
        if checkpoint_manifest is None:
            return
        if not force and len(records) % checkpoint_every != 0:
            return
        payload = build_report()
        payload["run_state"] = "COMPLETE" if force else "RUNNING_CHECKPOINT"
        _json_dump(checkpoint_manifest, payload, overwrite=True)

    for source in iter_textures(root):
        rel = source.relative_to(root).as_posix()
        if not _selected(rel, include_patterns, include_exact):
            continue
        previous = resume_map.get(rel.casefold())
        if previous and previous.get("status") == "upscaled":
            try:
                expected_source = str(previous.get("source_sha256") or "")
                expected_output = str(previous.get("output_sha256") or "")
                dest = (output_root / Path(rel)).resolve()
                if expected_source and expected_output and sha256_file(source) == expected_source and dest.is_file() and sha256_file(dest) == expected_output:
                    resumed = dict(previous)
                    resumed["output"] = str(dest)
                    resumed["resumed"] = True
                    records.append(resumed)
                    counts["upscaled"] = counts.get("upscaled", 0) + 1
                    used = str(resumed.get("backend_used") or "")
                    if used:
                        backend_counts[used] = backend_counts.get(used, 0) + 1
                    checkpoint()
                    continue
            except Exception:
                pass
        started = time.monotonic()
        rec = TextureRecord(source=rel, suffix=source.suffix.lower(), risk_class=_risk_class(rel))
        try:
            rec, meta = inspect_texture(source)
            rec.source = rel
            rec.risk_class = _risk_class(rel)
            rec.quality_profile = profile
            rel_lower = rel.lower()
            if not include_ui and rec.risk_class == "UI_ATLAS_RISK":
                rec.status = "skipped_ui_pixel_crop_risk"
                rec.reason = "use --include-ui only after verifying pixel-space atlas consumers"
                raise _Skip
            if extra_excludes and _matches_any(rel_lower, extra_excludes):
                rec.status = "skipped_pattern"
                rec.reason = "path matches --exclude"
                raise _Skip

            target_w = int(rec.width or 0) * scale
            target_h = int(rec.height or 0) * scale
            if target_w > max_dimension or target_h > max_dimension:
                rec.status = "skipped_max_dimension"
                rec.reason = f"target {target_w}x{target_h} exceeds {max_dimension}"
                raise _Skip

            source_raw = source.read_bytes()
            image = decode_texture(source, rec, meta)
            rec.detail_metric_before = _detail_metric(image)
            effective_backend = backend
            if backend == "auto":
                effective_backend = "realesrgan" if (profile == "detail" and auto_realesrgan) else "lanczos"
            if profile == "pixel-art":
                effective_backend = "lanczos"
            rec.backend_used = effective_backend
            rec.backend_decision = backend_decision
            rec.ai_enhancement_used = effective_backend == "realesrgan"
            backend_counts[effective_backend] = backend_counts.get(effective_backend, 0) + 1
            if effective_backend == "lanczos":
                result = upscale_lanczos(image, scale, profile=profile)
                command = None
            elif effective_backend == "realesrgan":
                result, command = upscale_realesrgan(
                    image,
                    scale=scale,
                    executable=auto_realesrgan or executable,
                    model=model,
                    tile=tile,
                    gpu=gpu,
                    profile=profile,
                )
            else:
                raise ValueError(f"unknown backend: {effective_backend}")
            metric_image = result.resize(image.size, Image.Resampling.LANCZOS) if result.size != image.size else result
            rec.detail_metric_after = _detail_metric(metric_image)
            if rec.detail_metric_before and rec.detail_metric_before > 0:
                rec.detail_gain_ratio = round(rec.detail_metric_after / rec.detail_metric_before, 6)

            encoded = encode_texture(result, source_raw, rec, meta)

            # Verify the encoded bytes before they become a published output.
            if rec.suffix == ".tga" and rec.protected:
                if rec.protection_mode in {"DIMENSIONS_12_15", "G8_RUNTIME"}:
                    rare_verify = _rare_tga_decode_for_upscale(encoded)
                    if rare_verify is None:
                        raise RuntimeError(f"encoded {rec.protection_mode} TGA failed rare-family verification")
                    verify_bytes, _rare_meta = rare_verify
                else:
                    verify_bytes, _verify_meta = decode_tga_bytes(encoded)
            elif rec.suffix == ".bmp" and rec.protected:
                if rec.protection_mode == "SHIP_DIB40":
                    verify_bytes, _ship_meta = decode_ship_bmp_bytes(encoded)
                else:
                    verify_info = inspect_bmp_bytes(encoded)
                    verify_bytes = decode_bmp_editable(encoded, verify_info)
            else:
                verify_bytes = encoded
            verify = _open_from_bytes(verify_bytes)
            if verify.size != (target_w, target_h):
                raise RuntimeError(f"verification dimensions {verify.size} != {(target_w, target_h)}")

            dest = output_root / Path(rel)
            _ensure_outside_source(root, dest, "output file")
            _atomic_publish(dest, encoded, overwrite=overwrite)
            if sha256_file(dest) != sha256_bytes(encoded):
                raise RuntimeError("published output hash mismatch")

            rec.output = str(dest)
            rec.output_sha256 = sha256_bytes(encoded)
            rec.output_width, rec.output_height = verify.size
            rec.status = "upscaled"
            rec.reason = (" ".join(command) if command else "Pillow Lanczos") + f" · profile={profile} · decision={backend_decision}"
        except _Skip:
            pass
        except Exception as exc:
            rec.status = "failed"
            rec.reason = f"{type(exc).__name__}: {exc}"
        finally:
            if rec.source_sha256:
                try:
                    rec.source_unchanged = sha256_file(source) == rec.source_sha256
                except Exception:
                    rec.source_unchanged = False
                if rec.source_unchanged is False:
                    source_changed = True
                    if rec.status != "failed":
                        rec.status = "failed"
                        rec.reason = "SOURCE_CHANGED_DURING_UPSCALE"
            rec.elapsed_seconds = round(time.monotonic() - started, 6)
            records.append(asdict(rec))
            counts[rec.status] = counts.get(rec.status, 0) + 1
            checkpoint()
        if fail_fast and rec.status == "failed":
            break

    checkpoint(force=True)
    final_report = build_report()
    final_report["run_state"] = "COMPLETE"
    return final_report


class _Skip(Exception):
    pass


def _resolve_client_root(value: Path | None) -> Path:
    if value is not None:
        root = value.expanduser().resolve()
    else:
        from .app_config import resolve_client_root
        root, _source = resolve_client_root(PROJECT_ROOT)
        root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def _run_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)


def _safe_asset_key(rel: str) -> str:
    rel = rel.replace("\\", "/").strip("/")
    digest = hashlib.sha256(rel.casefold().encode("utf-8")).hexdigest()[:12]
    stem = "__".join(part.casefold() for part in Path(rel).parts if part not in {".", ".."})
    stem = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)[:120]
    return f"{stem}__{digest}" if stem else digest


def enhancement_root(project_root: Path | None = None) -> Path:
    project = (project_root or PROJECT_ROOT).resolve()
    override = os.environ.get("PT_ENHANCEMENT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    # Keep user-facing enhancement artifacts at the repository/workspace root,
    # not buried inside app/pt_build. For the normal layout this is
    # ~/Transferências/pt_asset_tool/enhancement.
    return (project.parent / "enhancement").resolve()


def _normalized_rel(rel: str) -> str:
    value = str(rel or "").replace("\\", "/").strip("/")
    if not value or "\x00" in value or value.startswith("../") or "/../" in ("/" + value + "/"):
        raise ValueError("INVALID_ENHANCEMENT_ASSET_PATH")
    return value


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"INVALID_JSON_OBJECT:{path}")
    return data


def _enhancement_run_manifests(project_root: Path | None = None) -> list[Path]:
    root = enhancement_root(project_root) / "runs"
    if not root.is_dir():
        return []
    rows = [p for p in root.glob("*/manifest.json") if p.is_file()]
    return sorted(rows, key=lambda p: (p.stat().st_mtime_ns, p.as_posix()), reverse=True)


def latest_enhancement_candidate(project_root: Path, rel: str, *, source_sha256: str | None = None) -> dict | None:
    rel = _normalized_rel(rel)
    key = rel.casefold()
    for manifest_path in _enhancement_run_manifests(project_root):
        try:
            report = _load_json(manifest_path)
        except Exception:
            continue
        for rec in report.get("records") or []:
            if not isinstance(rec, dict):
                continue
            if str(rec.get("source") or "").replace("\\", "/").strip("/").casefold() != key:
                continue
            if rec.get("status") != "upscaled":
                continue
            rec_source_sha = str(rec.get("source_sha256") or "")
            if source_sha256 is not None and rec_source_sha != source_sha256:
                continue
            output_raw = str(rec.get("output") or "").strip()
            if not output_raw:
                continue
            output = Path(output_raw).expanduser().resolve()
            try:
                output.relative_to(enhancement_root(project_root))
            except ValueError:
                # Old texture_upscale outputs remain evidence, but are not publishable
                # as enhancement candidates after the dedicated enhancement workspace
                # became authoritative.
                continue
            if not output.is_file():
                continue
            expected = str(rec.get("output_sha256") or "")
            if expected and sha256_file(output) != expected:
                continue
            return {
                "source": str(rec.get("source") or rel).replace("\\", "/").strip("/"),
                "manifest": str(manifest_path.resolve()),
                "output": str(output),
                "output_sha256": expected or sha256_file(output),
                "source_sha256": rec_source_sha,
                "quality_profile": rec.get("quality_profile") or report.get("quality_profile"),
                "backend_used": rec.get("backend_used"),
                "ai_enhancement_used": bool(rec.get("ai_enhancement_used")),
                "output_width": rec.get("output_width"),
                "output_height": rec.get("output_height"),
                "created_at": manifest_path.stat().st_mtime,
            }
    return None


def _client_target(client_root: Path, rel: str) -> tuple[Path, str]:
    client_root = client_root.resolve()
    rel = _normalized_rel(rel)
    direct = (client_root / Path(rel)).resolve()
    try:
        direct.relative_to(client_root)
    except ValueError:
        raise ValueError("ENHANCEMENT_CLIENT_PATH_ESCAPE")
    if direct.is_file():
        return direct, direct.relative_to(client_root).as_posix()
    current = client_root
    chosen: list[str] = []
    for part in Path(rel).parts:
        if part in {"", "."}:
            continue
        try:
            matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()]
        except OSError:
            matches = []
        if len(matches) != 1:
            raise FileNotFoundError(client_root / rel)
        current = matches[0]
        chosen.append(current.name)
    if not current.is_file():
        raise FileNotFoundError(current)
    return current.resolve(), "/".join(chosen)


def _transaction_dirs(project_root: Path, rel: str) -> list[Path]:
    root = enhancement_root(project_root) / "transactions" / _safe_asset_key(rel)
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and (p / "transaction.json").is_file()]
    return sorted(dirs, key=lambda p: p.name, reverse=True)


def latest_enhancement_transaction(project_root: Path, rel: str, *, restorable_only: bool = False) -> dict | None:
    rel = _normalized_rel(rel)
    for txdir in _transaction_dirs(project_root, rel):
        try:
            tx = _load_json(txdir / "transaction.json")
        except Exception:
            continue
        if str(tx.get("asset") or "").casefold() != rel.casefold():
            continue
        if restorable_only and tx.get("state") != "APPLIED_VERIFIED":
            continue
        tx = dict(tx)
        tx["transaction_manifest"] = str((txdir / "transaction.json").resolve())
        tx["transaction_root"] = str(txdir.resolve())
        return tx
    return None


def enhancement_status(project_root: Path, client_root: Path, rel: str) -> dict:
    rel = _normalized_rel(rel)
    client, canonical_rel = _client_target(client_root, rel)
    current_sha = sha256_file(client) if client.is_file() else None
    candidate = latest_enhancement_candidate(project_root, canonical_rel, source_sha256=current_sha) if current_sha else None
    latest_tx = latest_enhancement_transaction(project_root, canonical_rel)
    restorable = latest_enhancement_transaction(project_root, canonical_rel, restorable_only=True)
    candidate_ready = bool(candidate and candidate.get("source_sha256") and current_sha == candidate.get("source_sha256"))
    # Re-publishing the same candidate over an already enhanced file is not useful;
    # if current bytes equal the candidate, only rollback should be offered.
    if candidate and current_sha == candidate.get("output_sha256"):
        candidate_ready = False
    can_restore = bool(restorable and current_sha == restorable.get("deployed_sha256"))
    drift = bool(restorable and current_sha and current_sha not in {restorable.get("deployed_sha256"), restorable.get("original_sha256")})
    return {
        "workspace_root": str(enhancement_root(project_root)),
        "candidate": candidate,
        "candidate_ready": candidate_ready,
        "latest_transaction": latest_tx,
        "can_restore": can_restore,
        "client_sha256": current_sha,
        "drift_detected": drift,
    }


def _atomic_replace_client(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_mode = None
    try:
        old_mode = path.stat().st_mode & 0o7777
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".ptenh.tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if old_mode is not None:
            os.chmod(tmp, old_mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _candidate_from_record(project_root: Path, manifest_path: Path, rec: dict) -> dict:
    rel = _normalized_rel(str(rec.get("source") or ""))
    if rec.get("status") != "upscaled":
        raise ValueError(f"ENHANCEMENT_RECORD_NOT_UPSCALED:{rel}")
    output_raw = str(rec.get("output") or "").strip()
    if not output_raw:
        raise ValueError(f"ENHANCEMENT_RECORD_OUTPUT_MISSING:{rel}")
    output = Path(output_raw).expanduser().resolve()
    try:
        output.relative_to(enhancement_root(project_root))
    except ValueError as exc:
        raise ValueError(f"ENHANCEMENT_OUTPUT_OUTSIDE_WORKSPACE:{rel}") from exc
    if not output.is_file():
        raise FileNotFoundError(output)
    expected = str(rec.get("output_sha256") or "")
    actual = sha256_file(output)
    if expected and actual != expected:
        raise RuntimeError(f"ENHANCEMENT_CANDIDATE_HASH_MISMATCH:{rel}")
    return {
        "source": rel,
        "manifest": str(manifest_path.resolve()),
        "output": str(output),
        "output_sha256": expected or actual,
        "source_sha256": str(rec.get("source_sha256") or ""),
        "quality_profile": rec.get("quality_profile"),
        "backend_used": rec.get("backend_used"),
        "ai_enhancement_used": bool(rec.get("ai_enhancement_used")),
        "output_width": rec.get("output_width"),
        "output_height": rec.get("output_height"),
        "created_at": manifest_path.stat().st_mtime,
    }


def _candidates_from_run_manifest(project_root: Path, manifest_path: Path) -> list[dict]:
    manifest_path = manifest_path.expanduser().resolve()
    report = _load_json(manifest_path)
    if str(report.get("action") or "") != "upscale":
        raise ValueError("ENHANCEMENT_BATCH_SOURCE_IS_NOT_UPSCALE_MANIFEST")
    if str(report.get("run_state") or "").upper() == "RUNNING_CHECKPOINT":
        raise RuntimeError("ENHANCEMENT_BATCH_RUN_INCOMPLETE_RESUME_REQUIRED")
    status_counts = {str(k): int(v) for k, v in (report.get("status_counts") or {}).items()}
    not_upscaled = sum(v for k, v in status_counts.items() if k != "upscaled")
    if not_upscaled:
        raise RuntimeError("ENHANCEMENT_BATCH_RUN_NOT_CLEAN:" + json.dumps(status_counts, ensure_ascii=False))
    candidates: list[dict] = []
    for rec in report.get("records") or []:
        if not isinstance(rec, dict) or rec.get("status") != "upscaled":
            continue
        candidates.append(_candidate_from_record(project_root, manifest_path, rec))
    if not candidates:
        raise RuntimeError("ENHANCEMENT_BATCH_HAS_NO_UPSCALED_CANDIDATES")
    return candidates


def _latest_run_manifest(project_root: Path) -> Path | None:
    rows = _enhancement_run_manifests(project_root)
    return rows[0] if rows else None


def _publish_candidate(client_root: Path, project_root: Path, candidate: dict) -> dict:
    rel = _normalized_rel(str(candidate.get("source") or ""))
    client_root = client_root.resolve()
    _ensure_outside_source(client_root, enhancement_root(project_root), "enhancement root")
    target, canonical_rel = _client_target(client_root, rel)
    current_sha = sha256_file(target)
    source_sha = str(candidate.get("source_sha256") or "")
    if not source_sha or current_sha != source_sha:
        raise RuntimeError(f"CLIENT_DRIFT_SINCE_ENHANCEMENT:{canonical_rel}")
    candidate_path = Path(str(candidate["output"])).resolve()
    candidate_bytes = candidate_path.read_bytes()
    candidate_sha = sha256_bytes(candidate_bytes)
    if candidate_sha != str(candidate.get("output_sha256") or ""):
        raise RuntimeError(f"ENHANCEMENT_CANDIDATE_HASH_MISMATCH:{canonical_rel}")

    txid = _run_stamp()
    txroot = enhancement_root(project_root) / "transactions" / _safe_asset_key(canonical_rel) / txid
    backup = txroot / "backup" / Path(canonical_rel)
    original_bytes = target.read_bytes()
    _atomic_publish(backup, original_bytes, overwrite=False)
    if sha256_file(backup) != current_sha:
        raise RuntimeError(f"ENHANCEMENT_BACKUP_HASH_MISMATCH:{canonical_rel}")
    manifest = txroot / "transaction.json"
    tx = {
        "format": "PT_TEXTURE_ENHANCEMENT_TRANSACTION_V1",
        "state": "PREPARED",
        "asset": canonical_rel,
        "client_path": str(target),
        "candidate_manifest": candidate["manifest"],
        "candidate_path": str(candidate_path),
        "backup_path": str(backup.resolve()),
        "original_sha256": current_sha,
        "deployed_sha256": candidate_sha,
        "quality_profile": candidate.get("quality_profile"),
        "backend_used": candidate.get("backend_used"),
        "ai_enhancement_used": bool(candidate.get("ai_enhancement_used")),
        "created_at": time.time(),
    }
    _json_dump(manifest, tx, overwrite=False)
    try:
        _atomic_replace_client(target, candidate_bytes)
        if sha256_file(target) != candidate_sha:
            raise RuntimeError(f"ENHANCEMENT_POST_WRITE_HASH_MISMATCH:{canonical_rel}")
    except Exception as write_exc:
        rollback_error = None
        try:
            _atomic_replace_client(target, original_bytes)
            if sha256_file(target) != current_sha:
                raise RuntimeError(f"ENHANCEMENT_AUTO_ROLLBACK_VERIFY_FAILED:{canonical_rel}")
        except Exception as exc:
            rollback_error = exc
        tx["state"] = "WRITE_FAILED_ROLLED_BACK" if rollback_error is None else "WRITE_FAILED_ROLLBACK_FAILED"
        tx["write_error"] = f"{type(write_exc).__name__}:{write_exc}"
        if rollback_error is not None:
            tx["rollback_error"] = f"{type(rollback_error).__name__}:{rollback_error}"
        tx["updated_at"] = time.time()
        _json_dump(manifest, tx, overwrite=True)
        if rollback_error is not None:
            raise RuntimeError(f"ENHANCEMENT_WRITE_AND_ROLLBACK_FAILED:{canonical_rel}:{rollback_error}") from write_exc
        raise
    tx["state"] = "APPLIED_VERIFIED"
    tx["updated_at"] = time.time()
    _json_dump(manifest, tx, overwrite=True)
    return {**tx, "transaction_manifest": str(manifest.resolve()), "client_modified": True}


def publish_enhancement(client_root: Path, project_root: Path, rel: str, *, confirm: str) -> dict:
    rel = _normalized_rel(rel)
    if confirm != ENHANCEMENT_PUBLISH_CONFIRM:
        raise PermissionError("ENHANCEMENT_PUBLISH_CONFIRMATION_REQUIRED")
    target, canonical_rel = _client_target(client_root.resolve(), rel)
    current_sha = sha256_file(target)
    candidate = latest_enhancement_candidate(project_root, canonical_rel, source_sha256=current_sha)
    if not candidate:
        raise RuntimeError("NO_ENHANCEMENT_CANDIDATE_FOR_CURRENT_CLIENT_HASH")
    return _publish_candidate(client_root, project_root, candidate)


def _restore_transaction(client_root: Path, tx_manifest: Path) -> dict:
    tx_manifest = tx_manifest.expanduser().resolve()
    tx = _load_json(tx_manifest)
    if tx.get("state") != "APPLIED_VERIFIED":
        raise RuntimeError(f"ENHANCEMENT_TRANSACTION_NOT_RESTORABLE:{tx_manifest}")
    rel = _normalized_rel(str(tx.get("asset") or ""))
    target, canonical_rel = _client_target(client_root.resolve(), rel)
    current_sha = sha256_file(target)
    if current_sha != str(tx.get("deployed_sha256") or ""):
        raise RuntimeError(f"CLIENT_DRIFT_AFTER_ENHANCEMENT:{canonical_rel}")
    backup = Path(str(tx.get("backup_path") or "")).resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"ENHANCEMENT_BACKUP_MISSING:{canonical_rel}")
    original_bytes = backup.read_bytes()
    original_sha = sha256_bytes(original_bytes)
    if original_sha != str(tx.get("original_sha256") or ""):
        raise RuntimeError(f"ENHANCEMENT_BACKUP_HASH_MISMATCH:{canonical_rel}")
    deployed_bytes = target.read_bytes()
    try:
        _atomic_replace_client(target, original_bytes)
        if sha256_file(target) != original_sha:
            raise RuntimeError(f"ENHANCEMENT_RESTORE_VERIFY_FAILED:{canonical_rel}")
    except Exception as restore_exc:
        try:
            _atomic_replace_client(target, deployed_bytes)
            if sha256_file(target) != current_sha:
                raise RuntimeError(f"ENHANCEMENT_RESTORE_RECOVERY_VERIFY_FAILED:{canonical_rel}")
        except Exception as recovery_exc:
            raise RuntimeError(f"ENHANCEMENT_RESTORE_AND_RECOVERY_FAILED:{canonical_rel}:{recovery_exc}") from restore_exc
        raise
    tx["state"] = "RESTORED_VERIFIED"
    tx["restored_at"] = time.time()
    _json_dump(tx_manifest, tx, overwrite=True)
    return {**tx, "transaction_manifest": str(tx_manifest), "client_modified": True}


def restore_enhancement(client_root: Path, project_root: Path, rel: str, *, confirm: str) -> dict:
    rel = _normalized_rel(rel)
    if confirm != ENHANCEMENT_RESTORE_CONFIRM:
        raise PermissionError("ENHANCEMENT_RESTORE_CONFIRMATION_REQUIRED")
    client_root = client_root.resolve()
    _ensure_outside_source(client_root, enhancement_root(project_root), "enhancement root")
    _target, canonical_rel = _client_target(client_root, rel)
    tx = latest_enhancement_transaction(project_root, canonical_rel, restorable_only=True)
    if not tx:
        raise FileNotFoundError("NO_APPLIED_ENHANCEMENT_TRANSACTION")
    return _restore_transaction(client_root, Path(str(tx["transaction_manifest"])))


def _batch_transaction_manifests(project_root: Path) -> list[Path]:
    root = enhancement_root(project_root) / "batches"
    if not root.is_dir():
        return []
    rows = [p for p in root.glob("*/batch.json") if p.is_file()]
    return sorted(rows, key=lambda p: (p.stat().st_mtime_ns, p.as_posix()), reverse=True)


def latest_enhancement_batch(project_root: Path, *, restorable_only: bool = False) -> dict | None:
    for path in _batch_transaction_manifests(project_root):
        try:
            row = _load_json(path)
        except Exception:
            continue
        if restorable_only and row.get("state") != "APPLIED_VERIFIED":
            continue
        row = dict(row)
        row["batch_manifest"] = str(path.resolve())
        return row
    return None


def enhancement_batch_status(project_root: Path) -> dict:
    run_path = _latest_run_manifest(project_root)
    run = None
    if run_path is not None:
        try:
            report = _load_json(run_path)
            counts = collections.Counter(str(x.get("status") or "UNKNOWN") for x in (report.get("records") or []) if isinstance(x, dict))
            risk = collections.Counter(str(x.get("risk_class") or "UNKNOWN") for x in (report.get("records") or []) if isinstance(x, dict))
            non_upscaled = sum(int(v) for k, v in counts.items() if k != "upscaled")
            run_state = str(report.get("run_state") or "LEGACY_COMPLETE")
            run = {
                "manifest": str(run_path.resolve()),
                "run_state": run_state,
                "clean_complete": run_state != "RUNNING_CHECKPOINT" and non_upscaled == 0 and int(counts.get("upscaled", 0)) > 0,
                "texture_count": int(report.get("texture_count") or 0),
                "status_counts": dict(counts),
                "risk_counts": dict(risk),
                "quality_profile": report.get("quality_profile"),
                "backend_counts": report.get("backend_counts") or {},
                "ai_enhancement_used": bool(report.get("ai_enhancement_used")),
            }
        except Exception as exc:
            run = {"manifest": str(run_path), "error": f"{type(exc).__name__}:{exc}"}
    latest = latest_enhancement_batch(project_root)
    restorable = latest_enhancement_batch(project_root, restorable_only=True)
    return {
        "workspace_root": str(enhancement_root(project_root)),
        "latest_run": run,
        "latest_batch": latest,
        "can_restore_batch": bool(restorable),
    }


def _resolve_batch_source_manifest(project_root: Path, manifest: Path | None) -> Path:
    path = manifest.expanduser().resolve() if manifest is not None else _latest_run_manifest(project_root)
    if path is None or not path.is_file():
        raise FileNotFoundError("NO_ENHANCEMENT_RUN_MANIFEST")
    try:
        path.relative_to(enhancement_root(project_root))
    except ValueError as exc:
        raise ValueError("ENHANCEMENT_BATCH_MANIFEST_OUTSIDE_WORKSPACE") from exc
    return path


def publish_enhancement_batch(
    client_root: Path,
    project_root: Path,
    *,
    manifest: Path | None = None,
    confirm: str,
) -> dict:
    if confirm != ENHANCEMENT_BATCH_PUBLISH_CONFIRM:
        raise PermissionError("ENHANCEMENT_BATCH_PUBLISH_CONFIRMATION_REQUIRED")
    client_root = client_root.resolve()
    run_manifest = _resolve_batch_source_manifest(project_root, manifest)
    candidates = _candidates_from_run_manifest(project_root, run_manifest)

    # All hashes are preflighted before the first client write. This keeps a stale
    # or partially regenerated run from producing a half-applied client.
    preflight: list[dict] = []
    errors: list[dict] = []
    for candidate in candidates:
        rel = str(candidate["source"])
        try:
            target, canonical_rel = _client_target(client_root, rel)
            current_sha = sha256_file(target)
            if current_sha != str(candidate.get("source_sha256") or ""):
                raise RuntimeError("CLIENT_HASH_NO_LONGER_MATCHES_RUN_SOURCE")
            if sha256_file(Path(str(candidate["output"]))) != str(candidate.get("output_sha256") or ""):
                raise RuntimeError("CANDIDATE_HASH_CHANGED")
            preflight.append({"asset": canonical_rel, "source_sha256": current_sha, "candidate_sha256": candidate["output_sha256"]})
        except Exception as exc:
            errors.append({"asset": rel, "error": f"{type(exc).__name__}:{exc}"})
    if errors:
        raise RuntimeError("ENHANCEMENT_BATCH_PREFLIGHT_FAILED:" + json.dumps(errors[:20], ensure_ascii=False))

    batch_id = _run_stamp()
    batch_root = enhancement_root(project_root) / "batches" / batch_id
    batch_manifest = batch_root / "batch.json"
    batch = {
        "format": "PT_TEXTURE_ENHANCEMENT_BATCH_V1",
        "state": "PREPARED",
        "batch_id": batch_id,
        "source_run_manifest": str(run_manifest),
        "asset_count": len(candidates),
        "preflight_count": len(preflight),
        "applied_count": 0,
        "restored_count": 0,
        "failed_count": 0,
        "transactions": [],
        "created_at": time.time(),
    }
    _json_dump(batch_manifest, batch, overwrite=False)
    applied: list[dict] = []
    try:
        for index, candidate in enumerate(candidates, 1):
            tx = _publish_candidate(client_root, project_root, candidate)
            applied.append(tx)
            batch["transactions"].append({
                "asset": tx["asset"],
                "transaction_manifest": tx["transaction_manifest"],
                "state": tx["state"],
            })
            batch["applied_count"] = len(applied)
            batch["progress"] = {"current": index, "total": len(candidates), "asset": tx["asset"]}
            batch["updated_at"] = time.time()
            _json_dump(batch_manifest, batch, overwrite=True)
    except Exception as write_exc:
        rollback_errors: list[dict] = []
        restored = 0
        for tx in reversed(applied):
            try:
                _restore_transaction(client_root, Path(str(tx["transaction_manifest"])))
                restored += 1
            except Exception as exc:
                rollback_errors.append({"asset": tx.get("asset"), "error": f"{type(exc).__name__}:{exc}"})
        batch["state"] = "WRITE_FAILED_ROLLED_BACK" if not rollback_errors else "WRITE_FAILED_ROLLBACK_INCOMPLETE"
        batch["write_error"] = f"{type(write_exc).__name__}:{write_exc}"
        batch["restored_count"] = restored
        batch["failed_count"] = 1 + len(rollback_errors)
        batch["rollback_errors"] = rollback_errors
        batch["updated_at"] = time.time()
        _json_dump(batch_manifest, batch, overwrite=True)
        raise RuntimeError(f"ENHANCEMENT_BATCH_WRITE_FAILED:{batch_manifest}:{write_exc}") from write_exc

    batch["state"] = "APPLIED_VERIFIED"
    batch["progress"] = {"current": len(candidates), "total": len(candidates)}
    batch["updated_at"] = time.time()
    _json_dump(batch_manifest, batch, overwrite=True)
    return {**batch, "batch_manifest": str(batch_manifest.resolve()), "client_modified": True}


def restore_enhancement_batch(
    client_root: Path,
    project_root: Path,
    *,
    batch_manifest: Path | None = None,
    confirm: str,
) -> dict:
    if confirm != ENHANCEMENT_BATCH_RESTORE_CONFIRM:
        raise PermissionError("ENHANCEMENT_BATCH_RESTORE_CONFIRMATION_REQUIRED")
    client_root = client_root.resolve()
    if batch_manifest is None:
        batch = latest_enhancement_batch(project_root, restorable_only=True)
        if not batch:
            raise FileNotFoundError("NO_APPLIED_ENHANCEMENT_BATCH")
        path = Path(str(batch["batch_manifest"]))
    else:
        path = batch_manifest.expanduser().resolve()
        try:
            path.relative_to(enhancement_root(project_root))
        except ValueError as exc:
            raise ValueError("ENHANCEMENT_BATCH_MANIFEST_OUTSIDE_WORKSPACE") from exc
        batch = _load_json(path)
    if batch.get("state") != "APPLIED_VERIFIED":
        raise RuntimeError("ENHANCEMENT_BATCH_NOT_RESTORABLE")
    tx_rows = list(batch.get("transactions") or [])
    if not tx_rows:
        raise RuntimeError("ENHANCEMENT_BATCH_HAS_NO_TRANSACTIONS")

    # Refuse the entire restore before any write if one asset has drifted or one
    # backup is missing. Batch rollback must remain deterministic.
    for item in tx_rows:
        txp = Path(str(item.get("transaction_manifest") or "")).resolve()
        tx = _load_json(txp)
        rel = _normalized_rel(str(tx.get("asset") or ""))
        target, _canonical = _client_target(client_root, rel)
        if sha256_file(target) != str(tx.get("deployed_sha256") or ""):
            raise RuntimeError(f"CLIENT_DRIFT_AFTER_ENHANCEMENT:{rel}")
        backup = Path(str(tx.get("backup_path") or "")).resolve()
        if not backup.is_file() or sha256_file(backup) != str(tx.get("original_sha256") or ""):
            raise RuntimeError(f"ENHANCEMENT_BACKUP_INVALID:{rel}")
        candidate = Path(str(tx.get("candidate_path") or "")).resolve()
        if not candidate.is_file() or sha256_file(candidate) != str(tx.get("deployed_sha256") or ""):
            raise RuntimeError(f"ENHANCEMENT_CANDIDATE_INVALID_FOR_BATCH_RECOVERY:{rel}")

    restored: list[dict] = []
    try:
        for item in reversed(tx_rows):
            result = _restore_transaction(client_root, Path(str(item["transaction_manifest"])))
            restored.append(result)
            batch["restored_count"] = len(restored)
            batch["progress"] = {"current": len(restored), "total": len(tx_rows), "asset": result["asset"]}
            batch["updated_at"] = time.time()
            _json_dump(path, batch, overwrite=True)
    except Exception as restore_exc:
        recovery_errors: list[dict] = []
        # Return already-restored assets to the enhanced bytes so the batch stays
        # all-enhanced if the rollback cannot complete.
        for tx in reversed(restored):
            try:
                rel = str(tx["asset"])
                target, _canonical = _client_target(client_root, rel)
                candidate = Path(str(tx["candidate_path"])).resolve()
                deployed = candidate.read_bytes()
                _atomic_replace_client(target, deployed)
                if sha256_file(target) != str(tx["deployed_sha256"]):
                    raise RuntimeError("BATCH_RESTORE_RECOVERY_HASH_MISMATCH")
                txp = Path(str(tx["transaction_manifest"])).resolve()
                original_tx = _load_json(txp)
                original_tx["state"] = "APPLIED_VERIFIED"
                original_tx.pop("restored_at", None)
                original_tx["updated_at"] = time.time()
                _json_dump(txp, original_tx, overwrite=True)
            except Exception as exc:
                recovery_errors.append({"asset": tx.get("asset"), "error": f"{type(exc).__name__}:{exc}"})
        batch["state"] = "RESTORE_FAILED_RECOVERED" if not recovery_errors else "RESTORE_FAILED_RECOVERY_INCOMPLETE"
        batch["restore_error"] = f"{type(restore_exc).__name__}:{restore_exc}"
        batch["recovery_errors"] = recovery_errors
        batch["updated_at"] = time.time()
        _json_dump(path, batch, overwrite=True)
        raise RuntimeError(f"ENHANCEMENT_BATCH_RESTORE_FAILED:{path}:{restore_exc}") from restore_exc

    batch["state"] = "RESTORED_VERIFIED"
    batch["restored_at"] = time.time()
    batch["progress"] = {"current": len(tx_rows), "total": len(tx_rows)}
    _json_dump(path, batch, overwrite=True)
    return {**batch, "batch_manifest": str(path.resolve()), "client_modified": True}

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pt_texture_upscale",
        description="Upscale Summit/Priston textures into pt_build or another separate tree while preserving protected TGA/BMP headers.",
    )
    sp = p.add_subparsers(dest="command", required=True)

    sp.add_parser("capabilities", help="show available texture enhancement backends and auto-profile policy")

    pub = sp.add_parser("publish", help="publish the latest verified enhancement candidate for one texture to the client")
    pub.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    pub.add_argument("--include-exact", required=True, help="exact client-relative texture path")
    pub.add_argument("--confirm", required=True)

    rst = sp.add_parser("restore", help="undo the latest applied enhancement transaction for one texture")
    rst.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    rst.add_argument("--include-exact", required=True, help="exact client-relative texture path")
    rst.add_argument("--confirm", required=True)

    pub_batch = sp.add_parser("publish-batch", help="publish every verified candidate from one enhancement run as an all-or-rollback batch")
    pub_batch.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    pub_batch.add_argument("--manifest", type=Path, help="run manifest; defaults to the latest enhancement run")
    pub_batch.add_argument("--confirm", required=True)

    rst_batch = sp.add_parser("restore-batch", help="restore every asset from the latest applied enhancement batch")
    rst_batch.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    rst_batch.add_argument("--batch-manifest", type=Path, help="defaults to the latest APPLIED_VERIFIED batch")
    rst_batch.add_argument("--confirm", required=True)

    sp.add_parser("batch-status", help="show latest enhancement run and batch publish/rollback state")

    s = sp.add_parser("scan", help="classify supported textures without writing the source tree")
    s.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    s.add_argument("--manifest", type=Path)
    s.add_argument("--include", action="append", default=[], help="glob against /relative/path; repeatable; omitted means all textures")
    s.add_argument("--include-exact", action="append", default=[], help="exact client-relative path; repeatable; intended for UI/single-asset runs")
    s.add_argument("--include-ui", action="store_true", help="do not apply conservative UI/atlas exclusions")
    s.add_argument("--exclude", action="append", default=[], help="glob against /relative/path; repeatable")

    u = sp.add_parser("run", help="upscale to a separate output tree; never writes the source/client")
    u.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    u.add_argument("--output-root", type=Path, help="defaults to a unique <project>/enhancement/runs/<id>/overlay tree")
    u.add_argument("--manifest", type=Path)
    u.add_argument("--include", action="append", default=[], help="glob against /relative/path; repeatable")
    u.add_argument("--include-exact", action="append", default=[], help="exact client-relative path; repeatable; intended for UI/single-asset runs")
    u.add_argument("--all", action="store_true", help="explicitly process every supported texture under the client root")
    u.add_argument("--scale", type=int, choices=(2, 3, 4), default=4)
    u.add_argument("--backend", choices=("auto", "realesrgan", "lanczos"), default="auto")
    u.add_argument("--profile", choices=QUALITY_PROFILES, default="balanced", help="faithful=no sharpening; balanced=mild detail; detail=stronger detail/AI when auto; pixel-art=nearest-neighbour")
    u.add_argument("--realesrgan", help="path/name of realesrgan-ncnn-vulkan executable")
    u.add_argument("--model", default="realesrgan-x4plus")
    u.add_argument("--tile", type=int, default=256, help="Vulkan tile size; 256 is conservative for 8GB-class GPUs")
    u.add_argument("--gpu", type=int, default=0)
    u.add_argument("--max-dimension", type=int, default=8192)
    u.add_argument("--include-ui", action="store_true", help="upscale paths normally excluded as pixel-crop/atlas risks")
    u.add_argument("--exclude", action="append", default=[], help="glob against /relative/path; repeatable")
    u.add_argument("--overwrite", action="store_true", help="explicitly allow replacing an existing output and/or explicit manifest")
    u.add_argument("--fail-fast", action="store_true")
    u.add_argument("--checkpoint-every", type=int, default=25, help="write an atomic run manifest checkpoint every N processed textures")

    resume = sp.add_parser("resume", help="resume an interrupted enhancement run without reprocessing verified candidates")
    resume.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    resume.add_argument("--manifest", type=Path, help="interrupted run manifest; defaults to the latest enhancement run")
    resume.add_argument("--checkpoint-every", type=int, default=25)
    resume.add_argument("--fail-fast", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "capabilities":
        print(json.dumps(capability_status(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "batch-status":
        print(json.dumps(enhancement_batch_status(PROJECT_ROOT), indent=2, ensure_ascii=False))
        return 0

    root = _resolve_client_root(getattr(args, "client_root", None))

    if args.command == "resume":
        manifest = _resolve_batch_source_manifest(PROJECT_ROOT, args.manifest)
        previous = _load_json(manifest)
        output_root = Path(str(previous.get("output_root") or "")).expanduser().resolve()
        report = upscale_tree(
            root, output_root,
            scale=int(previous.get("scale") or 4),
            backend=str(previous.get("backend") or "auto"),
            profile=str(previous.get("quality_profile") or "balanced"),
            include_ui=bool(previous.get("include_ui")),
            extra_excludes=list(previous.get("extra_excludes") or []),
            max_dimension=int(previous.get("max_dimension") or 8192),
            executable=None,
            model=str(previous.get("model") or "realesrgan-x4plus"),
            tile=int(previous.get("tile") or 256),
            gpu=int(previous.get("gpu") or 0),
            fail_fast=bool(args.fail_fast),
            include_patterns=list(previous.get("include_patterns") or []),
            include_exact=list(previous.get("include_exact") or []),
            overwrite=True,
            checkpoint_manifest=manifest,
            checkpoint_every=args.checkpoint_every,
            resume_records=list(previous.get("records") or []),
        )
        print(json.dumps({
            "tool": TOOL, "action": "resume", "texture_count": report["texture_count"],
            "status_counts": report["status_counts"], "backend_counts": report.get("backend_counts") or {},
            "manifest": str(manifest), "output_root": report.get("output_root"),
            "enhancement_workspace": str(enhancement_root(PROJECT_ROOT)),
            "source_client_modified": bool(report.get("source_client_modified")),
        }, indent=2, ensure_ascii=False))
        failed = int(report["status_counts"].get("failed", 0))
        return 1 if failed or report.get("source_client_modified") else 0

    if args.command == "publish":
        result = publish_enhancement(root, PROJECT_ROOT, args.include_exact, confirm=args.confirm)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "restore":
        result = restore_enhancement(root, PROJECT_ROOT, args.include_exact, confirm=args.confirm)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "publish-batch":
        result = publish_enhancement_batch(root, PROJECT_ROOT, manifest=args.manifest, confirm=args.confirm)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "restore-batch":
        result = restore_enhancement_batch(root, PROJECT_ROOT, batch_manifest=args.batch_manifest, confirm=args.confirm)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "run" and not args.all and not args.include and not args.include_exact:
        raise ValueError("texture-upscale run requires --include/--include-exact or explicit --all")
    if args.command == "run" and args.all and (args.include or args.include_exact):
        raise ValueError("--all cannot be combined with --include or --include-exact")

    default_run_dir: Path | None = None
    output_root: Path | None = None
    if args.command == "run":
        if args.output_root is None:
            default_run_dir = enhancement_root(PROJECT_ROOT) / "runs" / _run_stamp()
            output_root = (default_run_dir / "overlay").resolve()
        else:
            output_root = args.output_root.expanduser().resolve()
        _ensure_outside_source(root, output_root, "output root")

    manifest = args.manifest
    if manifest is None:
        if args.command == "scan":
            manifest = PROJECT_ROOT / "pt_build" / "texture_upscale" / "scans" / f"scan_{_run_stamp()}.json"
        elif default_run_dir is not None:
            manifest = default_run_dir / "manifest.json"
        else:
            assert output_root is not None
            manifest = Path(str(output_root) + ".manifest.json")
    manifest = manifest.expanduser().resolve()
    _ensure_outside_source(root, manifest, "manifest")
    if args.command == "run":
        assert output_root is not None
        if _is_within(output_root, manifest):
            raise ValueError(f"manifest must be outside the output overlay: {manifest}")
    manifest_overwrite = bool(getattr(args, "overwrite", False))
    if manifest.exists() and not manifest_overwrite:
        raise FileExistsError(f"output already exists: {manifest}")

    if args.command == "scan":
        report = scan_tree(
            root,
            include_ui=args.include_ui,
            extra_excludes=args.exclude,
            include_patterns=args.include,
            include_exact=args.include_exact,
        )
    else:
        assert output_root is not None
        report = upscale_tree(
            root,
            output_root,
            scale=args.scale,
            backend=args.backend,
            profile=args.profile,
            include_ui=args.include_ui,
            extra_excludes=args.exclude,
            max_dimension=args.max_dimension,
            executable=args.realesrgan,
            model=args.model,
            tile=args.tile,
            gpu=args.gpu,
            fail_fast=args.fail_fast,
            include_patterns=args.include,
            include_exact=args.include_exact,
            overwrite=args.overwrite,
            checkpoint_manifest=manifest,
            checkpoint_every=args.checkpoint_every,
        )

    if args.command != "run":
        _json_dump(manifest, report, overwrite=manifest_overwrite)

    summary = {
        "tool": TOOL,
        "action": report["action"],
        "texture_count": report["texture_count"],
        "status_counts": report["status_counts"],
        "backend_counts": report.get("backend_counts") or {},
        "backend_decision": report.get("backend_decision"),
        "backend_fallback_reason": report.get("backend_fallback_reason"),
        "ai_enhancement_used": bool(report.get("ai_enhancement_used")),
        "enhancement_class": report.get("enhancement_class"),
        "quality_profile": report.get("quality_profile"),
        "manifest": str(manifest),
        "output_root": report.get("output_root"),
        "enhancement_workspace": str(enhancement_root(PROJECT_ROOT)),
        "source_write_attempted": False,
        "source_client_modified": bool(report.get("source_client_modified")),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    failed = int(report["status_counts"].get("failed", 0))
    return 1 if failed or summary["source_client_modified"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
