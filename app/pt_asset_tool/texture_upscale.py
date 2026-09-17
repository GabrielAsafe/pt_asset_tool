from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover - environment-specific
    Image = None
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

TOOL = "PT_TEXTURE_UPSCALE_V1"
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
        info = inspect_tga_bytes(raw)
        decoded, _ = decode_tga_bytes(raw)
        im = _open_from_bytes(decoded)
        rec.format = str(info["format"])
        rec.protected = bool(info["protected"])
        rec.protection_mode = info.get("protection_mode")
        meta = info
    elif rec.suffix == ".bmp":
        info = inspect_bmp_bytes(raw)
        decoded = decode_bmp_editable(raw, info)
        im = _open_from_bytes(decoded)
        rec.format = str(info["format"])
        rec.protected = not bool(info["standard"])
        meta = info
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
        decoded, _ = decode_tga_bytes(raw)
        return _open_from_bytes(decoded).convert("RGBA" if rec.has_alpha else "RGB")
    if rec.suffix == ".bmp":
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
        mode = rec.protection_mode if rec.protection_mode in {"FULL18", "KEEP_00_16"} else "FULL18"
        return protect_tga_header(standard[:18], mode) + standard[18:]
    if rec.suffix == ".bmp" and rec.protected:
        return _runtime_encrypt_bmp_header(standard, source_raw[:14])
    return standard


def _alpha_channel(image, size: tuple[int, int]):
    _need_pillow()
    if "A" not in image.getbands():
        return None
    return image.getchannel("A").resize(size, Image.Resampling.LANCZOS)


def upscale_lanczos(image, scale: int):
    _need_pillow()
    target = (image.width * scale, image.height * scale)
    return image.resize(target, Image.Resampling.LANCZOS)


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
    }


