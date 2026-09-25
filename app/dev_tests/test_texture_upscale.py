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

    def fake_run(cmd, text, capture_output, cwd, env=None):
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


def test_balanced_profile_records_quality_metrics_and_preserves_alpha(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    image = Image.new("RGBA", (4, 4), (20, 40, 60, 0))
    alpha = Image.new("L", (4, 4))
    alpha.putdata([0, 32, 64, 96, 128, 160, 192, 224, 255, 224, 192, 160, 128, 96, 64, 32])
    image.putalpha(alpha)
    b = io.BytesIO(); image.save(b, format="PNG")
    src = root / "Image" / "Character" / "alpha.png"; src.parent.mkdir(parents=True); src.write_bytes(b.getvalue())
    report = upscale_tree(root, out, scale=2, backend="lanczos", profile="balanced", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    rec = report["records"][0]
    assert rec["quality_profile"] == "balanced"
    assert rec["backend_used"] == "lanczos"
    assert isinstance(rec["detail_metric_before"], float)
    assert isinstance(rec["detail_metric_after"], float)
    with Image.open(out / "Image" / "Character" / "alpha.png") as result:
        assert result.size == (8, 8)
        expected = alpha.resize((8, 8), Image.Resampling.LANCZOS)
        assert result.getchannel("A").tobytes() == expected.tobytes()


def test_auto_detail_falls_back_to_lanczos_when_ai_is_unavailable(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "_resolve_realesrgan", lambda executable: (_ for _ in ()).throw(FileNotFoundError("missing")))
    report = mod.upscale_tree(root, out, scale=2, backend="auto", profile="detail", include_ui=False,
                              extra_excludes=[], max_dimension=8192, executable=None,
                              model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["status_counts"] == {"upscaled": 1}
    assert report["backend_counts"] == {"lanczos": 1}
    assert report["records"][0]["backend_used"] == "lanczos"


def test_pixel_art_profile_uses_nearest_and_rejects_ai(tmp_path: Path):
    from pt_asset_tool.texture_upscale import upscale_lanczos
    image = Image.new("RGB", (2, 1))
    image.putdata([(0, 0, 0), (255, 255, 255)])
    result = upscale_lanczos(image, 2, profile="pixel-art")
    pixels = result.get_flattened_data() if hasattr(result, "get_flattened_data") else result.getdata()
    assert list(pixels) == [(0, 0, 0), (0, 0, 0), (255, 255, 255), (255, 255, 255)] * 2
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    with pytest.raises(ValueError, match="pixel-art profile cannot use realesrgan"):
        upscale_tree(root, out, scale=2, backend="realesrgan", profile="pixel-art", include_ui=False,
                     extra_excludes=[], max_dimension=8192, executable=None,
                     model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)


def test_auto_balanced_reports_conservative_lanczos_decision(tmp_path: Path):
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    report = upscale_tree(root, out, scale=2, backend="auto", profile="balanced", include_ui=False,
                          extra_excludes=[], max_dimension=8192, executable=None,
                          model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["backend_counts"] == {"lanczos": 1}
    assert report["backend_decision"] == "AUTO_CONSERVATIVE_PROFILE_LANCZOS"
    assert report["ai_enhancement_used"] is False
    assert report["enhancement_class"] == "DETERMINISTIC_RESAMPLE_SHARPEN"
    assert report["records"][0]["backend_decision"] == "AUTO_CONSERVATIVE_PROFILE_LANCZOS"


def test_auto_detail_reports_ai_unavailable_fallback_reason(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; out = tmp_path / "out"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    monkeypatch.setattr(mod, "_resolve_realesrgan", lambda executable: (_ for _ in ()).throw(FileNotFoundError("missing-ai")))
    report = mod.upscale_tree(root, out, scale=2, backend="auto", profile="detail", include_ui=False,
                              extra_excludes=[], max_dimension=8192, executable=None,
                              model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True)
    assert report["backend_counts"] == {"lanczos": 1}
    assert report["backend_decision"] == "AUTO_DETAIL_REALESRGAN_UNAVAILABLE_FALLBACK_LANCZOS"
    assert "missing-ai" in report["backend_fallback_reason"]
    assert report["ai_enhancement_used"] is False


def test_capabilities_command_does_not_require_client_root(monkeypatch, capsys):
    import pt_asset_tool.texture_upscale as mod
    monkeypatch.setattr(mod, "capability_status", lambda executable=None: {"realesrgan_ready": False, "auto_profile_policy": {"balanced": "lanczos_conservative"}})
    assert mod.main(["capabilities"]) == 0
    out = capsys.readouterr().out
    assert "realesrgan_ready" in out
    assert "lanczos_conservative" in out


def test_default_run_uses_enhancement_workspace(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    src = root / "Image" / "Character" / "hero.png"; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes())
    project = tmp_path / "app"; project.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    assert mod.main(["run", "--client-root", str(root), "--include-exact", "Image/Character/hero.png", "--scale", "2", "--backend", "lanczos"]) == 0
    manifests = list((project / "pt_build" / "texture_upscale" / "runs").glob("*/manifest.json"))
    assert len(manifests) == 1
    report = __import__("json").loads(manifests[0].read_text(encoding="utf-8"))
    assert "/pt_build/texture_upscale/runs/" in report["output_root"].replace("\\", "/")
    assert (Path(report["output_root"]) / "Image" / "Character" / "hero.png").is_file()


def test_publish_and_restore_enhancement_transaction(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    rel = "Image/Character/hero.png"
    src = root / rel; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes((4, 4)))
    original = src.read_bytes()
    project = tmp_path / "app"; project.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    assert mod.main(["run", "--client-root", str(root), "--include-exact", rel, "--scale", "2", "--backend", "lanczos"]) == 0
    status = mod.enhancement_status(project, root, rel)
    assert status["candidate_ready"] is True
    assert status["can_restore"] is False
    result = mod.publish_enhancement(root, project, rel, confirm=mod.ENHANCEMENT_PUBLISH_CONFIRM)
    assert result["state"] == "APPLIED_VERIFIED"
    assert src.read_bytes() != original
    status = mod.enhancement_status(project, root, rel)
    assert status["candidate_ready"] is False
    assert status["can_restore"] is True
    restored = mod.restore_enhancement(root, project, rel, confirm=mod.ENHANCEMENT_RESTORE_CONFIRM)
    assert restored["state"] == "RESTORED_VERIFIED"
    assert src.read_bytes() == original
    status = mod.enhancement_status(project, root, rel)
    assert status["can_restore"] is False


def test_publish_rejects_source_drift_after_candidate(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    rel = "Image/Character/hero.png"
    src = root / rel; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes((4, 4)))
    project = tmp_path / "app"; project.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    assert mod.main(["run", "--client-root", str(root), "--include-exact", rel, "--scale", "2", "--backend", "lanczos"]) == 0
    src.write_bytes(_png_bytes((5, 5)))
    with pytest.raises(RuntimeError, match="NO_ENHANCEMENT_CANDIDATE_FOR_CURRENT_CLIENT_HASH"):
        mod.publish_enhancement(root, project, rel, confirm=mod.ENHANCEMENT_PUBLISH_CONFIRM)


def test_restore_rejects_external_drift(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod
    root = tmp_path / "client"; root.mkdir()
    rel = "Image/Character/hero.png"
    src = root / rel; src.parent.mkdir(parents=True); src.write_bytes(_png_bytes((4, 4)))
    project = tmp_path / "app"; project.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    assert mod.main(["run", "--client-root", str(root), "--include-exact", rel, "--scale", "2", "--backend", "lanczos"]) == 0
    mod.publish_enhancement(root, project, rel, confirm=mod.ENHANCEMENT_PUBLISH_CONFIRM)
    src.write_bytes(_png_bytes((6, 6)))
    with pytest.raises(RuntimeError, match="CLIENT_DRIFT_AFTER_ENHANCEMENT"):
        mod.restore_enhancement(root, project, rel, confirm=mod.ENHANCEMENT_RESTORE_CONFIRM)


def test_bulk_enhancement_publish_and_restore_batch_is_verified(tmp_path: Path, monkeypatch):
    import json
    import pt_asset_tool.texture_upscale as mod

    project = tmp_path / "tool" / "app"
    project.mkdir(parents=True)
    client = tmp_path / "Área de Trabalho" / "cliente"
    client.mkdir(parents=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)

    for name, color in [("a.png", (10, 20, 30, 255)), ("b.png", (40, 50, 60, 255))]:
        p = client / "Image" / "Character" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGBA", (4, 4), color)
        b = io.BytesIO(); im.save(b, format="PNG"); p.write_bytes(b.getvalue())

    originals = {p.name: p.read_bytes() for p in (client / "Image" / "Character").glob("*.png")}
    run_dir = mod.enhancement_root(project) / "runs" / "test-run"
    report = mod.upscale_tree(
        client, run_dir / "overlay", scale=2, backend="lanczos", profile="detail",
        include_ui=True, extra_excludes=[], max_dimension=8192, executable=None,
        model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True,
    )
    mod._json_dump(run_dir / "manifest.json", report, overwrite=False)
    assert report["status_counts"] == {"upscaled": 2}

    batch = mod.publish_enhancement_batch(
        client, project, manifest=run_dir / "manifest.json",
        confirm=mod.ENHANCEMENT_BATCH_PUBLISH_CONFIRM,
    )
    assert batch["state"] == "APPLIED_VERIFIED"
    assert batch["applied_count"] == 2
    assert all((client / "Image" / "Character" / name).read_bytes() != raw for name, raw in originals.items())

    status = mod.enhancement_batch_status(project)
    assert status["can_restore_batch"] is True
    assert status["latest_batch"]["state"] == "APPLIED_VERIFIED"

    restored = mod.restore_enhancement_batch(
        client, project, batch_manifest=Path(batch["batch_manifest"]),
        confirm=mod.ENHANCEMENT_BATCH_RESTORE_CONFIRM,
    )
    assert restored["state"] == "RESTORED_VERIFIED"
    assert restored["restored_count"] == 2
    assert all((client / "Image" / "Character" / name).read_bytes() == raw for name, raw in originals.items())
    data = json.loads(Path(batch["batch_manifest"]).read_text(encoding="utf-8"))
    assert data["state"] == "RESTORED_VERIFIED"


def test_bulk_publish_preflight_rejects_drift_before_any_client_write(tmp_path: Path, monkeypatch):
    import pt_asset_tool.texture_upscale as mod

    project = tmp_path / "tool" / "app"
    project.mkdir(parents=True)
    client = tmp_path / "client"
    client.mkdir()
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    for name in ("a.png", "b.png"):
        p = client / "Image" / "Character" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_png_bytes((4, 4)))
    before_a = (client / "Image" / "Character" / "a.png").read_bytes()

    run_dir = mod.enhancement_root(project) / "runs" / "test-run"
    report = mod.upscale_tree(
        client, run_dir / "overlay", scale=2, backend="lanczos", profile="detail",
        include_ui=True, extra_excludes=[], max_dimension=8192, executable=None,
        model="realesrgan-x4plus", tile=256, gpu=0, fail_fast=True,
    )
    mod._json_dump(run_dir / "manifest.json", report, overwrite=False)
    (client / "Image" / "Character" / "b.png").write_bytes(b"external drift")

    with pytest.raises(RuntimeError, match="ENHANCEMENT_BATCH_PREFLIGHT_FAILED"):
        mod.publish_enhancement_batch(
            client, project, manifest=run_dir / "manifest.json",
            confirm=mod.ENHANCEMENT_BATCH_PUBLISH_CONFIRM,
        )
    assert (client / "Image" / "Character" / "a.png").read_bytes() == before_a
    assert not list((mod.enhancement_root(project) / "batches").glob("*/batch.json"))


def test_enhancement_checkpoint_resume_reuses_verified_candidates(tmp_path: Path):
    import json
    import pt_asset_tool.texture_upscale as mod

    root = tmp_path / "client"; out = tmp_path / "enhancement" / "runs" / "x" / "overlay"
    root.mkdir(parents=True)
    d = root / "Image" / "Character"; d.mkdir(parents=True)
    (d / "a.png").write_bytes(_png_bytes((4, 4)))
    (d / "b.png").write_bytes(b"broken image")
    manifest = tmp_path / "enhancement" / "runs" / "x" / "manifest.json"
    first = mod.upscale_tree(
        root, out, scale=2, backend="lanczos", profile="detail", include_ui=True,
        extra_excludes=[], max_dimension=8192, executable=None, model="realesrgan-x4plus",
        tile=256, gpu=0, fail_fast=False, checkpoint_manifest=manifest, checkpoint_every=1,
    )
    assert first["status_counts"] == {"upscaled": 1, "failed": 1}
    assert manifest.is_file()
    previous = json.loads(manifest.read_text(encoding="utf-8"))
    (d / "b.png").write_bytes(_png_bytes((4, 4)))

    resumed = mod.upscale_tree(
        root, out, scale=2, backend="lanczos", profile="detail", include_ui=True,
        extra_excludes=[], max_dimension=8192, executable=None, model="realesrgan-x4plus",
        tile=256, gpu=0, fail_fast=False, overwrite=True, checkpoint_manifest=manifest,
        checkpoint_every=1, resume_records=previous["records"],
    )
    assert resumed["status_counts"] == {"upscaled": 2}
    by_name = {Path(r["source"]).name: r for r in resumed["records"]}
    assert by_name["a.png"].get("resumed") is True
    assert by_name["b.png"].get("resumed") is not True
