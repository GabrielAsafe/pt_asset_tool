from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.blender_workspace import blender_edit_root
from pt_asset_tool.registry import Asset
from pt_asset_tool.ui_actions import build_command
from pt_asset_tool.ui_capabilities import capabilities_for_asset
from pt_asset_tool.validation import ValidationRunner, ValidationContext


def asset(*, family="SMD_MODEL_062_STATIC", kind="SMD_MODEL_062", binding="NONE", skeleton=""):
    return Asset(
        asset_id="AST-TEST", primary_path="char/test/body.smd", basename="body.smd",
        extension=".smd", category="CHARACTER", family=family, kind=kind,
        compatibility_tier="TEST", size=123, issues=[], configs=[{"inx":"char/test/body.inx"}],
        motions=[], binding_mode=binding, binding_source="TEST", binding_skeleton_smb=skeleton,
        source_record={"object_count":1,"physique_objects":0 if family.endswith("STATIC") else 1},
    )


def test_static_and_resolved_rigid_expose_generic_import():
    a=asset()
    caps,_=capabilities_for_asset(a,None)
    assert "import_blender" in caps
    r=asset(family="SMD_MODEL_062_RIGID_PHYSIQUE",binding="ROOT_SKELETON_BOUND",skeleton="char/test/body.smb")
    caps,_=capabilities_for_asset(r,None)
    assert "import_blender" in caps


def test_unresolved_rigid_does_not_expose_generic_import():
    r=asset(family="SMD_MODEL_062_RIGID_PHYSIQUE",binding="CONFIG_ONLY",skeleton="")
    caps,_=capabilities_for_asset(r,None)
    assert "import_blender" not in caps


def test_ui_command_routes_to_generic_import(tmp_path):
    (tmp_path/'pt_asset.py').write_text('# x')
    cmd = build_command(tmp_path,'import_blender','char/test/body.smd',{})
    assert cmd[2:4] == ['import','char/test/body.smd']
    assert '--load-actions' in cmd
    assert '--motion' in cmd
    assert '--open-mode' in cmd
    assert build_command(tmp_path,'import_blender','char/test/body.smd',{'reset':True})[-1] == '--reset'


def test_existing_import_workspace_is_reused_without_touching_source(tmp_path):
    a=asset()
    workspace=blender_edit_root(tmp_path,'generic_import',a.primary_path)
    workspace.mkdir(parents=True)
    blend=workspace/'imported.blend'
    blend.write_bytes(b'artist-edit')
    settings=SimpleNamespace(project_root=tmp_path)
    ctx=ValidationContext(settings=settings,resolver=SimpleNamespace(),certifications=SimpleNamespace())
    runner=ValidationRunner(ctx)
    result=runner.blender_import_workspace(a,reset=False)
    assert result['status']=='READY'
    assert result['reused_existing'] is True
    assert blend.read_bytes()==b'artist-edit'
    assert result['client_modified'] is False
    assert Path(result['workspace_info']).is_file()


def _rigid_with_configs(configs):
    a=asset(family="SMD_MODEL_062_RIGID_PHYSIQUE",binding="ROOT_SKELETON_BOUND",skeleton="char/test/body.smb")
    a.configs=configs
    return a


def test_rigid_import_model_info_selection_is_fail_closed_when_configs_differ(tmp_path):
    settings=SimpleNamespace(project_root=tmp_path)
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=SimpleNamespace(),certifications=SimpleNamespace()))
    a=_rigid_with_configs([
        {"inx":"char/test/body-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["BodyA"]}},
        {"inx":"char/test/body-b.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["BodyB"]}},
    ])
    import pytest
    with pytest.raises(RuntimeError, match="AMBIGUOUS_MODEL_INFO_CONFIG"):
        runner._select_rigid_lod(a,"auto",require_unambiguous=True)
    lod,cfg=runner._select_rigid_lod(a,"auto",model_info="char/test/body-b.inx",require_unambiguous=True)
    assert lod=="default"
    assert cfg["inx"]=="char/test/body-b.inx"


def test_rigid_import_auto_allows_semantically_equivalent_model_info_configs(tmp_path):
    settings=SimpleNamespace(project_root=tmp_path)
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=SimpleNamespace(),certifications=SimpleNamespace()))
    a=_rigid_with_configs([
        {"inx":"char/test/body-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"]}},
        {"inx":"char/test/body-b.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"]}},
    ])
    lod,cfg=runner._select_rigid_lod(a,"auto",require_unambiguous=True)
    assert lod=="default"
    assert cfg["inx"]=="char/test/body-a.inx"


