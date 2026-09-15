from __future__ import annotations

from types import MethodType, SimpleNamespace

from pt_asset_tool.registry import AssetRegistry


def _registry_with_multicontext_links():
    reg = AssetRegistry.__new__(AssetRegistry)
    reg.resolver = object()
    reg._inx_link_cache = {}
    reg.binding_cache = {"format": "PT_ROOT_SKELETON_BINDINGS_V7", "entries": {}}
    reg.pairing = [
        {"inx": "char/tmABCD/Ca001.inx", "model_smd": "char/tmABCD/ar0nDrac.smd", "model_resolved": "True", "motion_smb": ""},
        {"inx": "char/tmABCD/Cb001.inx", "model_smd": "char/tmABCD/ar0nDrac.smd", "model_resolved": "True", "motion_smb": ""},
        {"inx": "char/tmABCD/Cc001.inx", "model_smd": "char/tmABCD/ar0nDrac.smd", "model_resolved": "True", "motion_smb": ""},
        {"inx": "char/tmABCD/Cma001.inx", "model_smd": "char/tmABCD/ar0nDrac.smd", "model_resolved": "True", "motion_smb": ""},
        {"inx": "char/tmABCD/Cmd001.inx", "model_smd": "char/tmABCD/ar0nDrac.smd", "model_resolved": "True", "motion_smb": ""},
    ]
    reg.records = [
        {
            "relative_path": "char/tmABCD/ar0nDrac.smd", "extension": ".smd",
            "basename": "ar0nDrac.smd", "category_hint": "CHARACTER",
            "compatibility_family": "SMD_MODEL_062_RIGID_PHYSIQUE", "kind": "SMD_MODEL_062",
            "compatibility_tier": "", "size": 100, "issues": [], "texture_refs": [],
            "object_count": 1, "physique_objects": 1,
        },
        {"relative_path": "char/tmABCD/m1.smb", "extension": ".smb", "category_hint": "CHARACTER"},
        {"relative_path": "char/tmABCD/m3.smb", "extension": ".smb", "category_hint": "CHARACTER"},
        {"relative_path": "char/tmABCD/m4.smb", "extension": ".smb", "category_hint": "CHARACTER"},
    ]
    reg.by_rel = {str(r["relative_path"]).replace("\\", "/").casefold(): r for r in reg.records}

    mapping = {
        "ca001.inx": ("M1Bip.inx", "m1.smb", 1343570237),
        "cb001.inx": ("M1Bip.inx", "m1.smb", 1343570237),
        "cc001.inx": ("M4Bip.inx", "m4.smb", 1259684199),
        "cma001.inx": ("M1Bip.inx", "m1.smb", 1343570237),
        "cmd001.inx": ("M3Bip.inx", "m3.smb", 2719301977),
    }

    def fake_verified(self, row, by_inx_rows):
        src = self._row_inx(row)
        name = src.rsplit("/", 1)[-1].casefold()
        target, smb, code = mapping[name]
        return {
            "status": "VERIFIED", "source_inx": src,
            "target_inx": f"char/tmABCD/{target}", "raw_link_file": target,
            "link_code": code, "target_file_code": code,
            "motion_smb": f"char/tmABCD/{smb}", "root_models": [],
        }

    reg._verified_link_root_candidate = MethodType(fake_verified, reg)
    reg._pt_structural_twin_texture_alias_index_v1 = {}
    reg.assets = reg._build_assets()
    reg.by_id = {a.asset_id: a for a in reg.assets}
    reg.by_primary = {a.primary_path.replace("\\", "/").casefold(): a for a in reg.assets}
    return reg


def test_registry_preserves_verified_multi_context_link_bindings_without_global_skeleton():
    reg = _registry_with_multicontext_links()
    asset = next(a for a in reg.assets if a.primary_path.casefold() == "char/tmabcd/ar0ndrac.smd")
    assert asset.binding_mode == "MULTI_CONTEXT_BOUND"
    assert asset.binding_source == "INX_LINK_FILE_MULTI_CONTEXT"
    assert asset.binding_skeleton_smb == ""
    assert asset.rigid_context_ready is True
    assert asset.rigid_binding_ready is False
    assert asset.animation_binding_ready is False
    assert {m.casefold() for m in asset.motions} == {
        "char/tmabcd/m1.smb", "char/tmabcd/m3.smb", "char/tmabcd/m4.smb"
    }
    by_inx = {c["inx"].casefold(): c for c in asset.configs}
    assert by_inx["char/tmabcd/ca001.inx"]["motion_smb"].casefold() == "char/tmabcd/m1.smb"
    assert by_inx["char/tmabcd/cc001.inx"]["motion_smb"].casefold() == "char/tmabcd/m4.smb"
    assert by_inx["char/tmabcd/cmd001.inx"]["motion_smb"].casefold() == "char/tmabcd/m3.smb"
    assert by_inx["char/tmabcd/ca001.inx"]["motion_inx"].casefold() == "char/tmabcd/m1bip.inx"
    assert by_inx["char/tmabcd/cmd001.inx"]["motion_inx"].casefold() == "char/tmabcd/m3bip.inx"
    assert all(c["motion_binding_origin"] == "INX_LINK_FILE_MULTI_CONTEXT" for c in asset.configs)


def test_registry_multicontext_requires_every_source_row_verified():
    reg = _registry_with_multicontext_links()
    original = reg._verified_link_root_candidate

    def one_bad(self, row, by_inx_rows):
        if self._row_inx(row).casefold().endswith("cmd001.inx"):
            return {"status": "TARGET_FILE_CODE_MISMATCH", "source_inx": self._row_inx(row)}
        return original(row, by_inx_rows)

    reg._verified_link_root_candidate = MethodType(one_bad, reg)
    reg.assets = reg._build_assets()
    asset = next(a for a in reg.assets if a.primary_path.casefold() == "char/tmabcd/ar0ndrac.smd")
    assert asset.binding_mode == "CONFIG_ONLY"
    assert asset.binding_source == "INX_LINK_FILE_AMBIGUOUS"
    assert asset.rigid_context_ready is False


def test_multicontext_asset_does_not_promote_generic_rigid_authoring_or_animation():
    from pt_asset_tool.authoring import authoring_plan
    reg = _registry_with_multicontext_links()
    asset = next(a for a in reg.assets if a.primary_path.casefold() == "char/tmabcd/ar0ndrac.smd")
    plan = authoring_plan(asset, None)
    assert asset.rigid_context_ready is True
    assert asset.rigid_binding_ready is False
    assert asset.animation_binding_ready is False
    assert "RIGID_SKELETON_BINDING_NOT_READY" in plan["blockers"]
    assert plan["channels"]["geometry"]["maturity"] == "BLOCKED_BY_BINDING"
    assert plan["channels"]["animation"]["maturity"] == "CONTEXT_INCOMPLETE"
