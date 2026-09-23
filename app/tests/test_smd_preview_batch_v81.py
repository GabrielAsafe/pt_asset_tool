from __future__ import annotations

import json
import pathlib
import threading
from types import SimpleNamespace

import pytest

from pt_asset_tool import smd_preview, smd_preview_batch


class FakeResolver:
    def __init__(self, root: pathlib.Path):
        self.root = root
    def resolve(self, logical, required=False):
        if not logical:
            return None
        return self.root / pathlib.PurePosixPath(str(logical))


class FakeRegistry:
    def __init__(self, asset):
        self.asset = asset
    def resolve(self, rel):
        return self.asset


def _rigid_asset(configs):
    return SimpleNamespace(
        family="SMD_MODEL_062_RIGID_PHYSIQUE",
        primary_path="char/tmABCD/CtmbC010.smd",
        rigid_binding_ready=True,
        binding_skeleton_smb="char/tmABCD/m4.smb",
        configs=configs,
        textures=["char/tmABCD/Ava_M_03.tga"],
        visual_mode="RIGID",
    )


def test_preview_uses_paint_context_and_skips_bad_first_inx(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    bad = {"inx":"char/tmABCD/BAD.inx", "motion_smb":"char/tmABCD/m4.smb", "lod_groups":{"default":["missing"]}}
    good = {"inx":"char/tmABCD/Cc010.inx", "motion_smb":"char/tmABCD/m4.smb", "lod_groups":{"default":["body"]}}
    asset = _rigid_asset([bad, good])
    monkeypatch.setattr(smd_preview, "effective_lod_node_coverage", lambda a, cfg, lod: {
        "status": "PASS" if cfg["inx"].endswith("Cc010.inx") else "FAIL",
        "selection_mode": "MODEL_GROUP_KEYS",
    })
    plan = smd_preview.build_smd_preview_plan(FakeRegistry(asset), FakeResolver(tmp_path), asset.primary_path)
    assert plan is not None
    assert plan["preview_environment"] == "PAINT_EDIT"
    assert plan["load_actions"] == "none"
    assert plan["strategy"] == "PAINT_RIGID_LOD"
    assert plan["model_info_logical"] == "char/tmABCD/Cc010.inx"
    assert plan["skeleton_logical"] == "char/tmABCD/m4.smb"


def test_preview_falls_back_to_proven_skeleton_when_no_inx_lod_covers_model(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    cfg = {"inx":"char/tmABCD/Cc010.inx", "motion_smb":"char/tmABCD/m4.smb", "lod_groups":{"default":["wrong"]}}
    asset = _rigid_asset([cfg])
    monkeypatch.setattr(smd_preview, "effective_lod_node_coverage", lambda *a, **k: {"status":"FAIL", "missing_nodes":["wrong"]})
    plan = smd_preview.build_smd_preview_plan(FakeRegistry(asset), FakeResolver(tmp_path), asset.primary_path)
    assert plan is not None
    assert plan["strategy"] == "PAINT_RIGID_SKELETON_ONLY"
    assert plan["model_info_logical"] == ""
    assert plan["skeleton_logical"] == "char/tmABCD/m4.smb"


def test_static_thumbnail_uses_paint_static_without_animation(tmp_path: pathlib.Path):
    asset = SimpleNamespace(
        family="SMD_MODEL_062_STATIC", primary_path="char/monster/x/x.smd",
        configs=[], textures=["char/monster/x/x.tga"], visual_mode="STATIC",
    )
    plan = smd_preview.build_smd_preview_plan(FakeRegistry(asset), FakeResolver(tmp_path), asset.primary_path)
    assert plan is not None
    assert plan["strategy"] == "PAINT_STATIC"
    assert plan["preview_environment"] == "PAINT_EDIT"
    assert plan["load_actions"] == "none"
    assert not plan["model_info"]
    assert not plan["skeleton"]


def test_batch_cancel_is_persisted_and_does_not_render_backlog(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "app"; project.mkdir()
    client = tmp_path / "client"; client.mkdir()
    inv = project / "pt_build/state/asset_registry/asset_inventory.json"
    pair = project / "pt_build/state/asset_registry/inx_physical_pairing.csv"
    inv.parent.mkdir(parents=True)
    inv.write_text("{}", encoding="utf-8"); pair.write_text("x\n", encoding="utf-8")
    settings = SimpleNamespace(client_root=client, inventory=inv, pairing=pair)
    monkeypatch.setattr(smd_preview_batch.Settings, "discover", classmethod(lambda cls, *a, **k: settings))
    monkeypatch.setattr(smd_preview_batch, "blender_runtime_info", lambda *a, **k: {"ready":True,"source":"TEST","version":"3.6.23","command":["blender"]})

    class R:
        def __init__(self, root): pass
        def prime_from_inventory(self, path): return {}
    monkeypatch.setattr(smd_preview_batch, "ClientResolver", R)
    assets = [SimpleNamespace(primary_path=f"char/{i}.smd", family="SMD_MODEL_062_STATIC") for i in range(50)]
    class Registry:
        def __init__(self, *a, **k): self.assets = assets
    monkeypatch.setattr(smd_preview_batch, "AssetRegistry", Registry)
    monkeypatch.setattr(smd_preview_batch, "build_smd_preview_plan", lambda reg, res, rel: {"logical":rel,"dependency_paths":[],"smd":str(client/rel),"strategy":"PAINT_STATIC"})

    calls = []
    class Manager:
        def __init__(self,*a,**k): pass
        def classify(self, plan): return {"status":"MISSING","asset":plan["logical"]}
        def render_now(self, plan, **kwargs): calls.append(plan["logical"]); return {"status":"READY","asset":plan["logical"]}
    monkeypatch.setattr(smd_preview_batch, "SmdPreviewManager", Manager)
    stop = threading.Event(); stop.set()
    out = smd_preview_batch.run_batch(project, client, workers=4, cancel_event=stop)
    assert out["status"] == "CANCELED"
    assert len(calls) == 0
    persisted = json.loads(smd_preview_batch.batch_state_path(project).read_text(encoding="utf-8"))
    assert persisted["status"] == "CANCELED"


def test_v81_renderer_contains_paint_fallback_and_cooperative_cancel():
    root = pathlib.Path(__file__).resolve().parents[1]
    preview = (root / "pt_asset_tool/smd_preview.py").read_text(encoding="utf-8")
    batch = (root / "pt_asset_tool/smd_preview_batch.py").read_text(encoding="utf-8")
    assert "PAINT_RIGID_SKELETON_ONLY_FALLBACK" in preview
    assert "pt_smd_blender_import_v3_static_armature.py" in preview
    assert "SMD_PREVIEW_CANCELED" in preview
    assert "cancel_futures=True" in batch
    assert "SMD_PREVIEW_BATCH=CANCELED" in batch