def upscale_realesrgan(
    image,
    *,
    scale: int,
    executable: str | None,
    model: str,
    tile: int,
    gpu: int,
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
) -> dict:
    _need_pillow()
    if scale not in (2, 3, 4):
        raise ValueError("scale must be 2, 3, or 4")

    root = root.resolve()
    output_root = output_root.resolve()
    _ensure_outside_source(root, output_root, "output root")
    include_patterns = list(include_patterns or [])
    include_exact = list(include_exact or [])

    records: list[dict] = []
    counts: dict[str, int] = {}
    source_changed = False

    for source in iter_textures(root):
        rel = source.relative_to(root).as_posix()
        if not _selected(rel, include_patterns, include_exact):
            continue
        started = time.monotonic()
        rec = TextureRecord(source=rel, suffix=source.suffix.lower(), risk_class=_risk_class(rel))
        try:
            rec, meta = inspect_texture(source)
            rec.source = rel
            rec.risk_class = _risk_class(rel)
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
            if backend == "lanczos":
                result = upscale_lanczos(image, scale)
                command = None
            elif backend == "realesrgan":
                result, command = upscale_realesrgan(
                    image,
                    scale=scale,
                    executable=executable,
                    model=model,
                    tile=tile,
                    gpu=gpu,
                )
            else:
                raise ValueError(f"unknown backend: {backend}")

            encoded = encode_texture(result, source_raw, rec, meta)

            # Verify the encoded bytes before they become a published output.
            if rec.suffix == ".tga" and rec.protected:
                verify_bytes, _verify_meta = decode_tga_bytes(encoded)
            elif rec.suffix == ".bmp" and rec.protected:
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
            rec.reason = " ".join(command) if command else "Pillow Lanczos"
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
        if fail_fast and rec.status == "failed":
            break

    return {
        "tool": TOOL,
        "action": "upscale",
        "root": str(root),
        "output_root": str(output_root),
        "scale": scale,
        "backend": backend,
        "model": model if backend == "realesrgan" else None,
        "tile": tile if backend == "realesrgan" else None,
        "gpu": gpu if backend == "realesrgan" else None,
        "max_dimension": max_dimension,
        "include_ui": include_ui,
        "include_patterns": include_patterns,
        "include_exact": include_exact,
        "overwrite": overwrite,
        "texture_count": len(records),
        "status_counts": counts,
        "records": records,
        "source_write_attempted": False,
        "source_client_modified": source_changed,
    }


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pt_texture_upscale",
        description="Upscale Summit/Priston textures into pt_build or another separate tree while preserving protected TGA/BMP headers.",
    )
    sp = p.add_subparsers(dest="command", required=True)

    s = sp.add_parser("scan", help="classify supported textures without writing the source tree")
    s.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    s.add_argument("--manifest", type=Path)
    s.add_argument("--include", action="append", default=[], help="glob against /relative/path; repeatable; omitted means all textures")
    s.add_argument("--include-exact", action="append", default=[], help="exact client-relative path; repeatable; intended for UI/single-asset runs")
    s.add_argument("--include-ui", action="store_true", help="do not apply conservative UI/atlas exclusions")
    s.add_argument("--exclude", action="append", default=[], help="glob against /relative/path; repeatable")

    u = sp.add_parser("run", help="upscale to a separate output tree; never writes the source/client")
    u.add_argument("--client-root", type=Path, help="defaults to the configured/discovered client root")
    u.add_argument("--output-root", type=Path, help="defaults to a unique app/pt_build/texture_upscale/runs/<id>/overlay tree")
    u.add_argument("--manifest", type=Path)
    u.add_argument("--include", action="append", default=[], help="glob against /relative/path; repeatable")
    u.add_argument("--include-exact", action="append", default=[], help="exact client-relative path; repeatable; intended for UI/single-asset runs")
    u.add_argument("--all", action="store_true", help="explicitly process every supported texture under the client root")
    u.add_argument("--scale", type=int, choices=(2, 3, 4), default=4)
    u.add_argument("--backend", choices=("realesrgan", "lanczos"), default="lanczos")
    u.add_argument("--realesrgan", help="path/name of realesrgan-ncnn-vulkan executable")
    u.add_argument("--model", default="realesrgan-x4plus")
    u.add_argument("--tile", type=int, default=256, help="Vulkan tile size; 256 is conservative for 8GB-class GPUs")
    u.add_argument("--gpu", type=int, default=0)
    u.add_argument("--max-dimension", type=int, default=8192)
    u.add_argument("--include-ui", action="store_true", help="upscale paths normally excluded as pixel-crop/atlas risks")
    u.add_argument("--exclude", action="append", default=[], help="glob against /relative/path; repeatable")
    u.add_argument("--overwrite", action="store_true", help="explicitly allow replacing an existing output and/or explicit manifest")
    u.add_argument("--fail-fast", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _resolve_client_root(args.client_root)

    if args.command == "run" and not args.all and not args.include and not args.include_exact:
        raise ValueError("texture-upscale run requires --include/--include-exact or explicit --all")
    if args.command == "run" and args.all and (args.include or args.include_exact):
        raise ValueError("--all cannot be combined with --include or --include-exact")

    default_run_dir: Path | None = None
    output_root: Path | None = None
    if args.command == "run":
        if args.output_root is None:
            default_run_dir = PROJECT_ROOT / "pt_build" / "texture_upscale" / "runs" / _run_stamp()
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
        )

    _json_dump(manifest, report, overwrite=manifest_overwrite)

    summary = {
        "tool": TOOL,
        "action": report["action"],
        "texture_count": report["texture_count"],
        "status_counts": report["status_counts"],
        "manifest": str(manifest),
        "output_root": report.get("output_root"),
        "source_write_attempted": False,
        "source_client_modified": bool(report.get("source_client_modified")),
    }
    print(json.dumps(summary, indent=2))
    failed = int(report["status_counts"].get("failed", 0))
    return 1 if failed or summary["source_client_modified"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
