"""Opt-in restoration and custom NCNN models: safe defaults and regression checks."""
import io
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")

from pt_asset_tool import texture_upscale as m
from pt_asset_tool.ui_actions import build_command


def sample_rgba():
    im = Image.new("RGBA", (9, 9), (120, 100, 70, 255))
    im.putpixel((4, 4), (255, 0, 255, 17))
    im.putpixel((0, 0), (1, 2, 3, 0))
    return im


def test_denoising_is_opt_in_and_preserves_exact_alpha():
    im = sample_rgba()
    assert m.clean_compression_artifacts(im, "off") is im
    light = m.clean_compression_artifacts(im, "light")
    medium = m.clean_compression_artifacts(im, "medium")
    assert light.getchannel("A").tobytes() == im.getchannel("A").tobytes()
    assert medium.getchannel("A").tobytes() == im.getchannel("A").tobytes()
    assert light.getpixel((4, 4))[0] < 255
    assert medium.getpixel((4, 4))[0] < light.getpixel((4, 4))[0]
    with pytest.raises(ValueError):
        m.clean_compression_artifacts(im, "magic")


def test_technical_map_detection_is_conservative():
    assert m.detect_texture_role("Image/Field/brick_n.tga") == "normal_candidate"
    assert m.detect_texture_role("Image/Field/brick_normal.png") == "normal_candidate"
    assert m.detect_texture_role("Image/Field/brick_height.bmp") == "height_candidate"
    assert m.detect_texture_role("Image/Field/normal_stone.png") == "normal_candidate"
    assert m.detect_texture_role("Image/Field/brick_diffuse.png") == "diffuse_candidate"
    assert m.detect_texture_role("Image/Field/unknown.tga") == "diffuse_candidate"


def test_technical_candidates_are_skipped_until_explicit_authorization(tmp_path: Path):
    root = tmp_path / "client"
    p = root / "Image" / "Field" / "wall_n.png"
    p.parent.mkdir(parents=True)
    sample_rgba().save(p)
    out = tmp_path / "out"
    kw = dict(scale=2, backend="lanczos", profile="faithful", include_ui=False,
              extra_excludes=[], max_dimension=8192, executable=None,
              model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    report = m.upscale_tree(root, out, **kw)
    assert report["status_counts"] == {"skipped_technical_map_review": 1}
    assert report["records"][0]["texture_role"] == "normal_candidate"
    assert not (out / "Image" / "Field" / "wall_n.png").exists()
    report = m.upscale_tree(root, out, protect_technical_maps=False, **kw)
    assert report["status_counts"] == {"upscaled": 1}


def test_restore_pipeline_manifest_records_denoise_and_resumable_settings(tmp_path: Path):
    root = tmp_path / "client"
    p = root / "Image" / "Field" / "stone.png"
    p.parent.mkdir(parents=True)
    sample_rgba().save(p)
    out = tmp_path / "out"
    report = m.upscale_tree(root, out, scale=2, backend="lanczos", profile="balanced",
                            denoise="medium", include_ui=False, extra_excludes=[],
                            max_dimension=8192, executable=None, model="realesrgan-x4plus",
                            tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    assert report["denoise"] == "medium"
    assert report["protect_technical_maps"] is True
    assert report["records"][0]["denoise_level"] == "medium"
    assert report["records"][0]["model_used"] is None
    assert report["records"][0]["source_unchanged"] is True
    with Image.open(out / "Image" / "Field" / "stone.png") as im:
        assert im.size == (18, 18)
    assert p.exists() and p.read_bytes() != (out / "Image" / "Field" / "stone.png").read_bytes()


def test_custom_ncnn_model_dir_and_validation(tmp_path: Path, monkeypatch):
    exe = tmp_path / "realesrgan-ncnn-vulkan"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(m, "_resolve_realesrgan", lambda executable: str(exe))
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "Game4x.param").write_bytes(b"stub")
    (directory / "Game4x.bin").write_bytes(b"stub")
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        inp, out = Path(cmd[cmd.index("-i") + 1]), Path(cmd[cmd.index("-o") + 1])
        with Image.open(inp) as im:
            im.resize((im.width * 2, im.height * 2)).save(out)
        return type("Done", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    img, cmd = m.upscale_realesrgan(sample_rgba(), scale=2, executable=None,
                                    model="Game4x", model_dir=directory, tile=64, gpu=0)
    assert img.size == (18, 18)
    assert cmd[cmd.index("-m") + 1] == str(directory)
    assert len(commands) == 1
    with pytest.raises(FileNotFoundError):
        m.upscale_realesrgan(sample_rgba(), scale=2, executable=None,
                              model="Missing4x", model_dir=directory, tile=64, gpu=0)
    for bad in ("../../outside", "Game4x.pth", "foo/bar", ""):
        with pytest.raises(ValueError):
            m.upscale_realesrgan(sample_rgba(), scale=2, executable=None,
                                  model=bad, model_dir=directory, tile=64, gpu=0)


def test_gui_pipeline_arguments_are_opt_in(tmp_path: Path):
    (tmp_path / "pt_asset.py").write_text("# stub", encoding="utf-8")
    cmd = build_command(tmp_path, "upscale_texture", "Image/Field/wall.tga", {
        "scale": 2, "backend": "realesrgan", "profile": "detail",
        "model": "Game4x", "model_dir": "/home/user/models", "denoise": "light",
    })
    assert cmd[cmd.index("--denoise") + 1] == "light"
    assert cmd[cmd.index("--model") + 1] == "Game4x"
    assert cmd[cmd.index("--model-dir") + 1] == "/home/user/models"
    with pytest.raises(ValueError):
        build_command(tmp_path, "upscale_texture", "Image/Field/wall.tga",
                      {"backend": "lanczos", "profile": "pixel-art", "denoise": "light"})


def test_invalid_denoise_fails_before_processing(tmp_path: Path):
    root = tmp_path / "client"
    root.mkdir()
    with pytest.raises(ValueError):
        m.upscale_tree(root, tmp_path / "out", scale=2, backend="lanczos", denoise="strong",
                       include_ui=False, extra_excludes=[], max_dimension=8192,
                       executable=None, model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
