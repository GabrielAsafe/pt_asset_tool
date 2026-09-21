from __future__ import annotations

from pathlib import Path

from pt_asset_tool import dependencies, particle_service, texture_upscale
import pt_effect_preview


def test_enhancement_runtime_lives_under_pt_build(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PT_ENHANCEMENT_ROOT", raising=False)
    project = tmp_path / "repo" / "app"
    project.mkdir(parents=True)
    assert texture_upscale.enhancement_root(project) == (project / "pt_build" / "texture_upscale").resolve()


def test_realesrgan_discovers_bundled_binary(tmp_path: Path):
    project = tmp_path / "repo" / "app"
    bundled = tmp_path / "repo" / "tools" / "realesrgan" / "realesrgan-ncnn-vulkan"
    project.mkdir(parents=True)
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"stub")
    path, source = dependencies.resolve_realesrgan(project)
    assert path == str(bundled.resolve())
    assert source == "bundled with PT Asset Tool"


def test_dependency_report_has_actionable_install_and_reason(tmp_path: Path):
    project = tmp_path / "repo" / "app"
    project.mkdir(parents=True)
    report = dependencies.dependency_report(project)
    assert report["format"] == dependencies.FORMAT
    assert report["dependencies"]
    for row in report["dependencies"]:
        assert row["reason"]
        assert row["required_for"]
        assert row["install"]


def test_particle_service_stages_without_touching_client(tmp_path: Path):
    client = tmp_path / "client"
    build = tmp_path / "pt_build" / "devtest"
    client.mkdir()
    source = client / "Effect" / "Particle" / "Script" / "Demo.part"
    source.parent.mkdir(parents=True)
    original = b'LifeTime 1\r\nTexture "demo.tga"\r\n'
    source.write_bytes(original)

    inspected = particle_service.inspect_asset(client, build, "Effect/Particle/Script/Demo.part")
    assert inspected["authoring_status"] == "EDITABLE_STAGING"

    staged = particle_service.apply_stage_edit(
        client,
        build,
        {"asset": "Effect/Particle/Script/Demo.part", "selector": "lifetime[0]", "value": "2"},
    )
    assert staged["status"] == "PASS"
    assert staged["source_unchanged"] is True
    assert source.read_bytes() == original
    assert Path(staged["staged_candidate"]).is_file()
    assert build.resolve() in Path(staged["staged_candidate"]).resolve().parents


def test_particle_preview_accepts_global_command_prefix(tmp_path: Path):
    app = tmp_path / "app"
    app.mkdir()
    plan = app / "pt_build" / "devtest" / "effect_preview" / "demo.json"
    plan.parent.mkdir(parents=True)
    plan.write_text("{}", encoding="utf-8")
    cmd = pt_effect_preview.blender_command(
        app,
        plan,
        blender=["flatpak", "run", "--filesystem=home", "org.blender.Blender"],
    )
    assert cmd["args"][:4] == ["flatpak", "run", "--filesystem=home", "org.blender.Blender"]
    assert "--background" in cmd["args"]


def test_main_ui_exposes_integrated_particle_surface():
    package = Path(__file__).resolve().parents[1] / "pt_asset_tool"
    html = (package / "ui_static" / "index.html").read_text(encoding="utf-8")
    js = (package / "ui_static" / "app.js").read_text(encoding="utf-8")
    server = (package / "ui_app.py").read_text(encoding="utf-8")
    assert 'data-tab="particles"' in html
    assert 'id="tab-particles"' in html
    assert "/api/particles/inspect" in server
    assert "/api/particles/stage-edit" in server
    assert "loadParticleAssets" in js
