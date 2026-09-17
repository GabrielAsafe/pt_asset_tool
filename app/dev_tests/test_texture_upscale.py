import io
from pathlib import Path

import pytest
Image = pytest.importorskip("PIL.Image")

from pt_asset_tool.texture_upscale import (
    _runtime_decrypt_bmp,
    _runtime_decrypt_tga,
    _runtime_encrypt_bmp_header,
    inspect_texture,
    upscale_tree,
)
from pt_protected_tga_v1 import protect_header


def _png_bytes(size=(8, 8)):
    im = Image.new("RGBA", size, (100, 80, 60, 200))
    b = io.BytesIO(); im.save(b, format="PNG"); return b.getvalue()


def _tga_bytes(size=(8, 8)):
    im = Image.new("RGBA", size, (100, 80, 60, 200))
    b = io.BytesIO(); im.save(b, format="TGA"); return b.getvalue()


def _bmp_bytes(size=(8, 8)):
    im = Image.new("RGB", size, (100, 80, 60))
    b = io.BytesIO(); im.save(b, format="BMP"); return b.getvalue()


def test_protected_tga_upscale_runtime_decrypts(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    std = _tga_bytes()
    protected = protect_header(std[:18], "FULL18") + std[18:]
    src = root / "Image" / "Character" / "hero.tga"; src.parent.mkdir(parents=True); src.write_bytes(protected)

    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    raw = (out / "Image" / "Character" / "hero.tga").read_bytes()
    assert raw[:2] == b"G8"
    with Image.open(io.BytesIO(_runtime_decrypt_tga(raw))) as im:
        assert im.size == (16, 16)


def test_protected_bmp_upscale_runtime_decrypts(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    std = _bmp_bytes()
    protected = _runtime_encrypt_bmp_header(std, b"PX" + b"\0" * 12)
    src = root / "Image" / "Terrain" / "ground.bmp"; src.parent.mkdir(parents=True); src.write_bytes(protected)

    rec, _ = inspect_texture(src)
    assert rec.protected
    report = upscale_tree(root, out, scale=4, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    raw = (out / "Image" / "Terrain" / "ground.bmp").read_bytes()
    assert raw[:2] != b"BM"
    with Image.open(io.BytesIO(_runtime_decrypt_bmp(raw))) as im:
        assert im.size == (32, 32)


def test_ui_paths_are_skipped_by_default(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    src = root / "game" / "Login" / "button.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"skipped_ui_pixel_crop_risk": 1}
    assert not (out / "game" / "Login" / "button.png").exists()


def test_existing_output_is_not_overwritten_without_explicit_flag(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir(); out.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    dest = out / "Image" / "Character" / "hero.png"; dest.parent.mkdir(parents=True); dest.write_bytes(b"KEEP-ME")

    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"failed": 1}
    assert "output already exists" in report["records"][0]["reason"]
    assert dest.read_bytes() == b"KEEP-ME"
    assert report["source_client_modified"] is False


def test_manifest_inside_source_is_rejected(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path / "app")
    try:
        mod.main(["scan", "--client-root", str(root), "--manifest", str(root / "manifest.json")])
    except ValueError as exc:
        assert "manifest must be outside" in str(exc)
    else:
        raise AssertionError("manifest inside source was accepted")
    assert not (root / "manifest.json").exists()


def test_default_scan_manifest_uses_project_pt_build_not_cwd(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    project = tmp_path / "tool" / "app"; project.mkdir(parents=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    monkeypatch.chdir(root)
    assert mod.main(["scan", "--client-root", str(root)]) == 0
    manifests = list((project / "pt_build" / "texture_upscale" / "scans").glob("scan_*.json"))
    assert len(manifests) == 1
    assert not (root / "pt_build").exists()


def test_single_include_limits_processing(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    a = root / "Image" / "Character" / "a.png"; a.parent.mkdir(parents=True); a.write_bytes(_png_bytes())
    b = root / "Image" / "Character" / "b.png"; b.write_bytes(_png_bytes())
    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True,
                          include_patterns=["Image/Character/a.png"])
    assert report["status_counts"] == {"upscaled": 1}
    assert (out / "Image" / "Character" / "a.png").is_file()
    assert not (out / "Image" / "Character" / "b.png").exists()


def test_include_exact_does_not_expand_glob_metacharacters(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    d = root / "Image" / "Character"; d.mkdir(parents=True)
    (d / "hero[1].png").write_bytes(_png_bytes())
    (d / "hero1.png").write_bytes(_png_bytes())
    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True,
                          include_exact=["Image/Character/hero[1].png"])
    assert report["status_counts"] == {"upscaled": 1}
    assert (out / "Image" / "Character" / "hero[1].png").is_file()
    assert not (out / "Image" / "Character" / "hero1.png").exists()


def test_realesrgan_wrapper_preserves_resampled_alpha(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    exe = tmp_path / "realesrgan-ncnn-vulkan"; exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(mod, "_resolve_realesrgan", lambda executable: str(exe))

    def fake_run(cmd, text, capture_output, cwd):
        inp = Path(cmd[cmd.index("-i") + 1]); out = Path(cmd[cmd.index("-o") + 1]); scale = int(cmd[cmd.index("-s") + 1])
        with Image.open(inp) as im:
            im.convert("RGBA").resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST).save(out, format="PNG")
        class CP:
            returncode = 0
            stdout = ""
            stderr = ""
        return CP()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    image = Image.new("RGBA", (3, 2), (10, 20, 30, 0))
    alpha = Image.new("L", (3, 2))
    alpha.putdata([0, 64, 128, 192, 224, 255])
    image.putalpha(alpha)
    result, cmd = mod.upscale_realesrgan(image, scale=2, executable=None, model="realesrgan-x4plus", tile=256, gpu=0)
    assert result.size == (6, 4)
    expected_alpha = alpha.resize((6, 4), Image.Resampling.LANCZOS)
    assert result.getchannel("A").tobytes() == expected_alpha.tobytes()
    assert "-s" in cmd and cmd[cmd.index("-s") + 1] == "2"


def test_output_root_inside_source_is_rejected(tmp_path: Path):
    root = tmp_path / "client"; root.mkdir()
    try:
        upscale_tree(root, root / "pt_build", scale=2, backend="lanczos", include_ui=False,
                     extra_excludes=[], max_dimension=8192, executable=None,
                     model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    except ValueError as exc:
        assert "output root must be outside" in str(exc)
    else:
        raise AssertionError("output root inside source was accepted")


def test_overwrite_requires_explicit_flag_and_then_replaces_output(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir(); out.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    dest = out / "Image" / "Character" / "hero.png"; dest.parent.mkdir(parents=True); dest.write_bytes(b"OLD")
    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True,
                          overwrite=True)
    assert report["status_counts"] == {"upscaled": 1}
    assert dest.read_bytes() != b"OLD"
    with Image.open(dest) as im:
        assert im.size == (16, 16)


def test_invalid_encoded_candidate_is_never_published(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "encode_texture", lambda *args, **kwargs: b"not-an-image")
    report = mod.upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                              extra_excludes=[], max_dimension=8192, executable=None,
                              model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"failed": 1}
    assert not (out / "Image" / "Character" / "hero.png").exists()


def test_manifest_cannot_clobber_output_overlay(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    out = tmp_path / "out"
    try:
        mod.main(["run", "--client-root", str(root), "--output-root", str(out),
                  "--include-exact", "Image/Character/hero.png", "--backend", "lanczos",
                  "--manifest", str(out / "Image" / "Character" / "hero.png")])
    except ValueError as exc:
        assert "manifest must be outside the output overlay" in str(exc)
    else:
        raise AssertionError("manifest inside output overlay was accepted")


def test_protected_tga_keep_00_16_mode_is_preserved(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    std = _tga_bytes()
    protected = protect_header(std[:18], "KEEP_00_16") + std[18:]
    src = root / "Image" / "Character" / "legacy.tga"; src.parent.mkdir(parents=True); src.write_bytes(protected)

    before, _ = inspect_texture(src)
    assert before.protected is True
    assert before.protection_mode == "KEEP_00_16"
    report = upscale_tree(root, out, scale=2, backend="lanczos", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    after, _ = inspect_texture(out / "Image" / "Character" / "legacy.tga")
    assert after.protected is True
    assert after.protection_mode == "KEEP_00_16"
    assert (after.width, after.height) == (16, 16)


def test_run_requires_explicit_selection_or_all(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path / "app")
    with pytest.raises(ValueError, match="requires --include/--include-exact or explicit --all"):
        mod.main(["run", "--client-root", str(root), "--backend", "lanczos"])


def test_explicit_manifest_is_not_overwritten_without_flag(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    project = tmp_path / "app"; project.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    manifest = tmp_path / "scan.json"
    assert mod.main(["scan", "--client-root", str(root), "--manifest", str(manifest)]) == 0
    original = manifest.read_bytes()
    with pytest.raises(FileExistsError, match="output already exists"):
        mod.main(["scan", "--client-root", str(root), "--manifest", str(manifest)])
    assert manifest.read_bytes() == original


def test_all_is_explicit_and_cannot_mix_with_selection(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path / "app")
    with pytest.raises(ValueError, match="--all cannot be combined"):
        mod.main(["run", "--client-root", str(root), "--all", "--include-exact", "Image/Character/hero.png"])
