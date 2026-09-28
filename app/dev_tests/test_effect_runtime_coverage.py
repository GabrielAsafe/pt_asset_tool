from __future__ import annotations

from pathlib import Path

from pt_asset_tool.effect_runtime_coverage import audit_effect_runtime_coverage
from pt_asset_tool.source_catalog import SourceTree


def test_effect_runtime_coverage_resolves_animation_namespace_and_exact_paths(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; src = tmp_path / "src"
    project.mkdir(); client.mkdir(); src.mkdir()
    anim = client / "Effect" / "AnimationData"; anim.mkdir(parents=True)
    obj = client / "Effect" / "ObjAnimationData" / "BrutalSwing"; obj.mkdir(parents=True)
    image = client / "Effect" / "ImageData"; image.mkdir(parents=True)
    (anim / "Return1.ini").write_text("x")
    (image / "Return1.ini").write_text("duplicate but not billboard namespace")
    (obj / "BrutalSwing1.ini").write_text("x")
    code = src / "HoEffect.cpp"
    code.write_text(r'''
        billBoard->StartDestPath(world, local, dest, size, "Return1.ini", 600);
        GetPrivateProfileString("3DANIMATION", "DataName", NULL, buffer, sizeof(buffer), "Effect//ObjAnimationData//BrutalSwing//BrutalSwing1.ini");
    ''', encoding="utf-8")
    tree = SourceTree("CURRENT_SOURCE", "TARGET_RUNTIME_SOURCE", src)
    result = audit_effect_runtime_coverage(project, client, tree)
    roots = {x["path"].casefold(): x for x in result["roots"]}
    assert "effect/animationdata/return1.ini" in roots
    assert "effect/objanimationdata/brutalswing/brutalswing1.ini" in roots
    assert result["strong_root_count"] == 2
    assert result["policy"]["ambiguous_basename_is_review_not_root"] is True


def test_effect_runtime_coverage_ambiguous_non_animation_basename_stays_review(tmp_path):
    project = tmp_path / "project"; client = tmp_path / "client"; src = tmp_path / "src"
    project.mkdir(); client.mkdir(); src.mkdir()
    a = client / "Effect" / "ObjAnimationData" / "A"; b = client / "Effect" / "ImageData" / "B"
    a.mkdir(parents=True); b.mkdir(parents=True)
    (a / "Same.ini").write_text("x"); (b / "Same.ini").write_text("x")
    (src / "effect.cpp").write_text('x.StartBillRect(1,2,3,"Same.ini",0);', encoding="utf-8")
    tree = SourceTree("CURRENT_SOURCE", "TARGET_RUNTIME_SOURCE", src)
    result = audit_effect_runtime_coverage(project, client, tree)
    assert result["strong_root_count"] == 0
    assert result["review_witness_count"] == 1
    assert result["review"][0]["resolution_basis"] == "AMBIGUOUS_EFFECT_BASENAME"


def test_effect_runtime_coverage_accepts_multiline_loader_calls(tmp_path):
    project = tmp_path / "project"
    client = tmp_path / "client"
    source = tmp_path / "SourceCode"
    (client / "Effect/AnimationData").mkdir(parents=True)
    (client / "Effect/AnimationData/Return1.ini").write_text("x", encoding="utf-8")
    (client / "Effect/ObjAnimationData/Test").mkdir(parents=True)
    (client / "Effect/ObjAnimationData/Test/Foo.ASE").write_text("x", encoding="utf-8")
    source.mkdir(parents=True)
    (source / "HoEffect.cpp").write_text(
        'obj->StartDestPath(\n  x,\n  "Return1.ini",\n  y\n);\n'
        'model = smASE_Read(\n  "Effect/ObjAnimationData/Test/Foo.ASE",\n  0\n);\n',
        encoding="utf-8",
    )
    from pt_asset_tool.source_catalog import SourceTree
    tree = SourceTree("CURRENT_SOURCE", "TARGET_RUNTIME_SOURCE", source)
    result = audit_effect_runtime_coverage(project, client, tree)
    roots = {row["path"] for row in result["roots"]}
    assert "Effect/AnimationData/Return1.ini" in roots
    assert "Effect/ObjAnimationData/Test/Foo.ASE" in roots
