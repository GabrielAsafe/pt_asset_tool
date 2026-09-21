import io
import struct
from pathlib import Path

import pytest
Image = pytest.importorskip("PIL.Image")

from pt_asset_tool.texture_upscale import inspect_texture, upscale_tree


def _bmp_bytes(size=(8, 8)):
    im = Image.new("RGB", size, (100, 80, 60))
    b = io.BytesIO(); im.save(b, format="BMP"); return b.getvalue()


def test_standard_bmp_with_stale_declared_size_uses_pillow_compat_bridge(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    raw = bytearray(_bmp_bytes((8, 8)))
    struct.pack_into("<I", raw, 2, 2986040)
    src = root / "Image" / "Terrain" / "legacy_size.bmp"
    src.parent.mkdir(parents=True)
    src.write_bytes(raw)

    rec, meta = inspect_texture(src)
    assert rec.format == "BMP_STANDARD_PILLOW_COMPAT"
    assert rec.protected is False
    assert meta["codec_bridge"] == "pillow_standard_bmp"

    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=True,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    with Image.open(out / "Image" / "Terrain" / "legacy_size.bmp") as im:
        im.load()
        assert im.size == (16, 16)


def test_standard_bmp_compat_bridge_never_accepts_non_bm(tmp_path: Path):
    root = tmp_path / "client"; root.mkdir()
    src = root / "ship_like.bmp"
    src.write_bytes(b"A8" + bytes(100))
    with pytest.raises(Exception):
        inspect_texture(src)