def test_ui_import_command_accepts_explicit_lod_and_model_info(tmp_path):
    (tmp_path/'pt_asset.py').write_text('# x')
    cmd=build_command(tmp_path,'import_blender','char/test/body.smd',{
        'lod':'high','model_info':'char/test/body-a.inx'
    })
    lod_i = cmd.index('--lod')
    model_info_i = cmd.index('--model-info')
    assert cmd[lod_i:lod_i+2] == ['--lod','high']
    assert cmd[model_info_i:model_info_i+2] == ['--model-info','char/test/body-a.inx']


def test_rigid_import_auto_rejects_configs_that_only_match_current_default_but_differ_elsewhere(tmp_path):
    settings=SimpleNamespace(project_root=tmp_path)
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=SimpleNamespace(),certifications=SimpleNamespace()))
    a=_rigid_with_configs([
        {"inx":"char/test/body-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["BodyHiA"]}},
        {"inx":"char/test/body-b.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["BodyHiB"]}},
    ])
    import pytest
    with pytest.raises(RuntimeError, match="AMBIGUOUS_MODEL_INFO_CONFIG"):
        runner._select_rigid_lod(a,"auto",require_unambiguous=True)


def test_rigid_model_info_context_audit_classifies_full_semantic_equivalence():
    from pt_asset_tool.validation import audit_rigid_model_info_contexts
    equivalent = _rigid_with_configs([
        {"inx":"char/test/e-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["Hi"]}},
        {"inx":"char/test/e-b.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["Hi"]}},
    ])
    equivalent.asset_id = "AST-EQ"; equivalent.primary_path = "char/test/e.smd"
    ambiguous = _rigid_with_configs([
        {"inx":"char/test/a-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["HiA"]}},
        {"inx":"char/test/a-b.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["HiB"]}},
    ])
    ambiguous.asset_id = "AST-AMB"; ambiguous.primary_path = "char/test/a.smd"

    class Registry:
        def list_assets(self, **kwargs): return [equivalent, ambiguous]

    result = audit_rigid_model_info_contexts(Registry(), sample_limit=0)
    assert result["status"] == "PASS"
    assert result["multi_config_assets"] == 2
    assert result["equivalent_multi_config_assets"] == 1
    assert result["ambiguous_multi_config_assets"] == 1
    by_id = {row["asset_id"]: row for row in result["rows"]}
    assert by_id["AST-EQ"]["state"] == "SEMANTICALLY_EQUIVALENT"
    assert by_id["AST-AMB"]["state"] == "AMBIGUOUS_MODEL_INFO_CONFIG"
    assert by_id["AST-AMB"]["requires_explicit_model_info"] is True


def test_rigid_import_persists_selected_context_in_manifest(monkeypatch, tmp_path):
    import json
    import pt_asset_tool.validation as validation_mod
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body-a.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    a=_rigid_with_configs([
        {"inx":"char/test/body-a.inx","motion_smb":"char/test/body.smb","lod_groups":{"default":["Body"],"high":["BodyHi"]}},
    ])

    class Resolver:
        def resolve(self, logical, required=True):
            logical=str(logical).replace("\\", "/")
            return {
                "char/test/body.smd": source,
                "char/test/body-a.inx": inx,
                "char/test/body.smb": smb,
            }[logical]

    settings=SimpleNamespace(project_root=tmp_path)
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=Resolver(),certifications=SimpleNamespace()))
    monkeypatch.setattr(runner, "structural", lambda asset: {"status":"PASS"})
    overlay=tmp_path / "overlay"; overlay.mkdir()
    monkeypatch.setattr(runner, "_texture_overlay", lambda asset, work: (overlay, {"ready":True}))
    def fake_prepare(asset, lod, work, client_root, **kwargs):
        prepared=work / "pristine_import.blend"; prepared.write_bytes(b"blend")
        return source, prepared, "default", a.configs[0]
    monkeypatch.setattr(runner, "_prepare_rigid_blend", fake_prepare)
    monkeypatch.setattr(validation_mod, "authoring_plan", lambda asset, source_path: {"generic_build_authorized":False})

    result=runner.blender_import_workspace(a, lod="auto")
    assert result["status"] == "READY"
    ctx=result["selected_context"]
    assert ctx["model_info_inx"]["logical"] == "char/test/body-a.inx"
    assert ctx["skeleton_smb"]["logical"] == "char/test/body.smb"
    assert ctx["lod"] == "default"
    manifest=json.loads(Path(result["authoring_manifest"]).read_text())
    assert manifest["selected_context"] == ctx
    assert result["workspace_provenance"]["status"] == "PASS"


def test_existing_rigid_workspace_reuse_rejects_requested_context_mismatch(tmp_path):
    import pytest
    from pt_asset_tool.authoring import build_selected_authoring_context, write_workspace_manifest

    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body-a.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    a=_rigid_with_configs([{
        "inx":"char/test/body-a.inx", "motion_smb":"char/test/body.smb",
        "lod_groups":{"high":["BodyHi"], "default":["Body"]},
    }])
    workspace=blender_edit_root(tmp_path,'generic_import',a.primary_path)
    workspace.mkdir(parents=True)
    (workspace/'imported.blend').write_bytes(b'artist-edit')
    context=build_selected_authoring_context(
        model_info_logical="char/test/body-a.inx", model_info_path=inx,
        skeleton_logical="char/test/body.smb", skeleton_path=smb,
        lod="default", lod_groups=a.configs[0]["lod_groups"],
    )
    write_workspace_manifest(workspace, a, source, {"generic_build_authorized":False}, [inx,smb], selected_context=context)
    settings=SimpleNamespace(project_root=tmp_path)
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=SimpleNamespace(),certifications=SimpleNamespace()))

    ok=runner.blender_import_workspace(a, model_info="char/test/body-a.inx")
    assert ok["reused_existing"] is True
    with pytest.raises(RuntimeError, match="EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH"):
        runner.blender_import_workspace(a, model_info="char/test/body-b.inx")
    with pytest.raises(RuntimeError, match="EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH"):
        runner.blender_import_workspace(a, lod="high", model_info="char/test/body-a.inx")


def test_rigid_selected_context_persists_profile_selection_basis(monkeypatch, tmp_path):
    import pt_asset_tool.validation as validation_mod
    source = tmp_path / "client" / "body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    inx = tmp_path / "client" / "body-a.inx"; inx.write_bytes(b"inx")
    smb = tmp_path / "client" / "body.smb"; smb.write_bytes(b"smb")
    a=_rigid_with_configs([{
        "inx":"char/test/body-a.inx", "motion_smb":"char/test/body.smb",
        "lod_groups":{"default":["Body"]},
    }])
    class Resolver:
        def resolve(self, logical, required=True):
            return {
                "char/test/body.smd":source,
                "char/test/body-a.inx":inx,
                "char/test/body.smb":smb,
            }[str(logical).replace("\\", "/")]
    runner=ValidationRunner(ValidationContext(settings=SimpleNamespace(project_root=tmp_path),resolver=Resolver(),certifications=SimpleNamespace()))
    monkeypatch.setattr(runner, "structural", lambda asset: {"status":"PASS"})
    overlay=tmp_path / "overlay"; overlay.mkdir()
    monkeypatch.setattr(runner, "_texture_overlay", lambda asset, work: (overlay, {"ready":True}))
    def fake_prepare(asset, lod, work, client_root, **kwargs):
        prepared=work / "pristine_import.blend"; prepared.write_bytes(b"blend")
        return source, prepared, "default", a.configs[0]
    monkeypatch.setattr(runner, "_prepare_rigid_blend", fake_prepare)
    monkeypatch.setattr(validation_mod, "authoring_plan", lambda asset, source_path: {"generic_build_authorized":False})
    basis={"kind":"CANONICAL_PROFILE","profile_id":"hero","profile_version":1,"roundtrip_target":"char/test/body.smd"}
    result=runner.blender_import_workspace(a, model_info="char/test/body-a.inx", selection_basis=basis)
    assert result["selected_context"]["selection_basis"] == basis
    assert result["workspace_provenance"]["status"] == "PASS"


def test_rigid_lod_node_coverage_counts_duplicate_smd_chunks_and_missing_names():
    from pt_asset_tool.rigid_model_info import lod_node_coverage
    a = _rigid_with_configs([{
        "inx":"char/test/body-a.inx", "motion_smb":"char/test/body.smb",
        "lod_groups":{"high":["Body"], "default":["Body", "Accessory"]},
    }])
    a.source_record = {
        "object_count": 3, "physique_objects": 3,
        "object_names": ["Body", "Body", "Other"],
    }
    report = lod_node_coverage(a, a.configs[0], "default")
    assert report["status"] == "FAIL"
    assert report["missing_nodes"] == ["Accessory"]
    assert report["matched_chunk_count"] == 2


def test_rigid_reset_preflight_missing_nodes_preserves_existing_artist_workspace(tmp_path):
    import pytest
    a = _rigid_with_configs([{
        "inx":"char/test/body-a.inx", "motion_smb":"char/test/body.smb",
        "lod_groups":{"high":["Body"], "default":["Body", "Accessory"]},
    }])
    a.source_record = {
        "object_count": 2, "physique_objects": 2,
        "object_names": ["Body", "Body"],
    }
    workspace = blender_edit_root(tmp_path, "generic_import", a.primary_path)
    workspace.mkdir(parents=True)
    blend = workspace / "imported.blend"
    blend.write_bytes(b"artist-edit-must-survive")
    runner = ValidationRunner(ValidationContext(
        settings=SimpleNamespace(project_root=tmp_path),
        resolver=SimpleNamespace(), certifications=SimpleNamespace(),
    ))
    with pytest.raises(RuntimeError, match="MODEL_INFO_LOD_REFERENCES_MISSING_SMD_NODES"):
        runner.blender_import_workspace(
            a, lod="default", model_info="char/test/body-a.inx", reset=True,
        )
    assert blend.read_bytes() == b"artist-edit-must-survive"


def test_single_tier_legacy_labels_preflight_as_full_container_without_alias(tmp_path):
    a = _rigid_with_configs([{
        "inx":"char/test/legacy.inx", "motion_smb":"char/test/body.smb",
        "lod_groups":{"default":["legacy_label"]},
    }])
    a.source_record = {"object_count": 2, "physique_objects": 2, "object_names": ["Body", "Weapon"]}
    runner = ValidationRunner(ValidationContext(
        settings=SimpleNamespace(project_root=tmp_path), resolver=SimpleNamespace(), certifications=SimpleNamespace(),
    ))
    lod, cfg, coverage = runner._preflight_rigid_import(a, "default", model_info="char/test/legacy.inx")
    assert lod == "default"
    assert coverage["status"] == "PASS"
    assert coverage["selection_mode"] == "SINGLE_TIER_FULL_CONTAINER"
    assert coverage["effective_selected_nodes"] == ["Body", "Weapon"]
    assert coverage["legacy_unmapped_model_labels"] == ["legacy_label"]


def test_canonical_bcn02f_context_is_preflight_blocked_before_blender():
    from pt_asset_tool.registry import AssetRegistry
    from pt_asset_tool.rigid_model_info import lod_node_coverage
    root = Path(__file__).resolve().parents[1]
    reg = AssetRegistry(
        root / "data/asset_registry/asset_inventory.json",
        root / "data/asset_registry/inx_physical_pairing.csv",
    )
    a = reg.resolve("char/npc/Bcn02/Bcn02.smd")
    cfg = next(c for c in a.configs if str(c.get("inx") or "").casefold().endswith("bcn02f.inx"))
    default = lod_node_coverage(a, cfg, "default")
    high = lod_node_coverage(a, cfg, "high")
    assert default["status"] == "FAIL" and default["missing_nodes"] == ["hart"]
    assert high["status"] == "FAIL" and high["missing_nodes"] == ["hart", "T-npc-12-H02"]


def test_standalone_rigid_import_persists_explicit_skeleton_context(monkeypatch, tmp_path):
    import pt_asset_tool.validation as validation_mod
    source = tmp_path / "client" / "piece.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    smb = tmp_path / "client" / "class.smb"; smb.write_bytes(b"smb")
    structural = tmp_path / "structural.json"; structural.write_text('{"status":"PASS"}')
    a = asset(family="SMD_MODEL_062_RIGID_PHYSIQUE", binding="UNRESOLVED", skeleton="")
    a.configs = []

    class Resolver:
        def resolve(self, logical, required=True):
            return {"char/test/body.smd":source, "char/test/class.smb":smb}[str(logical).replace("\\", "/")]

    runner=ValidationRunner(ValidationContext(settings=SimpleNamespace(project_root=tmp_path),resolver=Resolver(),certifications=SimpleNamespace()))
    preflight={"source":source,"skeleton":smb,"skeleton_logical":"char/test/class.smb","structural_report":structural,"structural":{"status":"PASS"},"selected_nodes":["Piece"]}
    monkeypatch.setattr(runner,"_preflight_standalone_rigid_import",lambda asset,skeleton:preflight)
    overlay=tmp_path / "overlay"; overlay.mkdir()
    monkeypatch.setattr(runner,"_texture_overlay",lambda asset,work:(overlay,{"ready":True}))
    def fake_prepare(asset,work,client_root,preflight):
        prepared=work / "pristine_import.blend"; prepared.write_bytes(b"blend")
        return source, prepared
    monkeypatch.setattr(runner,"_prepare_standalone_rigid_blend",fake_prepare)
    monkeypatch.setattr(validation_mod,"authoring_plan",lambda asset,source_path:{"generic_build_authorized":False})

    result=runner.blender_import_workspace(a,skeleton="char/test/class.smb")
    assert result["status"]=="READY"
    assert result["mode"]=="RIGID_STANDALONE"
    assert result["lod"]=="standalone"
    assert result["selected_context"]["format"]=="PT_ASSET_STANDALONE_RIGID_CONTEXT_V1"
    assert result["selected_context"]["skeleton_smb"]["logical"]=="char/test/class.smb"
    assert result["workspace_provenance"]["status"]=="PASS"


def test_existing_standalone_rigid_workspace_rejects_skeleton_change(tmp_path):
    import pytest
    from pt_asset_tool.authoring import build_standalone_rigid_authoring_context, write_workspace_manifest
    source=tmp_path/"client"/"body.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    smb=tmp_path/"client"/"a.smb"; smb.write_bytes(b"smb")
    a=asset(family="SMD_MODEL_062_RIGID_PHYSIQUE",binding="UNRESOLVED",skeleton=""); a.configs=[]
    workspace=blender_edit_root(tmp_path,'generic_import',a.primary_path); workspace.mkdir(parents=True)
    (workspace/'imported.blend').write_bytes(b'artist-edit')
    ctx=build_standalone_rigid_authoring_context(
        asset_logical=a.primary_path,source_path=source,skeleton_logical="char/test/a.smb",skeleton_path=smb,
        selected_nodes=["Piece"],selection_basis={"kind":"EXPLICIT_SKELETON","roundtrip_target":a.primary_path,"structural_gate":"PASS"},
    )
    write_workspace_manifest(workspace,a,source,{"generic_build_authorized":False},[smb],selected_context=ctx)
    runner=ValidationRunner(ValidationContext(settings=SimpleNamespace(project_root=tmp_path),resolver=SimpleNamespace(),certifications=SimpleNamespace()))
    ok=runner.blender_import_workspace(a,skeleton="char/test/a.smb")
    assert ok["reused_existing"] is True
    with pytest.raises(RuntimeError,match="EXISTING_RIGID_WORKSPACE_CONTEXT_MISMATCH"):
        runner.blender_import_workspace(a,skeleton="char/test/b.smb")


def test_mixed_import_uses_explicit_structurally_proven_skeleton_context(monkeypatch, tmp_path):
    import pt_asset_tool.validation as validation_mod
    source = tmp_path / "client" / "mixed.smd"; source.parent.mkdir(); source.write_bytes(b"smd")
    smb = tmp_path / "client" / "class.smb"; smb.write_bytes(b"smb")
    structural = tmp_path / "structural.json"; structural.write_text('{"status":"PASS"}')
    a = asset(family="SMD_MODEL_062_MIXED_PHYSIQUE", binding="UNRESOLVED", skeleton="")
    a.primary_path = "char/test/mixed.smd"
    a.configs = []
    a.source_record = {"object_count":2,"physique_objects":1,"object_names":["RigidPart","StaticPart"]}

    class Resolver:
        def resolve(self, logical, required=True):
            return {"char/test/mixed.smd":source, "char/test/class.smb":smb}[str(logical).replace("\\", "/")]

    runner = ValidationRunner(ValidationContext(settings=SimpleNamespace(project_root=tmp_path),resolver=Resolver(),certifications=SimpleNamespace()))
    preflight={"source":source,"skeleton":smb,"skeleton_logical":"char/test/class.smb","structural_report":structural,"structural":{"status":"PASS"},"selected_nodes":["RigidPart","StaticPart"]}
    monkeypatch.setattr(runner,"_preflight_standalone_rigid_import",lambda asset,skeleton:preflight)
    overlay=tmp_path / "overlay"; overlay.mkdir()
    monkeypatch.setattr(runner,"_texture_overlay",lambda asset,work:(overlay,{"ready":True}))
    def fake_prepare(asset,work,client_root,preflight):
        prepared=work / "pristine_import.blend"; prepared.write_bytes(b"blend")
        return source, prepared
    monkeypatch.setattr(runner,"_prepare_standalone_rigid_blend",fake_prepare)
    monkeypatch.setattr(validation_mod,"authoring_plan",lambda asset,source_path:{"generic_build_authorized":False})

    result=runner.blender_import_workspace(a,skeleton="char/test/class.smb")
    assert result["status"] == "READY"
    assert result["mode"] == "MIXED"
    assert result["selected_context"]["format"] == "PT_ASSET_STANDALONE_RIGID_CONTEXT_V1"
    assert result["selected_context"]["skeleton_smb"]["logical"] == "char/test/class.smb"
    assert result["workspace_provenance"]["status"] == "PASS"


def test_rigid_model_info_options_include_lod_config_without_motion_smb():
    from pt_asset_tool.validation import rigid_model_info_options
    a=_rigid_with_configs([{
        "inx":"char/test/equip.inx", "motion_smb":"",
        "lod_groups":{"high":["PieceHi"],"default":["Piece"]},
    }])
    a.source_record={"object_names":["PieceHi","Piece"],"object_count":2,"physique_objects":2}
    rows=rigid_model_info_options(a)
    assert len(rows)==1
    assert rows[0]["inx"]=="char/test/equip.inx"
    assert rows[0]["skeleton_resolved"] is False
    assert rows[0]["lod_node_coverage"]["default"]["status"]=="PASS"


def test_explicit_skeleton_plus_model_info_preflight_allows_lod_without_motion_smb(monkeypatch, tmp_path):
    import json
    import pt_asset_tool.validation as validation_mod
    source=tmp_path/'client'/'body.smd'; source.parent.mkdir(); source.write_bytes(b'smd')
    inx=tmp_path/'client'/'equip.inx'; inx.write_bytes(b'inx')
    smb=tmp_path/'client'/'class.smb'; smb.write_bytes(b'smb')
    a=_rigid_with_configs([{
        "inx":"char/test/equip.inx", "motion_smb":"",
        "lod_groups":{"default":["Piece"]},
    }])
    a.binding_skeleton_smb=""
    a.source_record={"object_names":["Piece"],"object_count":1,"physique_objects":1}
    class Resolver:
        def resolve(self, logical, required=True):
            return {
                'char/test/body.smd':source,
                'char/test/equip.inx':inx,
                'char/test/class.smb':smb,
            }[str(logical).replace('\\','/')]
    settings=SimpleNamespace(project_root=tmp_path, work_dir=tmp_path/"work")
    runner=ValidationRunner(ValidationContext(settings=settings,resolver=Resolver(),certifications=SimpleNamespace()))
    def fake_run(cmd, log):
        report=Path(cmd[cmd.index('--report')+1]); report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps({'status':'PASS'}))
    monkeypatch.setattr(validation_mod,'run_logged',fake_run)
    pre=runner._preflight_explicit_skeleton_lod_import(
        a,'default',model_info='char/test/equip.inx',skeleton_logical='char/test/class.smb',require_unambiguous=True,
    )
    assert pre['lod']=='default'
    assert pre['cfg']['inx']=='char/test/equip.inx'
    assert pre['skeleton_logical']=='char/test/class.smb'
    assert pre['lod_node_coverage']['status']=='PASS'


def test_explicit_skeleton_plus_model_info_rejects_conflicting_cfg_skeleton(monkeypatch, tmp_path):
    import pytest
    a=_rigid_with_configs([{
        "inx":"char/test/equip.inx", "motion_smb":"char/test/a.smb",
        "lod_groups":{"default":["Piece"]},
    }])
    a.source_record={"object_names":["Piece"],"object_count":1,"physique_objects":1}
    runner=ValidationRunner(ValidationContext(settings=SimpleNamespace(project_root=tmp_path),resolver=SimpleNamespace(),certifications=SimpleNamespace()))
    with pytest.raises(RuntimeError,match='conflicts with the selected model-info motion_smb'):
        runner._preflight_explicit_skeleton_lod_import(
            a,'default',model_info='char/test/equip.inx',skeleton_logical='char/test/b.smb',require_unambiguous=True,
        )
