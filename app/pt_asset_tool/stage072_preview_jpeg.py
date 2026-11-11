"""Strict read-only preview conversion: shipped JPEG/JFIF bytes named .bmp.

Never rewrite the physical game asset or change its serialized path.  The
result is a real BMP at the same *logical* overlay path, solely for Blender.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


MAX_JPEG_PIXELS = 25_000_000
MAX_FILE_BYTES = 32 * 1024 * 1024


def is_jfif_in_bmp(data: bytes) -> bool:
    return (len(data) >= 11 and data[:4] == b'\xff\xd8\xff\xe0'
            and data[6:10] == b'JFIF' and data[10] == 0)


def convert_jfif_bmp_preview(source: Path, target: Path) -> dict:
    """Only used after exact physical resolution by the normal client resolver.

    Invalid JPEG, missing Pillow, overly large payload or changed RGB pixels
    fail closed.  ``source`` is opened read-only and remains untouched.
    """
    from PIL import Image, ImageFile
    source = Path(source)
    target = Path(target)
    raw = source.read_bytes()
    if len(raw) > MAX_FILE_BYTES or not is_jfif_in_bmp(raw):
        raise ValueError('NOT_JPEG_JFIF_WITH_BMP_EXTENSION')
    try:
        with Image.open(source) as check:
            if check.format != 'JPEG':
                raise ValueError('PIL_SOURCE_IS_NOT_JPEG')
            if check.width <= 0 or check.height <= 0 or check.width * check.height > MAX_JPEG_PIXELS:
                raise ValueError('JPEG_IMAGE_DIMENSIONS_OUT_OF_SCOPE')
            check.verify()
        # Ensure a complete image can actually be decoded; verify() checks the
        # header but may not validate that the compressed scan is complete.
        with Image.open(source) as image:
            if image.format != 'JPEG':
                raise ValueError('PIL_REOPEN_IS_NOT_JPEG')
            rgb = image.convert('RGB')
            rgb.load()
            expected = rgb.tobytes()
            dimensions = rgb.size
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.jpeg-preview.tmp')
            try:
                rgb.save(temp, format='BMP')
                with Image.open(temp) as roundtrip:
                    if roundtrip.format != 'BMP' or roundtrip.size != dimensions or roundtrip.convert('RGB').tobytes() != expected:
                        raise ValueError('JPEG_TO_BMP_PREVIEW_PIXEL_ROUNDTRIP_MISMATCH')
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
        if hashlib.sha256(source.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
            target.unlink(missing_ok=True)
            raise RuntimeError('SOURCE_CHANGED_WHILE_PREPARING_PREVIEW')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {
        'source_format': 'JPEG_JFIF_MISNAMED_BMP',
        'preview_format': 'STANDARD_BMP_RGB',
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'width': dimensions[0], 'height': dimensions[1],
        'pixel_roundtrip_exact': True,
        'preview_only': True,
        'game_asset_modified': False,
    }
