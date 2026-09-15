from pathlib import Path
from types import SimpleNamespace

from pt_asset_tool.animation_pose_devtest import choose_animation_pose_representatives
from pt_asset_tool.config import Settings
from pt_asset_tool.registry import AssetRegistry
import pt_asset_tool.static_semantic_devtest as static_mod
import pt_asset_tool.standalone_rigid_devtest as standalone_mod
import pt_asset_tool.physical_regression_auto as physical_mod


def test_animation_selector_uses_motion_owning_inx_for_mfbc01():
    settings=Settings.discover(None,None)
    registry=AssetRegistry(settings.inventory,settings.pairing)
    rows=choose_animation_pose_representatives(registry,"PLAYER",limit=100)
    hit=next(r for r in rows if r["asset"].casefold()=="char/tmabcd/mfbc01.smd".casefold())
    assert hit["model_info_inx"].casefold()=="char/tmabcd/m5bip.inx".casefold()
    assert hit["skeleton_smb"].casefold()=="char/tmabcd/m5.smb".casefold()


class _Registry:
    def __init__(self, assets):
        self.assets=assets
        self._by={a.primary_path:a for a in assets}
    def resolve(self, value):
        return self._by[value]


class _Resolver:
    def __init__(self, root: Path): self.root=root
    def resolve(self, logical, required=True):
        p=self.root/logical
        p.parent.mkdir(parents=True,exist_ok=True)
        p.touch(exist_ok=True)
        return p


def _asset(path, family="SMD_MODEL_062_STATIC"):
    return SimpleNamespace(
        asset_id="A-"+path.replace("/","_"), primary_path=path, family=family,
        object_count=1, material_count=1, total_vertices=3, total_faces=1, size=100,
    )


def test_static_selector_backfills_uneditable_source(tmp_path, monkeypatch):
    a=_asset("a.smd"); b=_asset("b.smd")
    reg=_Registry([a,b]); resolver=_Resolver(tmp_path)
    def fake_plan(asset, source):
        eligible=[] if asset.primary_path=="a.smd" else ["Object01"]
        return {"channels":{"geometry":{"eligible_objects":eligible}}}
    monkeypatch.setattr(static_mod,"authoring_plan",fake_plan)
    rows=static_mod.choose_static_semantic_representatives(reg,resolver,"MAP",limit=1)
    # Fake content-domain routing is bypassed by patching the imported function.
    assert rows==[]


def test_static_selector_backfill_with_domain_patch(tmp_path, monkeypatch):
    a=_asset("a.smd"); b=_asset("b.smd")
    reg=_Registry([a,b]); resolver=_Resolver(tmp_path)
    monkeypatch.setattr("pt_asset_tool.release_1_coverage.content_domain",lambda asset:"MAP")
    def fake_plan(asset, source):
        return {"channels":{"geometry":{"eligible_objects":[] if asset.primary_path=="a.smd" else ["Object01"]}}}
    monkeypatch.setattr(static_mod,"authoring_plan",fake_plan)
    rows=static_mod.choose_static_semantic_representatives(reg,resolver,"MAP",limit=1)
    assert [r["asset"] for r in rows]==["b.smd"]
    assert rows[0]["physical_authoring_preflight"]=="PASS"


def test_standalone_selector_backfills_non_authorable(tmp_path, monkeypatch):
    a=_asset("a.smd","SMD_MODEL_062_RIGID_PHYSIQUE"); b=_asset("b.smd","SMD_MODEL_062_RIGID_PHYSIQUE")
    reg=_Registry([a,b]); resolver=_Resolver(tmp_path)
    monkeypatch.setattr(standalone_mod,"choose_standalone_rigid_representatives",lambda registry,domain,limit:[
        {"asset":"a.smd","asset_id":"A-a","domain":domain,"skeleton_smb":"a.smb"},
        {"asset":"b.smd","asset_id":"A-b","domain":domain,"skeleton_smb":"b.smb"},
    ])
    monkeypatch.setattr(standalone_mod,"choose_authorable_lod_config_for_explicit_skeleton",lambda asset:None)
    monkeypatch.setattr(standalone_mod,"authoring_plan",lambda asset,source:{
        "channels":{"geometry":{"eligible_objects":[] if asset.primary_path=="a.smd" else ["Body"]}},
        "source_analysis":{"rigid_saved_blender_candidate_objects":[]},
    })
    rows=standalone_mod.choose_standalone_rigid_authorable_representatives(reg,resolver,"MONSTER",limit=1)
    assert [r["asset"] for r in rows]==["b.smd"]
    assert rows[0]["eligible_objects"]==["Body"]


def test_physical_regression_stops_on_environment_failure(tmp_path, monkeypatch):
    settings=SimpleNamespace(project_root=tmp_path,client_root=tmp_path/"client")
    monkeypatch.setattr(physical_mod,"run_environment_validation",lambda *a,**k:{"status":"FAIL","client_modified":False})
    result=physical_mod.run_physical_regression_auto(settings,object(),object(),object())
    assert result["status"]=="FAIL"
    assert result["required_failures"]==["environment"]
    assert result["gates"]["environment"]["status"]=="FAIL"
    assert Path(result["report"]).is_file()
