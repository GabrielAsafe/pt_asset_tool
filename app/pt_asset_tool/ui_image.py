from __future__ import annotations

import importlib.util
import mimetypes
import pathlib
import struct
import zlib
from functools import lru_cache
from types import ModuleType

PNG_SIG = b"\x89PNG\r\n\x1a\n"
_BROWSER_NATIVE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}


class PreviewDecodeError(ValueError):
    """A physical asset exists, but the application cannot render it safely."""


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("INVALID_RGBA_BUFFER")
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)  # PNG filter: None
        rows.extend(rgba[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + _chunk(b"IEND", b"")


def tga_bytes_to_png_bytes(data: bytes, max_pixels: int = 20_000_000) -> bytes:
    """Decode a *standard-equivalent* TGA byte stream to a browser PNG.

    Protected Priston/Summit headers are normalized before this function is
    called. Keeping the normalizer separate prevents the UI from duplicating
    format knowledge that already exists in the application adapters.
    """
    if len(data) < 18:
        raise ValueError("TGA_HEADER_TRUNCATED")
    id_len = data[0]
    cmap_type = data[1]
    image_type = data[2]
    _cmap_first, cmap_len, cmap_depth = struct.unpack_from("<HHB", data, 3)
    _x, _y, width, height, depth, desc = struct.unpack_from("<HHHHBB", data, 8)
    if cmap_type != 0:
        raise ValueError("TGA_COLOR_MAP_UNSUPPORTED")
    if image_type not in {2, 3, 10, 11}:
        raise ValueError(f"TGA_IMAGE_TYPE_UNSUPPORTED:{image_type}")
    if width <= 0 or height <= 0 or width * height > max_pixels:
        raise ValueError("TGA_DIMENSIONS_INVALID")
    if image_type in {2, 10} and depth not in {24, 32}:
        raise ValueError(f"TGA_TRUECOLOR_DEPTH_UNSUPPORTED:{depth}")
    if image_type in {3, 11} and depth != 8:
        raise ValueError(f"TGA_GRAYSCALE_DEPTH_UNSUPPORTED:{depth}")
    offset = 18 + id_len
    if cmap_len:
        offset += ((cmap_depth + 7) // 8) * cmap_len
    if offset > len(data):
        raise ValueError("TGA_DATA_OFFSET_INVALID")
    count = width * height
    bpp = depth // 8

    def decode_pixel(raw: bytes) -> bytes:
        if image_type in {3, 11}:
            g = raw[0]
            return bytes((g, g, g, 255))
        b, g, r = raw[:3]
        a = raw[3] if bpp == 4 else 255
        return bytes((r, g, b, a))

    pixels: list[bytes] = []
    pos = offset
    if image_type in {2, 3}:
        need = count * bpp
        if pos + need > len(data):
            raise ValueError("TGA_PIXEL_DATA_TRUNCATED")
        for i in range(count):
            raw = data[pos + i * bpp:pos + (i + 1) * bpp]
            pixels.append(decode_pixel(raw))
    else:
        while len(pixels) < count:
            if pos >= len(data):
                raise ValueError("TGA_RLE_TRUNCATED")
            header = data[pos]
            pos += 1
            run = (header & 0x7F) + 1
            if header & 0x80:
                if pos + bpp > len(data):
                    raise ValueError("TGA_RLE_PIXEL_TRUNCATED")
                px = decode_pixel(data[pos:pos + bpp])
                pos += bpp
                pixels.extend([px] * run)
            else:
                need = run * bpp
                if pos + need > len(data):
                    raise ValueError("TGA_RAW_PACKET_TRUNCATED")
                for _ in range(run):
                    pixels.append(decode_pixel(data[pos:pos + bpp]))
                    pos += bpp
            if len(pixels) > count:
                raise ValueError("TGA_RLE_PIXEL_OVERFLOW")
    pixels = pixels[:count]

    top_origin = bool(desc & 0x20)
    right_origin = bool(desc & 0x10)
    out = bytearray(width * height * 4)
    for src_i, px in enumerate(pixels):
        sy, sx = divmod(src_i, width)
        dy = sy if top_origin else (height - 1 - sy)
        dx = (width - 1 - sx) if right_origin else sx
        di = (dy * width + dx) * 4
        out[di:di + 4] = px
    return _png_rgba(width, height, bytes(out))


def tga_to_png_bytes(path: pathlib.Path, max_pixels: int = 20_000_000) -> bytes:
    """Legacy standard-TGA wrapper retained for callers outside the GUI."""
    return tga_bytes_to_png_bytes(path.read_bytes(), max_pixels=max_pixels)


@lru_cache(maxsize=8)
def _load_root_module(project_root: str, filename: str, module_tag: str) -> ModuleType:
    path = pathlib.Path(project_root) / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(module_tag, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decode_tga_for_preview(path: pathlib.Path, project_root: pathlib.Path) -> bytes:
    raw = path.read_bytes()
    adapter = _load_root_module(str(project_root.resolve()), "pt_protected_tga_v1.py", "pt_ui_protected_tga")
    try:
        standard, _info = adapter.decode_bytes(raw)
    except Exception as exc:
        # One previously documented corpus outlier (ArchivoTmp.tga) has a
        # single-bit dimension corruption with a strictly proven preview-only
        # recovery. Reuse that existing evidence here; do not promote it to a
        # runtime/writer authorization and do not guess for other anomalies.
        try:
            from .rare_outliers import _probe_archivotmp_recovery
            recovery = _probe_archivotmp_recovery(raw)
        except Exception:
            recovery = None
        if recovery and recovery.get("classification") == "TGA_DIMENSIONS_SINGLE_BIT_CORRUPT_RECOVERABLE_PREVIEW_ONLY":
            standard = bytes.fromhex(recovery["recovered_header_hex"]) + raw[18:]
        else:
            raise PreviewDecodeError(f"TGA_ADAPTER_FAILED:{type(exc).__name__}:{exc}") from exc
    try:
        return tga_bytes_to_png_bytes(standard)
    except Exception as exc:
        raise PreviewDecodeError(f"TGA_RENDER_FAILED:{type(exc).__name__}:{exc}") from exc


def _decode_bmp_for_preview(path: pathlib.Path, project_root: pathlib.Path) -> bytes:
    raw = path.read_bytes()
    if raw[:2] == b"BM":
        return raw

    legacy_error: Exception | None = None
    try:
        core = _load_root_module(str(project_root.resolve()), "pt_character_texture_v1_4.py", "pt_ui_bmp_core")
        info = core.inspect_bmp_bytes(raw)
        standard = core.decode_editable(raw, info)
        if standard[:2] != b"BM":
            raise RuntimeError("BMP_ADAPTER_DID_NOT_RETURN_STANDARD_HEADER")
        # Existing family proof promises only the file header is normalized.
        if standard[14:] != raw[14:]:
            raise RuntimeError("BMP_ADAPTER_CHANGED_NON_HEADER_BYTES")
        return standard
    except Exception as exc:
        legacy_error = exc

    try:
        from .rare_support import decode_ship_bmp_bytes
        standard, _meta = decode_ship_bmp_bytes(raw)
        return standard
    except Exception as ship_exc:
        raise PreviewDecodeError(
            "BMP_ADAPTER_FAILED:"
            f"legacy={type(legacy_error).__name__}:{legacy_error};"
            f"ship={type(ship_exc).__name__}:{ship_exc}"
        ) from ship_exc


@lru_cache(maxsize=64)
def _preview_image_bytes_cached(
    path_text: str, project_root_text: str, mtime_ns: int, size: int, max_bytes: int
) -> tuple[bytes, str]:
    # mtime/size are deliberately part of the cache key. They invalidate a
    # decoded preview after an external client file update without touching the
    # source tree or requiring a manual cache clear.
    path = pathlib.Path(path_text)
    project_root = pathlib.Path(project_root_text)
    ext = path.suffix.lower()
    if ext == ".tga":
        raw = _decode_tga_for_preview(path, project_root)
        mime = "image/png"
    elif ext == ".bmp":
        raw = _decode_bmp_for_preview(path, project_root)
        mime = "image/bmp"
    elif ext in _BROWSER_NATIVE_EXTS:
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    else:
        raise PreviewDecodeError(f"PREVIEW_EXTENSION_UNSUPPORTED:{ext or '<none>'}")
    if len(raw) > max_bytes:
        raise PreviewDecodeError(f"PREVIEW_TOO_LARGE:{len(raw)}")
    return raw, mime


def preview_image_bytes(path: pathlib.Path, project_root: pathlib.Path, max_bytes: int = 64 * 1024 * 1024) -> tuple[bytes, str]:
    """Return browser-renderable bytes without modifying the source client.

    The bounded in-memory cache is keyed by the physical file revision so
    gallery/entity rerenders do not repeatedly decode the same protected TGA/BMP.
    """
    path = pathlib.Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    st = path.stat()
    return _preview_image_bytes_cached(
        str(path.resolve()), str(pathlib.Path(project_root).resolve()),
        int(st.st_mtime_ns), int(st.st_size), int(max_bytes),
    )
